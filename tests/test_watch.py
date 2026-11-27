"""watch: a scan on a schedule that keeps a change log and alerts before the disk is full."""

import json
import os
import shutil
import stat
import tempfile

from helpers import HomeTestCase

KB = 1024
GB = 1000 * 1000 * 1000


class WatchTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.tool.CHANGE_MIN_BYTES = 100 * KB
        self.tool.LIST_MIN_BYTES = 0
        # free space is whatever the test says, not the real disk's
        self.free = 100 * GB
        real = self.tool.disk_numbers

        def disk_numbers(*a, **k):
            d = real(*a, **k)
            d["free"] = self.free
            return d
        self.tool.disk_numbers = disk_numbers
        # tests never call the real osascript
        self.notes = []
        self.tool.notify = lambda title, message: self.notes.append((title, message)) or True

    def watch(self, *argv):
        return self.run_tool("watch", "--time-limit", "60", *argv)

    def log(self):
        with open(os.path.join(self.home, ".local/state/disk-tool/changes.jsonl")) as f:
            return [json.loads(line) for line in f]

    def test_first_run_records_a_baseline_without_an_alert(self):
        self.write("Downloads/a.dmg", 200 * KB)
        rc, out = self.watch()
        self.assertEqual(rc, 0, out)
        self.assertIn("first run, baseline saved; 100.0 GB free. No alert.", out)
        self.assertEqual(out.count("\n"), 1, out)  # one line
        [entry] = self.log()
        self.assertTrue(entry["baseline"])
        self.assertFalse(entry["alert"])
        self.assertIsNone(entry["free_before"])
        self.assertEqual(entry["free_now"], 100 * GB)
        self.assertEqual(entry["items"], [])
        self.assertEqual(self.notes, [])
        path = os.path.join(self.home, ".local/state/disk-tool/changes.jsonl")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        # it saved a scan, as `scan` does
        self.assertTrue(os.path.exists(os.path.join(self.home,
                                                    ".local/state/disk-tool/latest.json")))

    def test_first_run_alerts_when_free_space_is_already_low(self):
        self.free = 10 * GB
        rc, out = self.watch()
        self.assertEqual(rc, 3, out)
        self.assertIn("free space 10.0 GB is below 40.0 GB", out)
        self.assertEqual(len(self.notes), 1)
        self.assertTrue(self.log()[0]["baseline"])

    def test_a_quiet_run_logs_the_changes_and_says_one_line(self):
        self.write("Downloads/a.dmg", 200 * KB)
        self.watch()
        self.write("Downloads/b.dmg", 200 * KB)
        self.free = 100 * GB - 1 * GB
        rc, out = self.watch()
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.count("\n"), 1, out)
        self.assertIn("free 100.0 GB -> 99.0 GB (-1.0 GB)", out)
        self.assertIn("1 change logged. No alert.", out)
        entry = self.log()[-1]
        self.assertFalse(entry["baseline"])
        self.assertTrue(entry["compared"])
        self.assertEqual(entry["free_change"], -1 * GB)
        [row] = entry["items"]
        self.assertEqual((row["change"], row["path"], row["kind"]), ("grew", "~/Downloads", "user"))
        self.assertGreaterEqual(row["delta"], 200 * KB)
        self.assertEqual(self.notes, [])

    def test_alert_when_free_space_is_below_the_minimum(self):
        self.watch()
        self.free = 30 * GB
        rc, out = self.watch("--max-drop-gb", "1000")
        self.assertEqual(rc, 3, out)
        self.assertIn("ALERT", out)
        self.assertIn("free space 30.0 GB is below 40.0 GB", out)
        self.assertNotIn("dropped", out)
        self.assertEqual(len(self.notes), 1)
        rc, out = self.watch("--min-free-gb", "20")
        self.assertEqual(rc, 0, out)

    def test_alert_when_free_space_drops_too_fast(self):
        self.write("Downloads/a.dmg", 200 * KB)
        self.watch()
        self.write("Movies/film.mov", 300 * KB)
        self.free = 90 * GB
        rc, out = self.watch()
        self.assertEqual(rc, 3, out)
        self.assertIn("Free 100.0 GB -> 90.0 GB (-10.0 GB)", out)
        self.assertIn("free space dropped by 10.0 GB (more than 5.0 GB)", out)
        self.assertIn("Biggest causes:", out)
        self.assertIn("~/Movies  (user, new", out)
        entry = self.log()[-1]
        self.assertTrue(entry["alert"])
        self.assertEqual(len(entry["reasons"]), 1)
        title, message = self.notes[0]
        self.assertIn("disk", title)
        self.assertIn("100.0 GB -> 90.0 GB", message)
        self.assertIn("~/Movies", message)

    def test_alert_when_one_item_grows_too_much(self):
        self.write("Library/Caches/com.example/blob", 100 * KB)
        self.watch()
        self.write("Library/Caches/com.example/blob2", 600 * KB)
        rc, out = self.watch("--max-item-growth-gb", "0.0005")  # 500 KB
        self.assertEqual(rc, 3, out)
        self.assertIn("grew by", out)
        self.assertIn("(more than 500 KB)", out)
        self.assertNotIn("below", out)
        self.assertNotIn("dropped", out)
        rc, out = self.watch("--max-item-growth-gb", "0.0005")  # nothing grew since
        self.assertEqual(rc, 0, out)

    def test_a_new_item_counts_as_growth(self):
        self.watch()
        self.write("Downloads/huge.dmg", 600 * KB)
        rc, out = self.watch("--max-item-growth-gb", "0.0005")
        self.assertEqual(rc, 3, out)
        self.assertIn("~/Downloads appeared with", out)

    def test_a_removed_item_is_logged_as_gone(self):
        self.write("Downloads/a.dmg", 300 * KB)
        self.watch()
        shutil.rmtree(os.path.join(self.home, "Downloads"))
        rc, out = self.watch()
        self.assertEqual(rc, 0, out)
        [row] = self.log()[-1]["items"]
        self.assertEqual((row["change"], row["path"], row["bytes"]), ("gone", "~/Downloads", 0))
        self.assertLess(row["delta"], 0)

    def test_the_log_keeps_the_biggest_changes_only(self):
        self.tool.WATCH_LOG_TOP = 2
        self.watch()
        for i, size in enumerate((150, 400, 250)):
            self.write(f"stuff{i}/x", size * KB)
        self.watch()
        entry = self.log()[-1]
        self.assertEqual([r["path"] for r in entry["items"]], ["~/stuff1", "~/stuff2"])
        self.assertEqual(entry["items_total"], 3)

    def test_private_folders_are_one_row_in_the_log(self):
        self.write("Developer/Acme/secret-zebra/big.bin", 300 * KB)
        self.write("Developer/Acme/quokka.pdf", 200 * KB)
        rc, out = self.run_tool("private", "add", "~/Developer/Acme")
        self.assertEqual(rc, 0, out)
        self.watch()
        self.write("Developer/Acme/secret-zebra/bigger.bin", 400 * KB)
        rc, out = self.watch("--max-item-growth-gb", "0.0001")
        self.assertEqual(rc, 3, out)
        rc, history = self.watch("--log")
        with open(os.path.join(self.home, ".local/state/disk-tool/changes.jsonl")) as f:
            raw = f.read()
        for text, where in ((out, "alert"), (history, "--log"), (raw, "change log"),
                            (repr(self.notes), "notification")):
            self.assertNotIn("zebra", text, where)
            self.assertNotIn("quokka", text, where)
        row = next(r for r in self.log()[-1]["items"] if r["path"] == "~/Developer/Acme")
        self.assertEqual(row["kind"], "private")

    def test_making_a_folder_private_scrubs_the_log(self):
        self.write("Work/one.bin", 50 * KB)
        self.watch()
        self.write("Work/secret-zebra/x.bin", 600 * KB)
        self.write("Work/node_modules/dep/index.js", 10 * KB)
        self.write("Work/package.json", 10)
        self.watch("--max-item-growth-gb", "0.0001")
        rc, out = self.run_tool("private", "add", "~/Work")
        self.assertEqual(rc, 0, out)
        with open(os.path.join(self.home, ".local/state/disk-tool/changes.jsonl")) as f:
            raw = f.read()
        self.assertNotIn("Work/", raw)
        self.assertIn("~/Work", raw)  # the folder itself, with its total, stays

    def test_log_prints_the_history_in_plain_words(self):
        rc, out = self.watch("--log")
        self.assertEqual(rc, 1)
        self.assertIn("No change log yet", out)
        self.watch()
        self.write("Downloads/a.dmg", 300 * KB)
        self.free = 80 * GB
        self.watch()
        self.watch()
        rc, out = self.watch("--log")
        self.assertEqual(rc, 0, out)
        self.assertIn("the last 3 of 3 runs, newest first", out)
        self.assertIn("(first run: baseline)", out)
        self.assertIn("free 100.0 GB -> 80.0 GB (-20.0 GB)  ALERT: free space dropped by 20.0 GB",
                      out)
        self.assertIn("new", out)
        self.assertIn("~/Downloads  (user, now", out)
        self.assertIn("nothing changed by more than", out)
        lines = [line for line in out.splitlines() if line and not line.startswith(" ")]
        self.assertIn("free 80.0 GB -> 80.0 GB", lines[1])  # newest first
        rc, out = self.watch("--log", "1")
        self.assertIn("the last 1 of 3 runs", out)
        self.assertNotIn("baseline", out)
        self.assertEqual(len(self.log()), 3)  # --log does not scan

    def test_a_failing_notifier_does_not_change_the_exit_code(self):
        def broken(title, message):
            raise RuntimeError("no notification center")
        self.tool.notify = broken
        self.free = 5 * GB
        rc, out = self.watch()
        self.assertEqual(rc, 3, out)

    def test_no_notify_skips_the_notification(self):
        self.free = 5 * GB
        rc, out = self.watch("--no-notify")
        self.assertEqual(rc, 3, out)
        self.assertEqual(self.notes, [])

    def test_negative_thresholds_are_refused_before_scanning(self):
        rc, out = self.watch("--max-drop-gb", "-1")
        self.assertEqual(rc, 2)
        self.assertIn("--max-drop-gb must be 0 or more", out)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local/state/disk-tool")))


class NotifyTest(HomeTestCase):
    """The real notify(), with a stand-in osascript on PATH: never the real one."""

    def setUp(self):
        super().setUp()
        self.bin = tempfile.mkdtemp(dir=self.tmp.name)
        old = os.environ.get("PATH")
        self.addCleanup(self._restore_env, "PATH", old)
        os.environ["PATH"] = self.bin

    def fake_osascript(self, exit_code):
        record = os.path.join(self.tmp.name, "args")
        path = os.path.join(self.bin, "osascript")
        with open(path, "w") as f:
            f.write(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{record}"\nexit {exit_code}\n')
        os.chmod(path, 0o755)
        return record

    def test_missing_osascript_is_not_an_error(self):
        self.assertFalse(self.tool.notify("t", "m"))

    def test_a_failing_osascript_is_not_an_error(self):
        record = self.fake_osascript(1)
        self.assertFalse(self.tool.notify('disk "tool"', "Free 5 GB."))
        with open(record) as f:
            args = f.read()
        self.assertIn("-e", args)
        self.assertIn('display notification "Free 5 GB." with title "disk \\"tool\\""', args)

    def test_a_working_osascript_reports_success(self):
        self.fake_osascript(0)
        self.assertTrue(self.tool.notify("t", "m"))
