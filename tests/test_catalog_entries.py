"""Catalog rows for folders seen on real Macs: the right kind, and never removed when the
folder holds something the user would lose."""

from helpers import HomeTestCase


class CatalogEntriesTest(HomeTestCase):
    def build(self):
        self.write(".konan/kotlin-native-prebuilt-macos-aarch64-2.0.0/bin/konanc")
        self.write(".konan/dependencies/llvm-16-aarch64-macos/bin/clang")
        self.write(".gradle/.tmp/gradle-worker-classpath123.jar")
        self.write(".gradle/caches/modules-2/files-2.1/x.jar")
        self.write(".npm/_npx/0123abcd/node_modules/create-thing/index.js")
        self.write(".npm/_cacache/content-v2/sha512/aa")
        self.write("Library/Application Support/com.apple.wallpaper/aerials/videos/A.mov")
        self.write("Library/Application Support/com.apple.wallpaper/Store/Index.plist")
        self.write(".colima/_lima/colima/disk")
        self.tool.LIST_MIN_BYTES = 0

    def test_new_rows_match_with_the_right_kind(self):
        self.build()
        _, items = self.scan()
        want = {
            ".konan": ("konan", "dev", False),
            ".gradle/.tmp": ("gradle-tmp", "temp", False),
            ".gradle/caches": ("gradle-cache", "cache", False),
            ".npm/_npx": ("npx-cache", "cache", False),
            ".npm/_cacache": ("npm-cache", "cache", False),
            "Library/Application Support/com.apple.wallpaper/aerials":
                ("macos-aerials", "apps", True),
            "Library/Application Support/com.apple.wallpaper": ("app-support", "apps", False),
            ".colima": ("colima", "dev", True),
        }
        for rel, (id_, kind, protected) in want.items():
            self.assertIn(rel, items)
            r = items[rel]
            self.assertEqual((r["id"], r["kind"], r["protected"]), (id_, kind, protected), rel)
        # the aerial videos are not counted twice in the folder around them
        self.assertEqual(items["Library/Application Support/com.apple.wallpaper"]["bytes"],
                         64 * 1024)

    def test_descriptions_say_what_to_do_instead(self):
        e = self.tool.ENTRIES
        self.assertIn("System Settings > Wallpaper", e["macos-aerials"].description)
        self.assertIn("volumes", e["colima"].description)
        self.assertIn("Never delete this folder", e["colima"].description)
        self.assertIn("docker system prune", e["colima"].description)
        self.assertTrue(e["npx-cache"].auto_clean)
        self.assertFalse(e["konan"].auto_clean)
        self.assertFalse(e["gradle-tmp"].auto_clean)

    def test_aerials_and_colima_are_never_removed(self):
        self.build()
        self.run_tool("policy", "init")
        self.run_tool("scan")
        for rel in ("Library/Application Support/com.apple.wallpaper/aerials",
                    "Library/Application Support/com.apple.wallpaper", ".colima"):
            rc, out = self.run_tool("clean", "--path", rel)
            self.assertIn("Nothing to remove", out, rel)
            self.assertIn("never removed by this tool" if rel != (
                "Library/Application Support/com.apple.wallpaper") else
                "which your policy does not clean", out, rel)
        rc, out = self.run_tool("policy", "set", "macos-aerials", "clean")
        self.assertNotEqual(rc, 0)
        self.assertIn("never removed by this tool", out)
