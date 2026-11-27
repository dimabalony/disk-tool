"""undecided: what the policy says `ask` for and nothing decided yet, with first-seen dates."""

import json
import os

from helpers import HomeTestCase

KB = 1024
GB = 1000 * 1000 * 1000


class UndecidedTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.tool.LIST_MIN_BYTES = 0
        self.tool.CHANGE_MIN_BYTES = 100 * KB
        self.tool.notify = lambda title, message: True  # never the real osascript

    def build(self):
        self.write("stuff/blob.bin", 500 * KB)  # unknown: ask
        self.write("Projects/app/package.json", 10)
        self.write("Projects/app/node_modules/dep/index.js", 200 * KB)  # dev: ask
        self.write("Downloads/a.dmg", 300 * KB)  # user: keep
        self.write("Library/Caches/com.example/c", 100 * KB)  # cache: clean by default

    def undecided(self, *argv):
        rc, out = self.run_tool("undecided", "--json", *argv)
        self.assertEqual(rc, 0, out)
        return json.loads(out)

    def paths(self, data):
        """Paths listed, leaving out the test home's own ~/.local and ~/.config."""
        return [r["path"] for r in data["items"] if not r["path"].startswith("~/.")]

    def test_lists_ask_items_biggest_first_with_first_seen(self):
        self.build()
        self.run_tool("scan", "--json")
        data = self.undecided()
        paths = self.paths(data)
        self.assertEqual(paths[0], "~/stuff")
        self.assertIn("~/Projects/app/node_modules", paths)
        self.assertNotIn("~/Downloads", paths)  # user: keep
        self.assertNotIn("~/Library/Caches/com.example", paths)  # cache: clean
        sizes = [r["bytes"] for r in data["items"]]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertEqual(data["count"], len(data["items"]))
        self.assertEqual(data["bytes"], sum(sizes))
        stuff = data["items"][0]
        self.assertEqual((stuff["kind"], stuff["id"]), ("unknown", "unknown"))
        self.assertIsNotNone(stuff["first_seen"])
        self.assertEqual(stuff["grown_since_first_seen"], 0)
        rc, out = self.run_tool("undecided")
        self.assertEqual(rc, 0, out)
        self.assertIn("Undecided: ", out)
        self.assertIn("~/stuff  (unknown, first seen", out)
        self.assertIn("(dev: node-modules, first seen", out)
        self.assertIn("policy set <path> keep", out)

    def test_growth_is_measured_from_the_first_scan(self):
        self.build()
        self.run_tool("scan", "--json")
        first = self.undecided()["items"][0]
        self.write("stuff/more.bin", 300 * KB)
        self.run_tool("scan", "--json")
        now = self.undecided()["items"][0]
        self.assertEqual(now["path"], "~/stuff")
        self.assertEqual(now["first_seen"], first["first_seen"])
        self.assertGreaterEqual(now["grown_since_first_seen"], 300 * KB)

    def test_since_keeps_only_items_first_seen_since_then(self):
        self.build()
        self.run_tool("scan", "--json")
        self.shift_clock(40)
        self.write("Movies-old/new-thing/x.bin", 400 * KB)
        self.run_tool("scan", "--json")
        self.assertEqual(self.paths(self.undecided("--since", "30d")), ["~/Movies-old"])
        self.assertIn("~/stuff", self.paths(self.undecided("--since", "50d")))
        self.assertIn("~/stuff", self.paths(self.undecided("--since", "2000-01-01")))
        rc, out = self.run_tool("undecided", "--since", "30d")
        self.assertIn("Undecided new since", out)
        self.assertNotIn("~/stuff", out)
        rc, out = self.run_tool("undecided", "--since", "soon")
        self.assertEqual(rc, 2)
        self.assertIn("30d", out)

    def test_a_decision_removes_the_item_and_sticks(self):
        self.build()
        self.run_tool("scan", "--json")
        rc, out = self.run_tool("policy", "set", "~/stuff", "keep")
        self.assertEqual(rc, 0, out)
        self.assertIn("~/stuff: keep", out)
        rc, out = self.run_tool("policy", "set", "node-modules", "clean",
                                "--older-than-days", "14")
        self.assertEqual(rc, 0, out)
        paths = self.paths(self.undecided())
        self.assertNotIn("~/stuff", paths)
        self.assertNotIn("~/Projects/app/node_modules", paths)
        self.write("stuff/more.bin", 300 * KB)
        self.run_tool("scan", "--json")  # still decided after the next scan
        self.assertNotIn("~/stuff", self.paths(self.undecided()))
        with open(os.path.join(self.home, ".config/disk-tool/policy.json")) as f:
            self.assertEqual(json.load(f)["paths"], {"stuff": {"action": "keep"}})
        rc, out = self.run_tool("policy", "show")
        self.assertIn("By path", out)
        self.assertIn("keep", out)
        self.assertIn("~/stuff", out)
        # ask again puts it back
        self.run_tool("policy", "set", "~/stuff", "ask")
        self.assertIn("~/stuff", self.paths(self.undecided()))

    def test_path_decisions_keep_the_safety_rules(self):
        self.build()
        self.run_tool("scan", "--json")
        rc, out = self.run_tool("policy", "set", "~/stuff", "clean")
        self.assertEqual(rc, 2)
        self.assertIn("can never be clean", out)
        rc, out = self.run_tool("policy", "set", "~/not-there", "keep")
        self.assertEqual(rc, 2)
        self.assertIn("not an item from the last scan", out)
        rc, out = self.run_tool("policy", "set", "/elsewhere/x", "keep")
        self.assertEqual(rc, 2)
        self.assertIn("not inside your home folder", out)

    def test_clean_follows_a_path_decision(self):
        self.write("Library/Caches/com.example.a/c", 100 * KB)
        self.write("Library/Caches/com.example.b/c", 100 * KB)
        self.run_tool("policy", "init")
        self.run_tool("scan", "--json")
        rc, out = self.run_tool("policy", "set", "~/Library/Caches/com.example.a", "keep")
        self.assertEqual(rc, 0, out)
        self.shift_clock(40)  # both look unused for 40 days
        rc, out = self.run_tool("clean", "--json")
        self.assertEqual(rc, 0, out)
        plan = json.loads(out)
        self.assertEqual([r["rel"] for r in plan["remove"]], ["Library/Caches/com.example.b"])
        rc, out = self.run_tool("clean", "--json", "--path", "~/Library/Caches/com.example.a")
        [row] = json.loads(out)["left_alone"]
        self.assertEqual(row["reason"], "your policy says keep")

    def test_private_folders_show_path_and_total_only(self):
        self.write("Developer/Acme/secret-zebra/x.bin", 300 * KB)
        self.run_tool("scan", "--json")  # before it is private: names inside are seen
        rc, out = self.run_tool("private", "add", "~/Developer/Acme")
        self.assertEqual(rc, 0, out)
        with open(os.path.join(self.home, ".local/state/disk-tool/first-seen.json")) as f:
            self.assertNotIn("zebra", f.read())
        self.run_tool("scan", "--json")
        self.assertNotIn("~/Developer/Acme", self.paths(self.undecided()))  # private: keep
        self.run_tool("policy", "set", "private", "ask")
        data = self.undecided()
        [row] = [r for r in data["items"] if r["path"] == "~/Developer/Acme"]
        self.assertEqual(row["kind"], "private")
        self.assertNotIn("id", row)
        self.assertNotIn("description", row)
        rc, out = self.run_tool("undecided")
        self.assertNotIn("zebra", json.dumps(data) + out)
        with open(os.path.join(self.home, ".local/state/disk-tool/first-seen.json")) as f:
            self.assertNotIn("zebra", f.read())
        rc, out = self.run_tool("policy", "set", "~/Developer/Acme/secret-zebra", "keep")
        self.assertEqual(rc, 2)
        self.assertIn("is private", out)

    def test_making_a_folder_private_drops_path_rules_inside_it(self):
        self.write("Work/secret-zebra/x.bin", 300 * KB)
        self.write("Work/package.json", 10)
        self.write("Work/node_modules/dep/index.js", 200 * KB)
        self.run_tool("scan", "--json")
        rc, out = self.run_tool("policy", "set", "~/Work/node_modules", "keep")
        self.assertEqual(rc, 0, out)
        path = os.path.join(self.home, ".config/disk-tool/policy.json")
        with open(path) as f:  # hand-written rules inside count too
            policy = json.load(f)
        policy["paths"]["Work/secret-zebra"] = {"action": "keep"}
        policy["paths"]["Work"] = {"action": "keep"}
        with open(path, "w") as f:
            json.dump(policy, f)
        rc, out = self.run_tool("private", "add", "~/Work")
        self.assertEqual(rc, 0, out)
        with open(path) as f:
            self.assertEqual(json.load(f)["paths"], {"Work": {"action": "keep"}})
        rc, out = self.run_tool("policy", "show")
        self.assertIn("~/Work", out)
        self.assertNotIn("zebra", out)
        self.assertNotIn("node_modules", out)

    def test_first_seen_starts_from_the_scan_before_when_it_is_missing(self):
        self.build()
        self.run_tool("scan", "--json")
        with open(os.path.join(self.home, ".local/state/disk-tool/latest.json")) as f:
            first_at = json.load(f)["scanned_at_epoch"]
        os.unlink(os.path.join(self.home, ".local/state/disk-tool/first-seen.json"))
        self.shift_clock(10)
        self.run_tool("scan", "--json")
        data = self.undecided()
        stuff = next(r for r in data["items"] if r["path"] == "~/stuff")
        self.assertEqual(stuff["first_seen"], self.tool.iso(first_at))
        self.assertEqual(data["first_seen_tracked_since"], self.tool.iso(first_at))

    def test_no_scan_yet(self):
        rc, out = self.run_tool("undecided")
        self.assertEqual(rc, 1)
        self.assertIn("No scan yet", out)


class WatchUndecidedTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.tool.LIST_MIN_BYTES = 50 * KB  # leaves out the test home's own state files
        self.tool.CHANGE_MIN_BYTES = 100 * KB
        self.tool.notify = lambda title, message: True
        real = self.tool.disk_numbers

        def disk_numbers(*a, **k):
            d = real(*a, **k)
            d["free"] = 100 * GB
            return d
        self.tool.disk_numbers = disk_numbers

    def test_the_alert_ends_with_the_undecided_count(self):
        self.write("stuff/blob.bin", 500 * KB)
        self.run_tool("watch", "--time-limit", "60")
        self.write("other/blob.bin", 700 * KB)
        rc, out = self.run_tool("watch", "--time-limit", "60", "--max-item-growth-gb", "0.0005")
        self.assertEqual(rc, 3, out)
        last = out.strip().splitlines()[-1]
        self.assertRegex(last, r"^2 undecided items, .* in total: `disk-tool undecided` "
                               r"lists them biggest first\.$")

    def test_a_kept_item_that_grows_still_alerts(self):
        self.write("stuff/blob.bin", 100 * KB)
        self.run_tool("watch", "--time-limit", "60")
        rc, out = self.run_tool("policy", "set", "~/stuff", "keep")
        self.assertEqual(rc, 0, out)
        self.write("stuff/more.bin", 700 * KB)
        rc, out = self.run_tool("watch", "--time-limit", "60", "--max-item-growth-gb", "0.0005")
        self.assertEqual(rc, 3, out)
        self.assertIn("~/stuff grew by", out)
        self.assertIn("0 undecided items", out)
