"""Stall budgets, parallel walkers that agree with a plain walk, and the read-only summary
of folders outside the home folder (against a fake root only)."""

import json
import os
import time

from helpers import HomeTestCase

KB = 1024
HANG_ENV = "DISK_TOOL_TEST_HANG"
ROOT_ENV = "DISK_TOOL_ROOT"


class StallBudgetTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(os.environ.pop, HANG_ENV, None)

    def test_three_stalls_in_one_folder_skip_the_rest_of_it(self):
        names = [f"com.example.{c}" for c in "abcdef"]
        for name in names:
            self.write(f"Library/Containers/{name}/Data/x")
        os.environ[HANG_ENV] = ",".join(names)
        self.tool.SIBLING_STALL_LIMIT = 0.3
        started = time.monotonic()
        result = self.tool.scan_home(self.home, 60, stall_limit=1)
        took = time.monotonic() - started
        rows = result["not_measured"]
        self.assertEqual(sum(r["reason"] == "no-answer" for r in rows), 3)
        grouped = [dict(r) for r in rows if r["reason"] == "skipped-after-stalls"]
        skipped = grouped[0].pop("names")  # kept so the next scan does not call them new
        self.assertEqual(len(skipped), 3)
        self.assertTrue(set(skipped) <= set(names), skipped)
        self.assertEqual(grouped, [{"rel": "Library/Containers",
                                    "reason": "skipped-after-stalls", "count": 3}])
        listed = {r["rel"] for r in result["items"]}
        for name in names:  # skipped folders are not measured, never shown as 0
            self.assertNotIn(f"Library/Containers/{name}", listed)
        self.assertLess(took, 4)  # 1 + 0.3 + 0.3 s of waiting, not six stalls
        out = self.run_tool("scan", "--stall-limit", "1")[1]
        self.assertIn("~/Library/Containers: 3 more folders skipped after macOS did not answer "
                      "for 3 of them", out)

    def test_stalls_never_cost_more_than_the_budget(self):
        hangs = {"Library/Mail/V10": "V10", "Library/Messages/Archive": "Archive",
                 "Library/Safari/Tabs": "Tabs", "Library/Containers/com.example.x": "com.example.x",
                 "Library/Group Containers/group.example": "group.example"}
        for rel in hangs:
            self.write(rel + "/f")
        os.environ[HANG_ENV] = ",".join(hangs.values())
        self.tool.STALL_BUDGET = 1.5
        self.tool.LATE_STALL_LIMIT = 0.2
        started = time.monotonic()
        result = self.tool.scan_home(self.home, 60, stall_limit=1)
        took = time.monotonic() - started
        rows = result["not_measured"]
        self.assertLessEqual(sum(r["reason"] == "no-answer" for r in rows), 2)
        self.assertTrue(any(r["reason"] == "skipped-stall-budget" for r in rows), rows)
        self.assertLess(took, 3.5)
        self.assertFalse(result["complete"])


class ParallelWalkTest(HomeTestCase):
    def build(self):
        for area in ("Library/Caches/com.example.app", "Developer/repo/node_modules",
                     "Documents/archive", "Library/Application Support/Example", "Misc"):
            for a in range(6):
                for b in range(6):
                    self.write(f"{area}/a{a}/b{b}/c/file.txt", 5000 + 100 * a + b)
                    self.write(f"{area}/a{a}/b{b}/c/d/e/deep.bin", 9000)
        self.write("Developer/repo/package.json", 10)
        os.link(os.path.join(self.home, "Misc/a0/b0/c/file.txt"),
                os.path.join(self.home, "Documents/hardlink.txt"))

    def plain_total(self):
        seen, total = set(), 0
        for root, dirs, files in os.walk(self.home):
            for name in dirs + files:
                st = os.lstat(os.path.join(root, name))
                if st.st_nlink > 1 and not os.path.isdir(os.path.join(root, name)):
                    if (st.st_dev, st.st_ino) in seen:
                        continue
                    seen.add((st.st_dev, st.st_ino))
                total += st.st_blocks * 512
        return total

    def test_parallel_and_serial_walks_agree_with_a_plain_walk(self):
        self.build()
        self.tool.WALKERS = 1
        one, items_one = self.scan()
        self.tool.WALKERS, self.tool.UNIT_DEPTH, self.tool.UNITS_PER_JOB = 4, 1, 2
        four, items_four = self.scan()
        self.assertEqual({k: v["bytes"] for k, v in items_one.items()},
                         {k: v["bytes"] for k, v in items_four.items()})
        self.assertEqual(one["measured_bytes"], self.plain_total())
        self.assertEqual(four["measured_bytes"], self.plain_total())
        self.assertEqual(items_four["Developer/repo/node_modules"]["id"], "node-modules")


class OutsideTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.outside, "root")
        self.addCleanup(os.environ.pop, ROOT_ENV, None)
        self.addCleanup(os.environ.pop, HANG_ENV, None)

    def put(self, rel, size=64 * KB):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"\0" * size)

    def build(self):
        self.put("Applications/Big.app/Contents/MacOS/Big", 600 * KB)
        self.put("Library/Caches/com.example.system/c")
        self.put("Users/Shared/shared.bin", 200 * KB)
        self.put("private/var/log/system.log")
        self.put("private/var/db/locked/x")
        os.chmod(os.path.join(self.root, "private/var/db/locked"), 0)
        self.addCleanup(os.chmod, os.path.join(self.root, "private/var/db/locked"), 0o700)
        self.put("opt/homebrew/Cellar/tool/bin", 300 * KB)
        self.put("Users/alice/Documents/private.txt")  # another account
        os.chmod(os.path.join(self.root, "Users/alice"), 0)
        self.addCleanup(os.chmod, os.path.join(self.root, "Users/alice"), 0o700)
        self.write("Documents/mine.txt", 100 * KB)
        os.environ[ROOT_ENV] = self.root
        os.environ[HANG_ENV] = "alice"  # if anything walked into alice, it would hang there
        self.tool._snapshot_count = lambda root: 3
        self.tool._volume_used = lambda home: 50 * 1000 * 1000

    def test_outside_summary_sizes_and_other_accounts_by_name_only(self):
        self.build()
        self.tool.LIST_MIN_BYTES = 0
        rc, out = self.run_tool("scan", "--json")
        data = json.loads(out)
        o = data["outside"]
        self.assertTrue(o["scanned"] and o["complete"], o)
        sizes = {m["path"]: m for m in o["locations"]}
        self.assertEqual(set(sizes), {"/Applications", "/Library", "/Users/Shared",
                                      "/private/var", "/opt"})
        self.assertGreaterEqual(sizes["/Applications"]["bytes"], 600 * KB)
        self.assertEqual(sizes["/Applications"]["biggest_inside"][0]["name"], "Big.app")
        self.assertEqual(sizes["/private/var"]["not_measured"], 1)
        self.assertTrue(sizes["/private/var"]["partial"])
        self.assertEqual(o["other_accounts"], ["alice"])
        self.assertEqual(o["local_snapshots"], 3)
        d = data["disk"]
        self.assertEqual(d["outside_measured"], o["bytes"])
        self.assertEqual(d["rest"], 50 * 1000 * 1000 - d["home_measured"] - o["bytes"])
        self.assertFalse(any("alice" in json.dumps(m) for m in o["locations"]))

        rc, out = self.run_tool("scan")
        self.assertIn("Outside your home folder (sizes only; nothing here is ever cleaned):", out)
        self.assertIn("/Applications  Apps for every account", out)
        self.assertIn("another account: alice (not measured: only that account can look)", out)
        self.assertIn("Local Time Machine snapshots: 3", out)
        self.assertRegex(out, r"Your data uses [0-9.]+ MB = [0-9.]+ KB in your home folder \+ "
                              r"[0-9.]+ MB in the folders outside it listed below \+ ")

    def test_nothing_outside_home_can_be_cleaned(self):
        self.build()
        self.run_tool("scan")
        rc, out = self.run_tool("clean", "--path",
                                os.path.join(self.root, "Applications/Big.app"))
        self.assertEqual(rc, 2)
        self.assertIn("not an item from the last scan", out)
        self.assertTrue(os.path.exists(os.path.join(self.root, "Applications/Big.app")))

    def test_with_another_home_and_no_test_root_nothing_outside_is_read(self):
        self.write("Documents/mine.txt")
        rc, out = self.run_tool("scan", "--json")
        self.assertEqual(json.loads(out)["outside"], {"scanned": False})
        self.assertIsNone(self.tool.outside_root(home_given=True))
        self.assertEqual(self.tool.outside_root(home_given=False), "/")
