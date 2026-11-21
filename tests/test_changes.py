"""Changes between two scans: what the earlier scan did not measure is never "new"."""

import json
import os

from helpers import HomeTestCase

KB = 1024
HANG_ENV = "DISK_TOOL_TEST_HANG"


def item(rel, kind, size, partial=False):
    return {"rel": rel, "kind": kind, "description": "", "bytes": size, "partial": partial}


class ChangesTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(os.environ.pop, HANG_ENV, None)
        self.tool.CHANGE_MIN_BYTES = 100 * KB

    def fake(self, items, not_measured=(), complete=None):
        kinds = {k: 0 for k in self.tool.KINDS}
        for r in items:
            kinds[r["kind"]] += r["bytes"]
        scan = {"scanned_at": "2026-01-01T00:00:00Z", "scanned_at_epoch": 0,
                "timed_out": False, "complete": not not_measured if complete is None else complete,
                "disk": {"free": 0}, "kinds": kinds, "items": list(items),
                "not_measured": list(not_measured), "not_reached": []}
        return scan

    def test_a_folder_skipped_last_time_is_measured_now_not_new(self):
        # The real case: macOS did not answer for folders next to Docker's, so the first
        # scan skipped Docker's disk image; the second measured it.
        names = [f"com.example.{c}" for c in "abcde"]
        for name in names:
            self.write(f"Library/Containers/{name}/Data/x")
        self.write("Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw", 300 * KB)
        os.environ[HANG_ENV] = ",".join(names + ["com.docker.docker"])
        self.tool.SIBLING_STALL_LIMIT = 0.3
        rc, out = self.run_tool("scan", "--json", "--stall-limit", "1")
        first = json.loads(out)
        self.assertFalse(first["complete"])
        self.assertNotIn("names", json.dumps(first["not_measured"]))  # saved scan only
        with open(os.path.join(self.home, ".local/state/disk-tool/latest.json")) as f:
            saved = json.load(f)["not_measured"]
        skipped = [r for r in saved if r["reason"] == "skipped-after-stalls"]
        self.assertEqual(len(skipped), 1, saved)
        self.assertEqual(len(skipped[0]["names"]), skipped[0]["count"])
        os.environ.pop(HANG_ENV)
        self.write("Downloads/really-new.dmg", 200 * KB)  # a real change next to it
        rc, out = self.run_tool("scan", "--json")
        ch = json.loads(out)["changes"]
        self.assertTrue(ch["available"])
        docker = "Library/Containers/com.docker.docker"
        self.assertNotIn(docker, [r["rel"] for r in ch["new"]])
        self.assertNotIn(docker, [r["rel"] for r in ch["grown"]])
        row = next(r for r in ch["newly_measured"] if r["rel"] == docker)
        self.assertEqual(row["last_time"], "not measured")
        self.assertGreaterEqual(row["bytes"], 300 * KB)
        self.assertLess(ch["kinds"]["dev"], 100 * KB)  # not a +300 KB change of "dev"
        self.assertEqual([r["rel"] for r in ch["new"]], ["Downloads"])
        self.assertGreaterEqual(ch["kinds"]["user"], 200 * KB)

    def test_text_report_shows_the_newly_measured_group(self):
        prev = self.fake([item("Documents", "user", 10 * KB)],
                         [{"rel": "Library/Containers", "reason": "skipped-after-stalls",
                           "count": 1, "names": ["com.docker.docker"]}])
        cur = self.fake([item("Documents", "user", 10 * KB),
                         item("Library/Containers/com.docker.docker", "dev", 500 * KB)])
        ch = self.tool.diff_scans(prev, cur)
        text = "\n".join(self.tool.render_changes(ch))
        self.assertIn("Measured now, skipped last time", text)
        self.assertIn("~/Library/Containers/com.docker.docker  (dev; last time not measured)",
                      text)
        self.assertNotIn("new  ", text)
        self.assertEqual(ch["kinds"]["dev"], 0)

    def test_skipped_names_keep_true_newcomers_next_to_them_new(self):
        prev = self.fake([], [{"rel": "Library/Containers", "reason": "skipped-after-stalls",
                               "count": 1, "names": ["com.docker.docker"]}])
        cur = self.fake([item("Library/Containers/com.docker.docker", "dev", 500 * KB),
                         item("Library/Containers/com.example.new", "apps", 200 * KB)])
        ch = self.tool.diff_scans(prev, cur)
        self.assertEqual([r["rel"] for r in ch["newly_measured"]],
                         ["Library/Containers/com.docker.docker"])
        self.assertEqual([r["rel"] for r in ch["new"]], ["Library/Containers/com.example.new"])
        self.assertEqual(ch["kinds"]["apps"], 200 * KB)

    def test_an_older_saved_scan_without_names_is_unknown_not_new(self):
        prev = self.fake([], [{"rel": "Library/Containers", "reason": "skipped-after-stalls",
                               "count": 3}])  # saved before skipped names were kept
        cur = self.fake([item("Library/Containers/com.docker.docker", "dev", 500 * KB),
                         item("Library/Containers/com.example.x", "apps", 200 * KB),
                         item("Downloads", "user", 200 * KB)])
        ch = self.tool.diff_scans(prev, cur)
        self.assertEqual(sorted(r["rel"] for r in ch["newly_measured"]),
                         ["Library/Containers/com.docker.docker",
                          "Library/Containers/com.example.x"])
        self.assertEqual([r["rel"] for r in ch["new"]], ["Downloads"])

    def test_no_answer_and_unreadable_folders_last_time_are_not_new(self):
        prev = self.fake([], [{"rel": "Library/Mail", "reason": "no-answer"},
                              {"rel": "Library/Safari", "reason": "privacy"}])
        cur = self.fake([item("Library/Mail", "apps", 500 * KB),
                         item("Library/Safari/Tabs", "apps", 500 * KB)])
        ch = self.tool.diff_scans(prev, cur)
        self.assertEqual(ch["new"], [])
        self.assertEqual(len(ch["newly_measured"]), 2)
        self.assertEqual(ch["kinds"]["apps"], 0)

    def test_growth_of_an_item_measured_only_partly_last_time_is_not_growth(self):
        prev = self.fake([item("Library", "unknown", 100 * KB, partial=True)],
                         [{"rel": "Library/Mail", "reason": "no-answer"}])
        cur = self.fake([item("Library", "unknown", 900 * KB)])
        ch = self.tool.diff_scans(prev, cur)
        self.assertEqual(ch["grown"], [])
        self.assertEqual(ch["newly_measured"][0]["last_time"], "partly measured")
        self.assertEqual(ch["newly_measured"][0]["before"], 100 * KB)
        self.assertEqual(ch["kinds"]["unknown"], 0)
        text = "\n".join(self.tool.render_changes(ch))
        self.assertIn("last time only partly measured, at least", text)

    def test_an_incomplete_scan_with_no_record_of_gaps_claims_nothing_new(self):
        prev = self.fake([], complete=False)
        del prev["not_measured"]
        cur = self.fake([item("Downloads", "user", 500 * KB)])
        ch = self.tool.diff_scans(prev, cur)
        self.assertEqual(ch["new"], [])
        self.assertEqual([r["rel"] for r in ch["newly_measured"]], ["Downloads"])

    def test_a_complete_previous_scan_still_reports_new(self):
        prev = self.fake([])
        cur = self.fake([item("Downloads", "user", 500 * KB)])
        ch = self.tool.diff_scans(prev, cur)
        self.assertEqual([r["rel"] for r in ch["new"]], ["Downloads"])
        self.assertEqual(ch["newly_measured"], [])
