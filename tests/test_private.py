"""Private folders: one line with the path and total size, nothing inside ever named."""

import contextlib
import io
import json
import os
import stat

from helpers import HomeTestCase

KB = 1024
SECRETS = ("zebra", "quokka", "ClientDocs", "secret-project")
HANG_ENV = "DISK_TOOL_TEST_HANG"


class PrivateTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(os.environ.pop, HANG_ENV, None)

    def build(self):
        self.write("Developer/Acme/secret-project-zebra/package.json", 10)
        self.write("Developer/Acme/secret-project-zebra/node_modules/dep/index.js", 300 * KB)
        self.write("Developer/Acme/secret-project-zebra/src/main.js", 200 * KB)
        self.write("Developer/Acme/ClientDocs/contract-quokka.pdf", 400 * KB)
        self.write("Developer/Acme/.cache/quokka-cache/blob", 50 * KB)
        self.write("Developer/mine/notes.txt", 100 * KB)
        self.tool.LIST_MIN_BYTES = 0
        self.tool.BIG_UNKNOWN_BYTES = 1  # two-level breakdowns everywhere
        self.tool.PROGRESS_EVERY = 0

    def assert_no_secrets(self, text, where):
        for word in SECRETS:
            self.assertNotIn(word, text, f"{word!r} leaked in {where}")

    def plain_total(self, rel):
        top = os.path.join(self.home, rel)
        total = os.lstat(top).st_blocks * 512
        for root, dirs, files in os.walk(top):
            for name in dirs + files:
                total += os.lstat(os.path.join(root, name)).st_blocks * 512
        return total

    def private_add(self, path):
        rc, out = self.run_tool("private", "add", path)
        self.assertEqual(rc, 0, out)
        return out

    def test_commands_work_before_any_scan_or_policy(self):
        self.mkdir("Developer/Acme")
        self.private_add("~/Developer/Acme")
        self.private_add(os.path.join(self.home, "Work"))
        self.private_add("Clients/Big")  # taken from the home folder
        rc, out = self.run_tool("private", "list")
        self.assertEqual(rc, 0)
        for rel in ("~/Developer/Acme", "~/Work", "~/Clients/Big"):
            self.assertIn(rel, out)
        path = os.path.join(self.home, ".config/disk-tool/private.json")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        rc, out = self.run_tool("private", "remove", "~/Work")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("~/Work", self.run_tool("private", "list")[1])
        for bad in (self.outside, self.home, "~"):
            rc, out = self.run_tool("private", "add", bad)
            self.assertEqual(rc, 2, bad)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config/disk-tool/policy.json")))

    def test_names_inside_appear_nowhere(self):
        self.build()
        self.private_add("~/Developer/Acme")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc, text = self.run_tool("scan")
        self.assertEqual(rc, 0, text)
        self.assert_no_secrets(text + err.getvalue(), "text output and progress")
        self.assertIn("~/Developer/Acme", text)
        rc, out = self.run_tool("scan", "--json")
        self.assert_no_secrets(out, "JSON")
        data = json.loads(out)
        acme = [i for i in data["kinds"]["private"]["items"] if i["rel"] == "Developer/Acme"]
        self.assertEqual(len(acme), 1)
        self.assertEqual(acme[0]["bytes"], self.plain_total("Developer/Acme"))
        self.assertEqual(acme[0]["biggest_inside"], [])
        dev = [i for i in data["kinds"]["unknown"]["items"] if i["rel"] == "Developer"][0]
        self.assertIn({"name": "Acme", "bytes": acme[0]["bytes"], "private": True},
                      dev["biggest_inside"])
        for name in ("latest.json", "previous.json"):
            with open(os.path.join(self.home, ".local/state/disk-tool", name)) as f:
                self.assert_no_secrets(f.read(), name)
        self.run_tool("policy", "init")
        self.run_tool("policy", "set", "dev", "clean", "--older-than-days", "0")
        for argv in (("clean",), ("clean", "--json")):
            rc, out = self.run_tool(*argv)
            self.assert_no_secrets(out, " ".join(argv))
        with open(os.path.join(self.home, ".local/state/disk-tool/clean-plan.json")) as f:
            self.assert_no_secrets(f.read(), "clean plan")

    def test_clean_refuses_the_private_folder_and_anything_inside(self):
        self.build()
        self.private_add("~/Developer/Acme")
        self.run_tool("scan")
        for rel in ("Developer/Acme", "Developer/Acme/secret-project-zebra/node_modules"):
            rc, out = self.run_tool("clean", "--path", rel)
            self.assertEqual(rc, 2, rel)
            self.assertIn("~/Developer/Acme is private", out)
        self.assertTrue(os.path.isdir(os.path.join(
            self.home, "Developer/Acme/secret-project-zebra/node_modules")))

    def test_saved_scans_are_scrubbed_when_a_folder_becomes_private(self):
        self.build()
        self.run_tool("scan")
        self.run_tool("scan")
        self.run_tool("clean", "--path", "Developer/Acme/secret-project-zebra/node_modules")
        self.private_add("~/Developer/Acme")
        state = os.path.join(self.home, ".local/state/disk-tool")
        for name in ("latest.json", "previous.json"):
            with open(os.path.join(state, name)) as f:
                self.assert_no_secrets(f.read(), name)
        self.assertFalse(os.path.exists(os.path.join(state, "clean-plan.json")))
        rc, out = self.run_tool("scan")
        self.assert_no_secrets(out, "the scan after")

    def test_a_folder_inside_that_never_answers_names_only_the_private_folder(self):
        self.build()
        self.private_add("~/Developer/Acme")
        os.environ[HANG_ENV] = "secret-project-zebra"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = self.tool.scan_home(self.home, 30, stall_limit=0.5, progress=True)
        self.assert_no_secrets(err.getvalue() + json.dumps(result), "stall report")
        rows = [r for r in result["not_measured"] if r["reason"] == "no-answer"]
        self.assertEqual([r["rel"] for r in rows], ["Developer/Acme"])

    def test_a_deep_private_folder_handed_between_walkers_stays_one_line(self):
        self.tool.UNIT_DEPTH, self.tool.UNITS_PER_JOB = 1, 1
        self.write("Work/clients/2026/Acme/secret-project-zebra/node_modules/x.js", 100 * KB)
        self.write("Work/clients/2026/Acme/secret-project-zebra/package.json", 10)
        self.write("Work/clients/2026/Acme/ClientDocs/a/b/c/quokka.txt", 70 * KB)
        self.private_add("~/Work/clients/2026/Acme")
        result, items = self.scan()
        self.assert_no_secrets(json.dumps(result), "deep private scan")
        self.assertEqual(items["Work/clients/2026/Acme"]["bytes"],
                         self.plain_total("Work/clients/2026/Acme"))
        self.assertEqual(items["Work/clients/2026/Acme"]["kind"], "private")
