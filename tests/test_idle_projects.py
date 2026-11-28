"""Build output and dependencies (node_modules, .venv, build) go only when their project
has been idle for the rule's days: no commit and no change to its own files. A fresh
.git/index (what `git status` leaves behind) is not use."""

import json
import os
import subprocess
import time
import unittest

from helpers import HAS_GIT, HomeTestCase, git


@unittest.skipUnless(HAS_GIT, "needs git")
class IdleProjectTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.shift_clock(40)  # everything written now looks 40 days old
        self.run_tool("policy", "init")
        self.run_tool("policy", "set", "node-modules", "clean", "--older-than-days", "30")

    def project(self, name, use_git=True):
        root = os.path.dirname(self.write(f"Developer/{name}/package.json", 10))
        self.write(f"Developer/{name}/src/index.js", 10)
        self.write(f"Developer/{name}/node_modules/dep/index.js", 100 * 1024)
        with open(os.path.join(root, ".gitignore"), "w") as f:
            f.write("node_modules/\n")
        if use_git:
            git(root, "init", "-q")
            git(root, "add", ".")
            git(root, "commit", "-q", "-m", "first")
        return root

    def plan(self):
        self.run_tool("scan")
        rc, out = self.run_tool("clean", "--json")
        self.assertEqual(rc, 0, out)
        data = json.loads(out)
        return ([r["rel"] for r in data["remove"]],
                {r["rel"]: r["reason"] for r in data["left_alone"]})

    def test_fresh_git_index_is_not_use_but_a_fresh_file_is(self):
        idle = self.project("idle")
        subprocess.run(["git", "-C", idle, "status"], capture_output=True, check=True)
        self.touch_future("Developer/idle/.git", 39)  # index and .git look used yesterday
        self.project("active")
        self.touch_future("Developer/active/src/index.js", 39)  # edited yesterday
        remove, left = self.plan()
        self.assertEqual(remove, ["Developer/idle/node_modules"])
        self.assertIn("its project ~/Developer/active was in use 1 days ago",
                      left["Developer/active/node_modules"])
        rc, out = self.run_tool("clean")
        self.assertIn("project ~/Developer/idle idle 40 days", out)
        rc, out = self.run_tool("clean", "--apply", "--json")
        done = json.loads(out)
        self.assertEqual([r["rel"] for r in done["removed"]], remove)
        self.assertFalse(os.path.exists(os.path.join(idle, "node_modules")))
        self.assertTrue(os.path.exists(os.path.join(self.home,
                                                    "Developer/active/node_modules")))

    def test_a_recent_commit_is_use(self):
        root = self.project("committed")
        future = str(int(time.time() + 39 * 86400))
        env = dict(os.environ, GIT_COMMITTER_DATE=future + " +0000",
                   GIT_AUTHOR_DATE=future + " +0000")
        with open(os.path.join(root, "README"), "w") as f:
            f.write("x")
        os.utime(os.path.join(root, "README"), (time.time(), time.time()))
        subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid",
                        "-c", "commit.gpgsign=false", "-C", root, "add", "."],
                       check=True, capture_output=True, env=env)
        subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid",
                        "-c", "commit.gpgsign=false", "-C", root, "commit", "-q", "-m", "2"],
                       check=True, capture_output=True, env=env)
        remove, left = self.plan()
        self.assertEqual(remove, [])
        self.assertIn("was in use 1 days ago", left["Developer/committed/node_modules"])

    def test_a_project_without_git_uses_its_files(self):
        self.project("plain-idle", use_git=False)
        self.project("plain-active", use_git=False)
        self.touch_future("Developer/plain-active/src", 39)
        remove, left = self.plan()
        self.assertEqual(remove, ["Developer/plain-idle/node_modules"])
        self.assertIn("was in use", left["Developer/plain-active/node_modules"])

    def test_build_output_changes_are_not_use(self):
        self.project("rebuilt", use_git=False)
        self.write("Developer/rebuilt/.next/cache/x", 10)  # another build folder
        self.touch_future("Developer/rebuilt/.next", 39)
        remove, _left = self.plan()
        self.assertEqual(remove, ["Developer/rebuilt/node_modules"])

    def test_a_submodule_of_a_git_project_counts_the_whole_checkout(self):
        root = self.project("mono")
        self.write("Developer/mono/packages/web/package.json", 10)
        self.write("Developer/mono/packages/web/node_modules/dep/index.js", 10)
        self.write("Developer/mono/packages/api/main.js", 10)
        self.touch_future("Developer/mono/packages/api", 39)  # edited elsewhere in the repo
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "more")
        remove, left = self.plan()
        self.assertEqual(remove, [])
        self.assertIn("its project ~/Developer/mono was in use",
                      left["Developer/mono/packages/web/node_modules"])

    def test_apply_reads_project_use_again(self):
        self.project("idle")
        self.project("plain", use_git=False)
        remove, _left = self.plan()
        self.assertEqual(sorted(remove), ["Developer/idle/node_modules",
                                          "Developer/plain/node_modules"])
        self.touch_future("Developer/idle/src/index.js", 39)  # edited after the dry run
        self.touch_future("Developer/plain/src", 39)
        rc, out = self.run_tool("clean", "--apply", "--json")
        self.assertEqual(json.loads(out)["removed"], [])
        for name in ("idle", "plain"):
            self.assertTrue(os.path.isdir(os.path.join(self.home, "Developer", name,
                                                       "node_modules")))

    def test_apply_leaves_output_when_use_cannot_be_read_again(self):
        self.project("plain", use_git=False)
        remove, _left = self.plan()
        self.assertEqual(remove, ["Developer/plain/node_modules"])
        self.tool.project_activity = lambda *_args: None
        rc, out = self.run_tool("clean", "--apply", "--json")
        self.assertEqual(json.loads(out)["removed"], [])
        self.assertTrue(os.path.isdir(os.path.join(self.home, "Developer/plain/node_modules")))

    def test_apply_still_removes_an_unchanged_idle_project(self):
        self.project("plain", use_git=False)
        remove, _left = self.plan()
        self.assertIn("Developer/plain/node_modules", remove)
        rc, out = self.run_tool("clean", "--apply", "--json")
        self.assertEqual(rc, 0, out)
        self.assertEqual([r["rel"] for r in json.loads(out)["removed"]], remove)
        self.assertFalse(os.path.exists(os.path.join(self.home, "Developer/plain/node_modules")))

    def test_an_unreadable_folder_in_build_output_does_not_hide_use(self):
        self.project("plain", use_git=False)
        locked = self.mkdir("Developer/plain/node_modules/dep/locked")
        os.chmod(locked, 0)
        result, _items = self.scan()
        self.assertFalse(result["projects"]["Developer/plain"]["partial"])
        os.chmod(locked, 0o700)
        own = self.mkdir("Developer/plain/src/locked")
        os.chmod(own, 0)  # one of the project's own folders: its use is not known
        result, _items = self.scan()
        self.assertTrue(result["projects"]["Developer/plain"]["partial"])
        os.chmod(own, 0o700)

    def test_activity_walk_does_not_enter_build_output(self):
        self.project("plain", use_git=False)
        self.write("Developer/plain/node_modules/dep/deep/x.js", 10)
        remove, _left = self.plan()
        self.assertEqual(remove, ["Developer/plain/node_modules"])
        seen, real_walk = [], self.tool.walk

        def spy(base, roots, on_listing, *args, **kwargs):
            def listing(rel, ctx, msg):
                seen.append(rel)
                return on_listing(rel, ctx, msg)
            return real_walk(base, roots, listing, *args, **kwargs)
        self.tool.walk = spy
        again = self.tool.project_activity(self.home, "Developer/plain", 60, 20, [])
        self.assertIsNotNone(again)
        self.assertIn(("Developer", "plain", "src"), seen)
        self.assertFalse([r for r in seen if "node_modules" in r], seen)

    def test_staged_submodule_pointer_in_build_output_keeps_it(self):
        root = self.project("staged")
        remote = os.path.join(self.outside, "staged.git")
        git(self.outside, "init", "-q", "--bare", remote)
        nm = os.path.join(root, "node_modules", "dep")
        git(nm, "init", "-q")
        git(nm, "add", ".")
        git(nm, "commit", "-q", "-m", "dep")
        git(nm, "remote", "add", "origin", remote)
        git(nm, "push", "-q", "-u", "origin", "HEAD:main")
        git(nm, "fetch", "-q", "origin")
        head = subprocess.run(["git", "-C", nm, "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
        git(nm, "update-index", "--add", "--cacheinfo", f"160000,{head},vendored")
        remove, left = self.plan()
        self.assertEqual(remove, [])
        self.assertIn("has uncommitted changes", left["Developer/staged/node_modules"])

    def test_an_old_scan_without_project_data_cleans_no_build_output(self):
        self.project("idle")
        self.run_tool("scan")
        path = self.tool.state_dir(self.home) + "/latest.json"
        with open(path) as f:
            data = json.load(f)
        del data["projects"]
        with open(path, "w") as f:
            json.dump(data, f)
        rc, out = self.run_tool("clean", "--json")
        data = json.loads(out)
        self.assertEqual(data["remove"], [])
        self.assertIn("scan again", data["left_alone"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
