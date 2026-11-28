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

    def test_a_units_own_path_rule_beats_the_containers(self):
        dd = "Library/Developer/Xcode/DerivedData"
        self.write(f"{dd}/Keep-abc/Build/x.o", 100 * 1024)
        self.write(f"{dd}/Old-def/Build/x.o", 100 * 1024)
        self.run_tool("policy", "init")
        import os
        path = self.tool.policy_path(self.home)
        with open(path) as f:
            policy = json.load(f)
        policy.setdefault("paths", {})[f"{dd}/Keep-abc"] = {"action": "keep"}
        with open(path, "w") as f:
            json.dump(policy, f)
        self.run_tool("scan")
        plan = self.plan()
        self.assertEqual([r["rel"] for r in plan["remove"]], [f"{dd}/Old-def"])
        left = {r["rel"]: r["reason"] for r in plan["left_alone"]}
        self.assertEqual(left[f"{dd}/Keep-abc"], "your policy says keep")
        self.assertEqual([r["rel"] for r in self.plan("--path", dd)["remove"]],
                         [f"{dd}/Old-def"])  # keep holds for an explicit --path too
        self.run_tool("clean")
        self.run_tool("clean", "--apply")
        self.assertTrue(os.path.isdir(os.path.join(self.home, dd, "Keep-abc")))

    def test_the_printed_apply_command_names_what_was_asked(self):
        self.write(".gradle/wrapper/dists/gradle-8.5-bin/abc/gradle-8.5/lib/a.jar")
        self.run_tool("scan")
        rc, out = self.run_tool("clean", "--path", ".gradle/wrapper/dists")
        self.assertIn("clean --path .gradle/wrapper/dists --apply", out)
        rc, out = self.run_tool("clean", "--path", ".gradle/wrapper/dists", "--apply")
        self.assertEqual(rc, 0, out)
        self.assertFalse(self.exists(".gradle/wrapper/dists/gradle-8.5-bin"))

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

    def test_a_private_folder_keeps_only_its_own_unit(self):
        dd = "Library/Developer/Xcode/DerivedData"
        self.write(f"{dd}/Old-abc/Build/Products/app.o", 200 * 1024)
        self.write(f"{dd}/Mine-xyz/Build/Products/app.o", 100 * 1024)
        self.run_tool("policy", "init")
        self.run_tool("private", "add", f"~/{dd}/Mine-xyz/Build")
        self.run_tool("scan")
        plan = self.plan()
        self.assertEqual([r["rel"] for r in plan["remove"]], [f"{dd}/Old-abc"])
        left = {r["rel"]: r["reason"] for r in plan["left_alone"]}
        self.assertIn("private", left[f"{dd}/Mine-xyz"])

    def test_policy_set_takes_one_unit_of_a_container(self):
        dd = "Library/Developer/Xcode/DerivedData"
        self.write(f"{dd}/Old-abc/Build/Products/app.o", 200 * 1024)
        self.write(f"{dd}/Keep-def/Build/Products/app.o", 200 * 1024)
        self.run_tool("policy", "init")
        self.run_tool("scan")
        rc, out = self.run_tool("policy", "set", f"~/{dd}/Keep-def", "keep")
        self.assertEqual(rc, 0, out)
        plan = self.plan()
        self.assertEqual([r["rel"] for r in plan["remove"]], [f"{dd}/Old-abc"])
        rc, out = self.run_tool("policy", "set", f"~/{dd}/Keep-def/Build", "keep")
        self.assertNotEqual(rc, 0, out)  # deeper than a unit: not an item
        self.assertIn("not an item from the last scan", out)


class KotlinPinTest(HomeTestCase):
    """~/.konan: a Kotlin/Native version a project's version catalog names is kept."""

    def setUp(self):
        super().setUp()
        self.shift_clock(40)
        for v in ("1.9.0", "2.0.0"):
            self.write(f".konan/kotlin-native-prebuilt-macos-aarch64-{v}/bin/konanc")
        self.run_tool("policy", "init")
        self.run_tool("policy", "set", "konan", "clean", "--older-than-days", "30")

    def catalog(self, rel, text):
        path = self.write(rel, 0)
        with open(path, "w") as f:
            f.write(text)

    def plan(self):
        rc, out = self.run_tool("clean", "--json")
        self.assertEqual(rc, 0, out)
        data = json.loads(out)
        return ([r["rel"] for r in data["remove"]],
                {r["rel"]: r["reason"] for r in data["left_alone"]})

    def test_a_pinned_version_stays_and_says_why(self):
        self.catalog("Developer/app/gradle/libs.versions.toml",
                     '[versions]\nkotlin = "2.0.0"\n[plugins]\n'
                     'kmp = { id = "org.jetbrains.kotlin.multiplatform", version.ref = "kotlin" }\n')
        self.run_tool("scan")
        remove, left = self.plan()
        self.assertEqual(remove, [".konan/kotlin-native-prebuilt-macos-aarch64-1.9.0"])
        self.assertEqual(left[".konan/kotlin-native-prebuilt-macos-aarch64-2.0.0"],
                         "Kotlin 2.0.0 is named in ~/Developer/app/gradle/libs.versions.toml")
        rc, out = self.run_tool("clean")
        self.assertIn("Kotlin 2.0.0 is named in", out)
        rc, out = self.run_tool("clean", "--apply")
        self.assertTrue(self.exists(".konan/kotlin-native-prebuilt-macos-aarch64-2.0.0"))
        self.assertFalse(self.exists(".konan/kotlin-native-prebuilt-macos-aarch64-1.9.0"))

    def exists(self, rel):
        import os
        return os.path.lexists(os.path.join(self.home, rel))

    def test_catalogs_in_library_are_not_read(self):
        self.catalog("Library/Mobile Documents/app/gradle/libs.versions.toml",
                     '[versions]\nkotlin = "2.0.0"\n')
        self.run_tool("scan")
        remove, _left = self.plan()
        self.assertEqual(len(remove), 2)

    def test_a_scan_from_before_pins_or_an_incomplete_one_keeps_compilers(self):
        self.run_tool("scan")
        path = self.tool.state_dir(self.home) + "/latest.json"
        with open(path) as f:
            data = json.load(f)
        data["complete"] = False
        with open(path, "w") as f:
            json.dump(data, f)
        remove, left = self.plan()
        self.assertEqual(remove, [])
        self.assertIn("may have been missed",
                      left[".konan/kotlin-native-prebuilt-macos-aarch64-1.9.0"])
        del data["kotlin_pins"]
        with open(path, "w") as f:
            json.dump(data, f)
        remove, left = self.plan()
        self.assertEqual(remove, [])
        self.assertIn("scan again", left[".konan/kotlin-native-prebuilt-macos-aarch64-1.9.0"])

    def test_private_folders_hide_their_catalogs(self):
        self.catalog("Work/app/gradle/libs.versions.toml", '[versions]\nkotlin = "2.0.0"\n')
        self.run_tool("private", "add", "~/Work")
        self.run_tool("scan")
        with open(self.tool.state_dir(self.home) + "/latest.json") as f:
            self.assertEqual(json.load(f)["kotlin_pins"], [])

    def test_a_catalog_that_cannot_be_read_keeps_every_compiler(self):
        real = self.write("Developer/shared/libs.versions.toml", 0)
        import os
        os.makedirs(os.path.join(self.home, "Developer/app/gradle"))
        os.symlink(real, os.path.join(self.home, "Developer/app/gradle/libs.versions.toml"))
        self.run_tool("scan")
        remove, left = self.plan()
        self.assertEqual(remove, [])
        self.assertIn("could not read ~/Developer/app/gradle/libs.versions.toml",
                      left[".konan/kotlin-native-prebuilt-macos-aarch64-1.9.0"])

    def test_pins_are_read_again_at_apply(self):
        cat = "Developer/app/gradle/libs.versions.toml"
        self.catalog(cat, '[versions]\nkotlin = "2.0.0"\n')
        self.run_tool("scan")
        remove, _left = self.plan()
        self.assertEqual(remove, [".konan/kotlin-native-prebuilt-macos-aarch64-1.9.0"])
        self.run_tool("clean")
        self.catalog(cat, '[versions]\nkotlin = "1.9.0"\n')  # changed after the dry run
        rc, out = self.run_tool("clean", "--apply", "--json")
        self.assertEqual(json.loads(out)["removed"], [])
        self.assertTrue(self.exists(".konan/kotlin-native-prebuilt-macos-aarch64-1.9.0"))

    def test_private_catalog_folder_is_scrubbed(self):
        self.catalog("Developer/app/gradle/libs.versions.toml", '[versions]\nkotlin = "2.0.0"\n')
        self.run_tool("scan")
        self.run_tool("scan")  # previous.json has it too
        self.run_tool("private", "add", "~/Developer/app/gradle")
        for name in ("latest.json", "previous.json"):
            with open(self.tool.state_dir(self.home) + "/" + name) as f:
                data = json.load(f)
            self.assertEqual((data["kotlin_pins"], data["kotlin_catalogs"]), ([], []), name)

    def test_parser_takes_headers_with_comments_and_refuses_odd_ones(self):
        text = '[versions] # shared\nkotlin = "2.0.0" # pinned\n'
        self.assertEqual(self.tool.kotlin_versions(text), ["2.0.0"])
        self.assertIsNone(self.tool.kotlin_versions('["versions"]\nkotlin = "2.0.0"\n'))

    def test_a_catalog_folder_reached_through_a_link_is_not_read_again(self):
        import os
        cat = "Developer/app/gradle/libs.versions.toml"
        self.catalog(cat, '[versions]\nkotlin = "2.0.0"\n')
        self.run_tool("scan")
        remove, _left = self.plan()
        self.assertEqual(remove, [".konan/kotlin-native-prebuilt-macos-aarch64-1.9.0"])
        self.run_tool("clean")
        app = os.path.join(self.home, "Developer/app")
        os.rename(app, os.path.join(self.outside, "app"))
        os.symlink(os.path.join(self.outside, "app"), app)  # the folder now leaves home
        rc, out = self.run_tool("clean", "--apply", "--json")
        self.assertEqual(json.loads(out)["removed"], [])
        skipped = json.loads(out)["skipped"]
        self.assertIn("could not read ~/Developer/app/gradle/libs.versions.toml",
                      skipped[0]["reason"])
        self.assertTrue(self.exists(".konan/kotlin-native-prebuilt-macos-aarch64-1.9.0"))
        scan = self.tool.latest_scan(self.home)
        self.assertEqual(self.tool.read_catalogs_again(self.home, scan, ["Developer/app"],
                                                       60, 20), {"Developer/app": "private"})

    def test_parser_resolves_refs_whatever_the_table_order(self):
        text = ('[plugins]\nkmp = { id = "org.jetbrains.kotlin.multiplatform", '
                'version.ref = "kgp" }\n[versions]\nkgp = "2.1.20"\n')
        self.assertEqual(self.tool.kotlin_versions(text), ["2.1.20"])

    def test_parser(self):
        text = (
            '# comment\n[versions]\nkgp = { strictly = "1.9.24" }\ncoroutines = "1.8.1"\n'
            '[libraries]\n'
            'co = { module = "org.jetbrains.kotlinx:kotlinx-coroutines-core", version.ref = "coroutines" }\n'
            'kgp = { module = "org.jetbrains.kotlin:kotlin-gradle-plugin", version.ref = "kgp" }\n'
            'std = "org.jetbrains.kotlin:kotlin-stdlib:1.8.0"\n'
            '[plugins]\nkmp = { id = "org.jetbrains.kotlin.multiplatform", version = "2.1.0" }\n')
        self.assertEqual(self.tool.kotlin_versions(text), ["1.8.0", "1.9.24", "2.1.0"])


if __name__ == "__main__":
    import unittest
    unittest.main()
