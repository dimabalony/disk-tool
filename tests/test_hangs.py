"""A folder that never answers (macOS waiting on a privacy prompt) must not hang the tool.

The test hook DISK_TOOL_TEST_HANG=<name> makes the walker block forever right before it
opens a folder with that name, the way a blocked open() does.
"""

import json
import os
import signal
import subprocess
import sys
import time

from helpers import TOOL, HomeTestCase

MB = 1000 * 1000
HANG_ENV = "DISK_TOOL_TEST_HANG"


class HangTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(self._kill_leftovers)

    def start(self, *argv, hang=None):
        env = dict(os.environ)
        if hang:
            env[HANG_ENV] = hang
        return subprocess.Popen([sys.executable, TOOL] + list(argv) + ["--home", self.home],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                env=env)

    def run_cli(self, *argv, hang=None, timeout=20):
        started = time.monotonic()
        proc = self.start(*argv, hang=hang)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            self.fail(f"`{' '.join(argv)}` did not finish within {timeout} s")
        return proc.returncode, out, err, time.monotonic() - started

    def leftovers(self):
        """Processes whose command line names this test's private home folder."""
        ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True)
        rows = []
        for line in ps.stdout.splitlines():
            pid, _, command = line.strip().partition(" ")
            if self.home in command and int(pid) != os.getpid():
                rows.append((int(pid), command))
        return rows

    def _kill_leftovers(self):
        for pid, _ in self.leftovers():  # only processes this test started (unique folder)
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def build(self):
        self.write("Library/Mail/V10/inbox.mbox", 2 * MB)
        self.write("Documents/report.pdf", 2 * MB)
        self.write("Library/Caches/com.example.app/blob", 2 * MB)

    def test_scan_survives_a_folder_that_never_answers(self):
        self.build()
        rc, out, err, took = self.run_cli("scan", "--json", "--stall-limit", "1",
                                          "--time-limit", "30", hang="Mail")
        self.assertEqual(rc, 0, err)
        self.assertLess(took, 15)
        data = json.loads(out)
        rows = {r["rel"]: r["reason"] for r in data["not_measured"]}
        self.assertEqual(rows.get("Library/Mail"), "no-answer")
        listed = [i["rel"] for k in data["kinds"].values() for i in k["items"]]
        self.assertNotIn("Library/Mail", listed)  # not measured, never shown as 0
        self.assertIn("Documents", listed)
        self.assertIn("Library/Caches/com.example.app", listed)
        self.assertFalse(data["complete"])
        self.assertIn("did not answer", data["incomplete_reason"])
        self.assertEqual(self.leftovers(), [])

    def test_text_mode_says_what_it_is_doing(self):
        self.build()
        rc, out, err, took = self.run_cli("scan", "--stall-limit", "1", hang="Mail")
        self.assertEqual(rc, 0, err)
        self.assertIn("~/Library/Mail", err)
        self.assertIn("did not answer", err)
        self.assertIn("~/Library/Mail: macOS did not answer", out)
        self.assertEqual(self.leftovers(), [])

    def test_time_limit_holds_while_a_folder_hangs(self):
        self.build()
        rc, out, err, took = self.run_cli("scan", "--json", "--stall-limit", "60",
                                          "--time-limit", "2", hang="Mail")
        self.assertEqual(rc, 0, err)
        self.assertLess(took, 10)
        data = json.loads(out)
        self.assertFalse(data["complete"])
        self.assertIn("time limit", data["incomplete_reason"])
        self.assertEqual(self.leftovers(), [])

    def test_ctrl_c_and_sigterm_stop_the_walker(self):
        self.build()
        for sig in (signal.SIGINT, signal.SIGTERM):
            proc = self.start("scan", "--stall-limit", "60", "--time-limit", "60", hang="Mail")
            walker = []
            deadline = time.monotonic() + 10
            while not walker and time.monotonic() < deadline:
                walker = [p for p, cmd in self.leftovers() if p != proc.pid]
                time.sleep(0.1)
            self.assertTrue(walker, "the scan should walk in a child process")
            time.sleep(0.5)
            proc.send_signal(sig)
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                self.fail(f"the scan ignored {sig.name}")
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(self.leftovers(), [], sig.name)

    def test_clean_check_survives_a_folder_that_never_answers(self):
        self.write("Library/Caches/com.example.slow/sub/blob", 2 * MB)
        rc, out, err, _ = self.run_cli("scan")
        self.assertEqual(rc, 0, err)
        rc, out, err, took = self.run_cli("clean", "--path", "Library/Caches/com.example.slow",
                                          "--json", "--stall-limit", "1", hang="sub")
        self.assertEqual(rc, 0, err)
        self.assertLess(took, 15)
        data = json.loads(out)
        self.assertEqual(data["remove"], [])
        self.assertIn("did not answer", data["left_alone"][0]["reason"])
        self.assertTrue(os.path.exists(os.path.join(self.home, "Library/Caches/com.example.slow")))
        self.assertEqual(self.leftovers(), [])
