"""Linked git worktrees: a clean candidate only when everything in it is committed and
pushed and nothing changed for the rule's days; removed with `git worktree remove`."""

import json
import os
import subprocess
import time
import unittest

from helpers import HAS_GIT, HomeTestCase, git


@unittest.skipUnless(HAS_GIT, "needs git")
class WorktreeTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.shift_clock(70)  # everything written now looks 70 days old
        self.app = os.path.dirname(self.write("Developer/app/README", 10))
        with open(os.path.join(self.app, ".gitignore"), "w") as f:
            f.write("node_modules/\n.env\n")
        git(self.app, "init", "-q")
        git(self.app, "add", ".")
        git(self.app, "commit", "-q", "-m", "first")
        self.remote = os.path.join(self.outside, "app.git")
        git(self.outside, "init", "-q", "--bare", self.remote)
        git(self.app, "remote", "add", "origin", self.remote)
        git(self.app, "push", "-q", "-u", "origin", "main")
        self.run_tool("policy", "init")

    def worktree(self, name, push=True):
        path = os.path.join(self.home, "Developer", name)
        git(self.app, "worktree", "add", "-q", "-b", name, path)
        if push:
            git(path, "push", "-q", "-u", "origin", name)
        return path

    def commit_file(self, name, rel, text=None):
        path = os.path.join(self.home, "Developer", name)
        self.write(f"Developer/{name}/{rel}", 10)
        if text is not None:
            with open(os.path.join(path, rel), "w") as f:
                f.write(text)
        git(path, "add", rel)
        git(path, "commit", "-q", "-m", "add " + rel)
        git(path, "push", "-q")

    def plan(self, *argv):
        self.run_tool("scan")
        rc, out = self.run_tool("clean", "--json", *argv)
        self.assertEqual(rc, 0, out)
        data = json.loads(out)
        return ([r["rel"] for r in data["remove"]],
                {r["rel"]: r["reason"] for r in data["left_alone"]})

    def test_only_a_clean_pushed_old_worktree_is_a_candidate(self):
        self.run_tool("policy", "set", "git-worktree", "clean")  # 60 days by default
        done = self.worktree("done")
        self.commit_file("done", "package.json")
        self.write("Developer/done/node_modules/dep/index.js", 10)  # ignored, rebuilds
        dirty = self.worktree("dirty")
        with open(os.path.join(dirty, "README"), "w") as f:
            f.write("changed")
        untracked = self.worktree("untracked")
        self.write("Developer/untracked/notes.txt", 10)
        unpushed = self.worktree("unpushed")
        self.write("Developer/unpushed/more.txt", 10)
        git(unpushed, "add", ".")
        git(unpushed, "commit", "-q", "-m", "local only")
        self.worktree("local", push=False)
        self.worktree("recent")
        self.touch_future("Developer/recent/README", 69)  # edited yesterday
        self.worktree("secret")
        self.write("Developer/secret/.env", 10)  # ignored, and would be lost
        committed = self.worktree("committed")
        self.write("Developer/committed/new.txt", 10)  # the file looks 70 days old
        future = str(int(time.time() + 69 * 86400)) + " +0000"  # the commit: yesterday
        env = dict(os.environ, GIT_COMMITTER_DATE=future, GIT_AUTHOR_DATE=future)
        for argv in (["add", "."], ["commit", "-q", "-m", "late"], ["push", "-q"]):
            subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid",
                            "-c", "commit.gpgsign=false", "-C", committed] + argv,
                           check=True, capture_output=True, env=env)

        remove, left = self.plan()
        self.assertEqual(remove, ["Developer/done"])
        self.assertIn("uncommitted or untracked", left["Developer/dirty"])
        self.assertIn("uncommitted or untracked", left["Developer/untracked"])
        self.assertIn("1 commits not pushed to origin/unpushed", left["Developer/unpushed"])
        self.assertIn("no upstream", left["Developer/local"])
        self.assertIn("in use 1 days ago (its last commit", left["Developer/committed"])
        self.assertNotIn("Developer/recent", left)  # changed recently: only counted
        rc, out = self.run_tool("clean", "--json")
        self.assertEqual(json.loads(out)["used_recently"]["count"], 1)
        self.assertIn("files git ignores that would be lost, such as .env",
                      left["Developer/secret"])
        self.assertNotIn("Developer/app", left)  # the main checkout is not a worktree

        rc, out = self.run_tool("clean")
        self.assertIn("~/Developer/done  (git worktree: everything committed and pushed to "
                      "origin/done, no commit or file change for 70 days", out)
        self.assertIn("removed with `git worktree remove`", out)
        rc, out = self.run_tool("clean", "--apply", "--json")
        self.assertEqual(rc, 0, out)
        applied = json.loads(out)
        self.assertEqual([r["rel"] for r in applied["removed"]], remove)
        self.assertEqual(applied["removed"][0]["done"], "git worktree remove")
        self.assertFalse(os.path.exists(done))
        listed = subprocess.run(["git", "-C", self.app, "worktree", "list"],
                                capture_output=True, text=True, check=True).stdout
        self.assertNotIn(done, listed)
        branches = subprocess.run(["git", "-C", self.app, "branch", "--list", "done"],
                                  capture_output=True, text=True).stdout
        self.assertIn("done", branches)  # the branch stays
        for name in ("dirty", "untracked", "unpushed", "local", "recent", "secret",
                     "committed"):
            self.assertTrue(os.path.isdir(os.path.join(self.home, "Developer", name)), name)
        self.assertTrue(os.path.isdir(self.app))

    def test_worktrees_are_ask_unless_the_policy_names_them(self):
        self.worktree("done")
        self.tool.LIST_MIN_BYTES = 0
        self.run_tool("policy", "set", "dev", "clean", "--older-than-days", "7")
        self.run_tool("scan")
        with open(self.tool.state_dir(self.home) + "/latest.json") as f:
            items = {r["rel"]: r for r in json.load(f)["items"]}
        self.assertEqual((items["Developer/done"]["id"], items["Developer/done"]["kind"]),
                         ("git-worktree", "dev"))
        remove, left = self.plan()
        self.assertNotIn("Developer/done", remove + list(left))
        rc, out = self.run_tool("undecided")
        self.assertIn("~/Developer/done", out)
        rc, out = self.run_tool("policy", "set", "~/Developer/done", "clean")
        self.assertIn("clean when unused 60 days", out)
        remove, _left = self.plan()
        self.assertEqual(remove, ["Developer/done"])

    def test_path_skips_the_age_but_not_the_git_checks(self):
        self.worktree("recent")
        self.touch_future("Developer/recent/README", 69)
        local = self.worktree("local", push=False)
        remove, left = self.plan("--path", "Developer/recent", "--path", "Developer/local")
        self.assertEqual(remove, ["Developer/recent"])
        self.assertIn("no upstream", left["Developer/local"])
        self.assertTrue(os.path.isdir(local))

    def test_build_output_inside_goes_with_the_worktree(self):
        self.run_tool("policy", "set", "git-worktree", "clean")
        self.run_tool("policy", "set", "node-modules", "clean")
        self.worktree("done")
        self.write("Developer/done/package.json", 10)
        git(os.path.join(self.home, "Developer/done"), "add", "package.json")
        git(os.path.join(self.home, "Developer/done"), "commit", "-q", "-m", "pkg")
        git(os.path.join(self.home, "Developer/done"), "push", "-q")
        self.write("Developer/done/node_modules/dep/index.js", 100 * 1024)
        remove, left = self.plan()
        self.assertEqual(remove, ["Developer/done"])
        self.assertIn("goes with the git worktree ~/Developer/done",
                      left["Developer/done/node_modules"])
        rc, out = self.run_tool("clean", "--json")
        row = json.loads(out)["remove"][0]
        self.assertGreaterEqual(row["bytes"], 100 * 1024)  # counts what is inside
        rc, out = self.run_tool("clean", "--apply")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("Skipped", out)
        self.assertFalse(os.path.exists(os.path.join(self.home, "Developer/done")))

    def test_a_repository_whose_config_runs_programs_is_not_checked(self):
        self.run_tool("policy", "set", "git-worktree", "clean")
        done = self.worktree("done")
        marker = os.path.join(self.outside, "ran")
        git(self.app, "config", "filter.x.clean", f"touch {marker}; cat")
        with open(os.path.join(done, ".gitattributes"), "w") as f:
            f.write("* filter=x\n")
        remove, left = self.plan()
        self.assertEqual(remove, [])
        self.assertIn("sets programs for git to run", left["Developer/done"])
        self.assertFalse(os.path.exists(marker))

    def test_a_forged_pointer_is_not_a_worktree(self):
        self.run_tool("policy", "set", "git-worktree", "clean")
        done = self.worktree("done")
        fake = os.path.join(self.home, "Developer", "fake")
        os.makedirs(fake)
        with open(os.path.join(done, ".git")) as f:
            pointer = f.read()
        with open(os.path.join(fake, ".git"), "w") as f:
            f.write(pointer)  # names done's admin folder, which names done, not fake
        remove, left = self.plan("--path", "Developer/fake")
        self.assertEqual(remove, [])
        self.assertIn("does not list it as a worktree", left["Developer/fake"])
        self.assertTrue(os.path.isdir(fake))

    def test_a_worktree_with_submodules_is_refused_without_entering_them(self):
        self.run_tool("policy", "set", "git-worktree", "clean")
        done = self.worktree("done")
        lib = os.path.join(self.outside, "lib-src")
        os.makedirs(lib)
        with open(os.path.join(lib, "x"), "w") as f:
            f.write("x")
        git(lib, "init", "-q")
        git(lib, "add", ".")
        git(lib, "commit", "-q", "-m", "lib")
        git(done, "-c", "protocol.file.allow=always", "submodule", "add", "-q", lib, "lib")
        git(done, "commit", "-q", "-m", "add lib")
        git(done, "push", "-q")
        marker = os.path.join(self.outside, "ran")
        git(os.path.join(done, "lib"), "config", "filter.x.clean", f"touch {marker}; cat")
        with open(os.path.join(done, "lib", ".gitattributes"), "w") as f:
            f.write("* filter=x\n")
        remove, left = self.plan()
        self.assertEqual(remove, [])
        self.assertIn("submodules", left["Developer/done"])
        self.assertFalse(os.path.exists(marker))

    def test_a_submodule_is_not_a_worktree(self):
        sub = os.path.join(self.outside, "lib.git")
        git(self.outside, "init", "-q", "--bare", sub)
        tmp = os.path.join(self.outside, "lib-src")
        os.makedirs(tmp)
        with open(os.path.join(tmp, "x"), "w") as f:
            f.write("x")
        git(tmp, "init", "-q")
        git(tmp, "add", ".")
        git(tmp, "commit", "-q", "-m", "lib")
        git(tmp, "push", "-q", sub, "HEAD:main")
        git(self.app, "-c", "protocol.file.allow=always", "submodule", "add", "-q", sub, "lib")
        self.run_tool("scan")
        with open(self.tool.state_dir(self.home) + "/latest.json") as f:
            ids = {r["rel"]: r["id"] for r in json.load(f)["items"]}
        self.assertNotEqual(ids.get("Developer/app/lib"), "git-worktree")

    def test_ignored_build_names_must_be_real_build_output_without_keys(self):
        self.run_tool("policy", "set", "git-worktree", "clean")
        for name in ("ok", "bare", "file", "envin", "nested"):
            self.worktree(name)
            self.commit_file(name, ".gitignore", "node_modules/\nbuild\n.env\n")
        for name in ("ok", "envin", "nested"):
            self.commit_file(name, "build.gradle")
        self.write("Developer/ok/build/classes/A.class", 10)
        self.write("Developer/bare/node_modules/dep/index.js", 10)  # no package.json
        self.write("Developer/file/build", 10)  # a file named build, not a folder
        self.write("Developer/envin/build/.env", 10)
        nested = self.mkdir("Developer/nested/build/tool")
        git(nested, "init", "-q")
        self.write("Developer/nested/build/tool/x", 10)
        remove, left = self.plan()
        self.assertEqual(remove, ["Developer/ok"])
        self.assertIn("not build output", left["Developer/bare"])
        self.assertIn("would be lost, such as build", left["Developer/file"])
        self.assertIn("build/.env", left["Developer/envin"])
        self.assertIn("another git project", left["Developer/nested"])

    def test_a_locked_worktree_stays(self):
        self.run_tool("policy", "set", "git-worktree", "clean")
        done = self.worktree("done")
        git(self.app, "worktree", "lock", done)
        remove, left = self.plan()
        self.assertEqual(remove, [])
        self.assertIn("locked", left["Developer/done"])

    def test_removal_checks_everything_again_right_before_git(self):
        self.run_tool("policy", "set", "git-worktree", "clean")
        done = self.worktree("done")
        self.commit_file("done", "package.json")
        self.write("Developer/done/node_modules/dep/index.js", 10)
        _remove, _left = self.plan()
        rc, out = self.run_tool("clean", "--json")
        row = json.loads(out)["remove"][0]
        planned = {"upstream": row["upstream"], "head": row["head"]}
        # what changed after the plan was made: each one alone keeps the worktree
        self.write("Developer/done/node_modules/dep/.env", 10)
        how, why, partly = self.tool.remove_worktree(self.home, done, planned)
        self.assertEqual((how, partly), (None, False))
        self.assertIn("node_modules/dep/.env", why)
        os.unlink(os.path.join(done, "node_modules/dep/.env"))
        git(self.app, "worktree", "lock", done)
        how, why, _partly = self.tool.remove_worktree(self.home, done, planned)
        self.assertIn("locked", why)
        git(self.app, "worktree", "unlock", done)
        how, why, _partly = self.tool.remove_worktree(self.home, done,
                                                      dict(planned, head="0" * 40))
        self.assertIn("changed since the dry run", why)
        self.assertTrue(os.path.isdir(done))
        how, why, _partly = self.tool.remove_worktree(self.home, done, planned)
        self.assertEqual(how, "git worktree remove", why)
        self.assertFalse(os.path.exists(done))

    def test_a_failed_removal_says_it_may_be_partial(self):
        self.run_tool("policy", "set", "git-worktree", "clean")
        done = self.worktree("done")
        self.commit_file("done", "package.json")
        self.write("Developer/done/node_modules/dep/index.js", 10)
        remove, _left = self.plan()
        self.assertEqual(remove, ["Developer/done"])
        os.chmod(os.path.join(done, "node_modules", "dep"), 0o500)  # git cannot empty it
        rc, out = self.run_tool("clean", "--apply", "--json")
        self.assertEqual(rc, 0, out)
        applied = json.loads(out)
        self.assertEqual(applied["removed"], [])
        self.assertEqual([r["rel"] for r in applied["partly_removed"]], ["Developer/done"])
        self.assertIn("failed part way", applied["partly_removed"][0]["reason"])

    def test_staged_submodule_pointer_is_a_change(self):
        self.run_tool("policy", "set", "git-worktree", "clean")
        done = self.worktree("done")
        head = subprocess.run(["git", "-C", done, "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
        git(done, "update-index", "--add", "--cacheinfo", f"160000,{head},lib")
        remove, left = self.plan()
        self.assertEqual(remove, [])
        self.assertIn("staged changes", left["Developer/done"])

    def test_a_repository_outside_home_keeps_its_worktrees(self):
        self.run_tool("policy", "set", "git-worktree", "clean")
        repo = os.path.join(self.outside, "elsewhere")
        os.makedirs(repo)
        with open(os.path.join(repo, "README"), "w") as f:
            f.write("x")
        git(repo, "init", "-q")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", "first")
        git(repo, "remote", "add", "origin", self.remote)
        git(repo, "push", "-q", "origin", "main:other")
        path = os.path.join(self.home, "Developer", "far")
        git(repo, "worktree", "add", "-q", "-b", "far", path)
        git(path, "push", "-q", "-u", "origin", "far")
        remove, left = self.plan()
        self.assertEqual(remove, [])
        self.assertIn("outside your home folder", left["Developer/far"])
        self.assertTrue(os.path.isdir(path))

    def test_relative_paths_worktree(self):
        self.run_tool("policy", "set", "git-worktree", "clean")
        path = os.path.join(self.home, "Developer", "rel")
        added = subprocess.run(["git", "-C", self.app, "worktree", "add", "-q",
                                "--relative-paths", "-b", "rel", path],
                               capture_output=True, text=True)
        if added.returncode != 0 and "relative-paths" in added.stderr:
            self.skipTest("git has no --relative-paths")
        self.assertEqual(added.returncode, 0, added.stderr)
        git(path, "push", "-q", "-u", "origin", "rel")
        with open(os.path.join(self.app, ".git", "worktrees", "rel", "gitdir")) as f:
            self.assertFalse(os.path.isabs(f.read().strip()))
        self.assertNotEqual(os.getcwd(), path)
        remove, left = self.plan()
        self.assertEqual(remove, ["Developer/rel"], left)
        rc, out = self.run_tool("clean", "--apply")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
