"""Containers: `clean` judges each folder inside them on its own (one compiler version,
one project's build files), removes the stale ones and leaves the rest."""

import json

from helpers import HomeTestCase


class ContainerTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.shift_clock(40)  # everything written now looks 40 days old

    def exists(self, rel):
        import os
        return os.path.lexists(os.path.join(self.home, rel))

    def plan(self, *argv):
        rc, out = self.run_tool("clean", "--json", *argv)
        self.assertEqual(rc, 0, out)
        return json.loads(out)

    def test_only_the_stale_unit_goes_and_apply_equals_the_dry_run(self):
        dd = "Library/Developer/Xcode/DerivedData"
        self.write(f"{dd}/Old-abc/Build/Products/app.o", 200 * 1024)
        self.write(f"{dd}/New-def/Build/Products/app.o", 100 * 1024)
        self.touch_future(f"{dd}/New-def", 39)  # built yesterday
        self.write(f"{dd}/info.plist", 10)  # a loose file: never a unit
        self.run_tool("policy", "init")
        self.run_tool("scan")

        plan = self.plan()
        listed = [r["rel"] for r in plan["remove"]]
        self.assertEqual(listed, [f"{dd}/Old-abc"])
        self.assertEqual(plan["remove"][0]["part_of"], dd)
        self.assertGreaterEqual(plan["remove"][0]["days_unchanged"], 39)
        self.assertEqual(plan["used_recently"]["count"], 1)

        rc, out = self.run_tool("clean")
        self.assertIn(f"~/{dd}/Old-abc", out)
        self.assertIn("unchanged 40 days", out)
        self.assertNotIn("New-def", out)
        rc, out = self.run_tool("clean", "--apply", "--json")
        self.assertEqual(rc, 0, out)
        done = json.loads(out)
        self.assertEqual([r["rel"] for r in done["removed"]], listed)
        self.assertEqual(done["skipped"], [])
        self.assertFalse(self.exists(f"{dd}/Old-abc"))
        self.assertTrue(self.exists(".Trash/Old-abc/Build/Products/app.o"))
        self.assertTrue(self.exists(f"{dd}/New-def/Build/Products/app.o"))
        self.assertTrue(self.exists(f"{dd}/info.plist"))

    def test_konan_versions_and_dependencies_are_units(self):
        self.write(".konan/kotlin-native-prebuilt-macos-aarch64-1.9.0/bin/konanc")
        self.write(".konan/kotlin-native-prebuilt-macos-aarch64-2.0.0/bin/konanc")
        self.touch_future(".konan/kotlin-native-prebuilt-macos-aarch64-2.0.0", 39)
        self.write(".konan/dependencies/llvm-11-old/bin/clang")
        self.write(".konan/dependencies/llvm-16-new/bin/clang")
        self.touch_future(".konan/dependencies/llvm-16-new", 39)
        self.write(".konan/dependencies/.extracted", 10)
        self.run_tool("policy", "init")
        self.run_tool("policy", "set", "konan", "clean", "--older-than-days", "30")
        self.run_tool("scan")
        listed = sorted(r["rel"] for r in self.plan()["remove"])
        self.assertEqual(listed, [".konan/dependencies/llvm-11-old",
                                  ".konan/kotlin-native-prebuilt-macos-aarch64-1.9.0"])
        self.run_tool("clean")
        rc, out = self.run_tool("clean", "--apply")
        self.assertEqual(rc, 0, out)
        for rel in listed:
            self.assertFalse(self.exists(rel), rel)
        for rel in (".konan/kotlin-native-prebuilt-macos-aarch64-2.0.0/bin/konanc",
                    ".konan/dependencies/llvm-16-new/bin/clang",
                    ".konan/dependencies/.extracted"):
            self.assertTrue(self.exists(rel), rel)

    def test_path_takes_every_unit_but_not_loose_files(self):
        self.write(".gradle/wrapper/dists/gradle-8.5-bin/abc/gradle-8.5/lib/a.jar")
        self.write(".gradle/wrapper/dists/gradle-8.9-bin/def/gradle-8.9/lib/a.jar")
        self.touch_future(".gradle/wrapper/dists/gradle-8.9-bin", 39)
        self.write(".gradle/wrapper/dists/README", 10)
        self.run_tool("scan")
        plan = self.plan("--path", ".gradle/wrapper/dists")
        self.assertEqual(sorted(r["rel"] for r in plan["remove"]),
                         [".gradle/wrapper/dists/gradle-8.5-bin",
                          ".gradle/wrapper/dists/gradle-8.9-bin"])

    def test_a_unit_holding_a_git_project_with_unsaved_work_stays(self):
        from helpers import HAS_GIT, git
        if not HAS_GIT:
            self.skipTest("needs git")
        repo = self.mkdir("Library/Caches/JetBrains/IdeaIC2023.1/plugins/thing")
        self.write("Library/Caches/JetBrains/IdeaIC2023.1/plugins/thing/x", 10)
        git(repo, "init", "-q")
        self.write("Library/Caches/JetBrains/IdeaIC2022.3/index/x")
        self.run_tool("policy", "init")
        self.run_tool("scan")
        plan = self.plan()
        self.assertEqual([r["rel"] for r in plan["remove"]],
                         ["Library/Caches/JetBrains/IdeaIC2022.3"])
        left = {r["rel"]: r["reason"] for r in plan["left_alone"]}
        self.assertIn("uncommitted changes", left["Library/Caches/JetBrains/IdeaIC2023.1"])


if __name__ == "__main__":
    import unittest
    unittest.main()
