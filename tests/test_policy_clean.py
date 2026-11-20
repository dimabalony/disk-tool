import json
import os
import unittest

from helpers import HAS_GIT, HomeTestCase, git


class PolicyTest(HomeTestCase):
    def policy(self):
        with open(os.path.join(self.home, ".config/disk-tool/policy.json")) as f:
            return json.load(f)

    def test_init_writes_safe_defaults(self):
        rc, out = self.run_tool("policy", "init")
        self.assertEqual(rc, 0, out)
        policy = self.policy()
        self.assertEqual(policy["kinds"]["user"], {"action": "keep"})
        for kind in ("cache", "temp", "dev", "apps", "unknown"):
            self.assertEqual(policy["kinds"][kind], {"action": "ask"}, kind)
        self.assertEqual(policy["items"]["xcode-derived-data"],
                         {"action": "clean", "older_than_days": 30})
        for item_id, rule in policy["items"].items():
            entry = self.tool.ENTRIES[item_id]
            self.assertEqual((entry.kind, entry.returns), ("cache", "auto"), item_id)
        self.assertNotIn("xdg-cache", policy["items"])  # ~/.cache/* stays ask
        rc, out = self.run_tool("policy", "init")
        self.assertEqual(rc, 1)
        self.assertIn("already exists", out)

    def test_user_and_unknown_can_never_be_clean(self):
        self.run_tool("policy", "init")
        for target in ("user", "unknown", "documents", "downloads", "device-backups",
                       "docker-desktop"):
            rc, out = self.run_tool("policy", "set", target, "clean")
            self.assertEqual(rc, 2, target)
        self.assertEqual(self.policy()["kinds"]["user"], {"action": "keep"})
        rc, out = self.run_tool("policy", "set", "dev", "clean", "--older-than-days", "7")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.policy()["kinds"]["dev"], {"action": "clean", "older_than_days": 7})
        rc, out = self.run_tool("policy", "set", "nonsense-id", "keep")
        self.assertEqual(rc, 2)

    def test_hand_edited_policy_is_checked(self):
        self.run_tool("policy", "init")
        policy = self.policy()
        policy["kinds"]["unknown"] = {"action": "clean", "older_than_days": 1}
        with open(os.path.join(self.home, ".config/disk-tool/policy.json"), "w") as f:
            json.dump(policy, f)
        self.run_tool("scan")
        rc, out = self.run_tool("clean")
        self.assertEqual(rc, 2)
        self.assertIn("can never be clean", out)

    def test_show_lists_rules_and_catalog(self):
        rc, out = self.run_tool("policy", "show", "--all")
        self.assertEqual(rc, 0)
        self.assertIn("not saved yet", out)
        self.assertIn("xcode-derived-data", out)
        self.assertIn("never removed by this tool", out)


class CleanTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.shift_clock(40)  # everything written now looks 40 days old

    def exists(self, rel):
        return os.path.lexists(os.path.join(self.home, rel))

    def test_dry_run_then_apply(self):
        self.write("Library/Caches/com.example.old/blob", 300 * 1024)
        self.write("Library/Caches/com.example.fresh/blob")
        self.touch_future("Library/Caches/com.example.fresh", 39)
        self.write("Documents/keep-me.txt")
        self.run_tool("policy", "init")
        self.run_tool("scan")

        rc, out = self.run_tool("clean", "--apply")
        self.assertEqual(rc, 1)
        self.assertIn("without --apply first", out)
        self.assertTrue(self.exists("Library/Caches/com.example.old"))

        rc, out = self.run_tool("clean")
        self.assertEqual(rc, 0, out)
        self.assertIn("Dry run: nothing is removed", out)
        self.assertIn("~/Library/Caches/com.example.old", out)
        self.assertNotIn("com.example.fresh", out)
        self.assertIn("changed recently", out)
        self.assertTrue(self.exists("Library/Caches/com.example.old"))

        rc, out = self.run_tool("clean", "--apply")
        self.assertEqual(rc, 0, out)
        self.assertIn("moved to the Trash", out)
        self.assertFalse(self.exists("Library/Caches/com.example.old"))
        self.assertTrue(self.exists(".Trash/com.example.old/blob"))
        self.assertTrue(self.exists("Library/Caches/com.example.fresh"))
        self.assertTrue(self.exists("Documents/keep-me.txt"))

        rc, out = self.run_tool("clean", "--apply")  # the dry run is used up
        self.assertEqual(rc, 1)

    def test_apply_removes_only_what_the_dry_run_showed(self):
        self.write("Library/Caches/com.example.one/blob")
        self.run_tool("policy", "init")
        self.run_tool("scan")
        self.run_tool("clean")
        self.write("Library/Caches/com.example.two/blob")
        self.run_tool("scan")
        rc, out = self.run_tool("clean", "--apply")
        self.assertIn("was not in the dry run you checked", out)
        self.assertFalse(self.exists("Library/Caches/com.example.one"))
        self.assertTrue(self.exists("Library/Caches/com.example.two"))

    def test_trash_items_are_deleted_not_moved(self):
        self.write(".Trash/old.dmg")
        self.run_tool("scan")
        rc, out = self.run_tool("clean", "--path", ".Trash/old.dmg")
        self.assertIn("Would remove 1 item", out)
        self.assertIn("--path .Trash/old.dmg --apply", out)
        rc, out = self.run_tool("clean", "--path", ".Trash/old.dmg", "--apply")
        self.assertIn("deleted", out)
        self.assertEqual(os.listdir(os.path.join(self.home, ".Trash")), [])

    def test_never_removes_user_unknown_protected_or_keep(self):
        self.write("Documents/letter.txt")
        self.write("Developer/thing/file")
        self.write("Library/Containers/com.docker.docker/Data/vms/0/Docker.raw")
        self.write("Library/Application Support/MobileSync/Backup/0000/x")
        self.write("Library/Logs/App/log.txt")
        self.run_tool("policy", "init")
        self.run_tool("policy", "set", "logs", "keep")
        self.run_tool("scan")
        cases = {
            "Documents": "your own files",
            "Developer": "not in the catalog",
            "Library/Containers/com.docker.docker": "never removed by this tool",
            "Library/Application Support/MobileSync": "which your policy does not clean",
            "Library/Logs/App": "your policy says keep",
        }
        for rel, reason in cases.items():
            rc, out = self.run_tool("clean", "--path", rel)
            self.assertIn(reason, out, rel)
            self.assertIn("Nothing to remove", out, rel)
        rc, out = self.run_tool("clean", "--path", "Developer/thing")
        self.assertEqual(rc, 2)
        self.assertIn("not an item from the last scan", out)

    def test_path_checks(self):
        check = self.tool.check_path
        self.mkdir("Library/Caches/real")
        os.symlink(self.outside, os.path.join(self.home, "Library/Caches/out"))
        os.symlink(os.path.join(self.home, "Library/Caches/real"),
                   os.path.join(self.home, "Library/Caches/in"))
        os.symlink(os.path.join(self.home, "Library/Caches"), os.path.join(self.home, "lnk"))
        self.assertIsNone(check(self.home, os.path.join(self.home, "Library/Caches/real")))
        self.assertEqual(check(self.home, self.outside), "outside your home folder")
        self.assertEqual(check(self.home, self.home), "outside your home folder")
        self.assertIn("top-level", check(self.home, os.path.join(self.home, "Library")))
        self.assertEqual(check(self.home, os.path.join(self.home, "Library/Caches/out")),
                         "a link pointing outside your home folder")
        self.assertEqual(check(self.home, os.path.join(self.home, "Library/Caches/in")),
                         "a link, not the folder itself")
        self.assertEqual(check(self.home, os.path.join(self.home, "lnk/real")),
                         "reached through a link")


@unittest.skipUnless(HAS_GIT, "needs git")
class GitSafetyTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.shift_clock(40)

    def reason(self, rel):
        self.run_tool("scan")
        rc, out = self.run_tool("clean", "--path", rel, "--json")
        data = json.loads(out)
        if data["remove"]:
            return None
        return data["left_alone"][0]["reason"]

    def test_git_checkout_with_unsaved_work_is_refused(self):
        repo = os.path.dirname(self.write(".cache/sometool/checkout/README", 10))
        git(repo, "init", "-q")
        self.assertIn("uncommitted changes", self.reason(".cache/sometool"))
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", "first")
        self.assertIn("not pushed", self.reason(".cache/sometool"))
        remote = os.path.join(self.outside, "remote.git")
        git(self.outside, "init", "-q", "--bare", remote)
        git(repo, "remote", "add", "origin", remote)
        git(repo, "push", "-q", "origin", "main")
        self.assertIsNone(self.reason(".cache/sometool"))

    def test_files_tracked_by_the_project_around_it_are_refused(self):
        proj = os.path.dirname(self.write("Developer/app/package.json", 10))
        self.write("Developer/app/node_modules/dep/index.js", 10)
        git(proj, "init", "-q")
        self.assertIsNone(self.reason("Developer/app/node_modules"))  # untracked: fine
        git(proj, "add", ".")
        git(proj, "commit", "-q", "-m", "commit node_modules by mistake")
        self.assertEqual(self.reason("Developer/app/node_modules"), "git tracks files in it")


if __name__ == "__main__":
    unittest.main()
