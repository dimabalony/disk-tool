"""What a person reads: where the rest of the disk is, what a cut-short scan missed,
progress lines without file names, and what is inside a big unknown folder."""

import contextlib
import io
import os
import re
import time

from helpers import HomeTestCase

KB = 1024
HANG_ENV = "DISK_TOOL_TEST_HANG"


class ReportTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(os.environ.pop, HANG_ENV, None)

    def hang(self, *names):
        os.environ[HANG_ENV] = ",".join(names)

    def test_disk_line_accounts_for_the_whole_volume(self):
        self.write("Documents/a", 300 * KB)
        self.write("Library/Locked/x")
        os.chmod(os.path.join(self.home, "Library/Locked"), 0)
        self.addCleanup(os.chmod, os.path.join(self.home, "Library/Locked"), 0o700)
        self.tool._volume_used = lambda home: 900 * 1000 * 1000 * 1000
        result, _ = self.scan()
        d = result["disk"]
        self.assertEqual(d["home_measured"], result["measured_bytes"])
        self.assertIsNone(d["outside_measured"])  # --home given: nothing outside is scanned
        self.assertEqual(d["rest"], 900 * 1000 ** 3 - result["measured_bytes"])
        self.assertEqual(d["not_measured_count"], 1)
        self.assertIn("purgeable", d["note"])
        rc, out = self.run_tool("scan")
        self.assertRegex(out, r"Your data uses 900\.0 GB: [0-9.]+ KB measured in your home "
                              r"folder, 900\.0 GB outside it \(apps, macOS data, other user "
                              r"accounts\) or in the 1 folder not measured\.")
        self.assertIn("purgeable", out)

        self.tool._volume_used = lambda home: None  # diskutil missing: the volume's numbers
        result, _ = self.scan()
        self.assertIsNone(result["disk"]["data_volume_used"])
        self.assertEqual(result["disk"]["rest"],
                         result["disk"]["used"] - result["measured_bytes"])

    def test_cut_short_scan_lists_what_it_did_not_reach_and_walks_slow_areas_last(self):
        self.write("Library/Caches/com.example.app/blob")
        self.write("Library/Mobile Documents/com~apple~CloudDocs/a/b")
        self.write("Library/CloudStorage/Dropbox/c")
        self.write("Library/Containers/com.example.guarded/Data/e")
        self.write("Zeta/big", 300 * KB)
        self.write("Documents/d")
        self.hang("Mobile Documents", "CloudStorage")
        result, items = self.scan(time_limit=3)
        self.assertFalse(result["complete"])
        reached = {r["rel"]: r["status"] for r in result["not_reached"]}
        self.assertEqual(reached.get("Library/Mobile Documents"), "not started")
        self.assertEqual(reached.get("Library/CloudStorage"), "not started")  # cloud: last
        self.assertTrue(items["Library/Mobile Documents"]["partial"])
        for rel in ("Library/Caches/com.example.app", "Zeta", "Documents",  # done first,
                    "Library/Containers/com.example.guarded"):  # guarded before cloud
            self.assertGreater(items[rel]["bytes"], 60 * KB, rel)
            self.assertFalse(items[rel]["partial"], rel)
        self.tool.LIST_MIN_BYTES = 0
        rc, out = self.run_tool("scan", "--time-limit", "3")
        self.assertIn("Not reached before the time limit", out)
        self.assertIn("~/Library/Mobile Documents (not started)", out)
        self.assertIn("at least", out)

    def test_folders_next_to_a_stalled_one_get_a_short_limit(self):
        for name in ("com.a", "com.b", "com.c"):
            self.write(f"Library/Containers/{name}/Data/x")
        self.hang("com.a", "com.b", "com.c")
        self.tool.SIBLING_STALL_LIMIT = 0.3
        started = time.monotonic()
        result = self.tool.scan_home(self.home, 30, stall_limit=2)
        took = time.monotonic() - started
        stuck = [r["rel"] for r in result["not_measured"] if r["reason"] == "no-answer"]
        self.assertEqual(len(stuck), 3)
        self.assertLess(took, 4.5)  # 2 s for the first, 0.3 s for each sibling (6 s without)

    def test_progress_shows_at_most_three_folder_names(self):
        self.write("Library/Mobile Documents/iCloud~books/Documents/A Private Book.epub/ch1")
        self.write("Developer/one/two/three/four/file")
        self.hang("A Private Book.epub")
        self.tool.PROGRESS_EVERY = 0
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.tool.scan_home(self.home, 30, stall_limit=0.5, progress=True)
        text = err.getvalue()
        self.assertIn("did not answer", text)
        self.assertNotIn("Private Book", text)
        self.assertNotIn("four", text)
        for path in re.findall(r"~/[^ :]*", text):
            parts = [p for p in path[2:].split("/") if p and p != "..."]
            self.assertLessEqual(len(parts), 3, path)

    def test_big_unknown_folder_shows_two_levels_and_what_is_counted_elsewhere(self):
        self.tool.BIG_UNKNOWN_BYTES = 100 * KB
        self.tool.LIST_MIN_BYTES = 0
        self.write("Developer/Backend/repo1/package.json", 10)
        self.write("Developer/Backend/repo1/node_modules/dep/index.js", 300 * KB)
        self.write("Developer/Backend/repo1/src/main.js", 200 * KB)
        self.write("Developer/Backend/repo2/data.bin", 150 * KB)
        self.write("Developer/Personal/p/w", 50 * KB)
        result, items = self.scan()
        dev = items["Developer"]
        names = [c["name"] for c in dev["biggest_inside"]]
        self.assertEqual(names[:2], ["Backend/repo1", "Backend/repo2"])
        self.assertIn("Personal/p", names)
        self.assertGreaterEqual(dev["counted_elsewhere"]["bytes"], 300 * KB)
        self.assertEqual(list(dev["counted_elsewhere"]["by_kind"]), ["dev"])
        self.assertEqual(dev["counted_elsewhere"]["names"], ["node_modules"])
        self.assertEqual(dev["whole_folder_bytes"],
                         dev["bytes"] + dev["counted_elsewhere"]["bytes"])
        self.tool.LIST_MIN_BYTES = 1
        rc, out = self.run_tool("scan")
        self.assertRegex(out, r"the whole folder is [0-9.]+ KB; [0-9.]+ KB of it is counted "
                              r"above \(dev [0-9.]+ KB: node_modules\)")
        self.assertIn("the rest is mostly in: Backend/repo1", out)
