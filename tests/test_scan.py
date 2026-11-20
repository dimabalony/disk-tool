import json
import os
import unittest

from helpers import TOOL, HomeTestCase, load_tool

KB = 1024


class CatalogTest(unittest.TestCase):
    def test_table_is_consistent(self):
        tool = load_tool()
        ids = [e.id for e in tool.CATALOG] + [p.entry.id for p in tool.PROJECT_FOLDERS]
        self.assertEqual(len(ids), len(set(ids)), "catalog ids must be unique")
        self.assertNotIn("unknown", ids)
        for e in tool.ENTRIES.values():
            self.assertIn(e.kind, tool.KINDS, e.id)
            self.assertIn(e.returns, tool.RETURNS, e.id)
            self.assertTrue(e.description.endswith("."), e.id)
            if e.auto_clean:
                self.assertEqual((e.kind, e.returns), ("cache", "auto"), e.id)
                self.assertFalse(e.protected, e.id)
        for e in tool.CATALOG:
            first = e.pattern.split("/")[0]
            self.assertFalse(any(c in first for c in "*?["), e.id)

    def test_no_network_code(self):
        with open(TOOL) as f:
            source = f.read()
        for word in ("import socket", "urllib", "http.client", "import ssl", "requests"):
            self.assertNotIn(word, source)


class GroupingTest(HomeTestCase):
    def build(self):
        self.write("Library/Caches/com.example.app/blob")
        self.write("Library/Caches/Homebrew/downloads/pkg.tar.gz")
        self.write("Library/Developer/Xcode/DerivedData/App-abc/Build/x")
        self.write("Library/Developer/Xcode/iOS DeviceSupport/17.0 (21A)/Symbols/y")
        self.write("Library/Containers/com.example.sandboxed/Data/Library/Caches/z")
        self.write("Library/Containers/com.example.sandboxed/Data/Documents/doc")
        self.write("Library/Application Support/Example/data")
        self.write("Library/Application Support/MobileSync/Backup/0000/manifest")
        self.write("Documents/letter.txt")
        self.write("Documents/side-project/package.json", 10)
        self.write("Documents/side-project/node_modules/lib/index.js")
        self.write("Developer/app/package.json", 10)
        self.write("Developer/app/node_modules/left-pad/index.js")
        self.write("Developer/app/src/main.js")
        self.write("Developer/notaproject/node_modules/x.js")  # no package.json next to it
        self.write("Developer/rusty/Cargo.toml", 10)
        self.write("Developer/rusty/target/debug/bin")
        self.write("Developer/py/.venv/pyvenv.cfg", 10)
        self.write("Developer/py/.venv/lib/site.py")
        self.write(".nvm/versions/node/v20/lib/node_modules/npm/index.js")
        self.write(".npm/_cacache/content/a")
        self.write(".cache/uv/wheels/b")
        self.write(".cache/sometool/c")
        self.write(".Trash/old-installer.dmg")
        self.write("Applications/Thing.app/Contents/Resources/app/package.json", 10)
        self.write("Applications/Thing.app/Contents/Resources/app/node_modules/m.js")
        self.write("big-loose-file.iso")

    def test_kinds_and_most_specific_match(self):
        self.build()
        result, items = self.scan()
        self.assertTrue(result["complete"])
        expect = {
            "Library/Caches/com.example.app": ("library-caches", "cache"),
            "Library/Caches/Homebrew": ("homebrew-cache", "cache"),
            "Library/Developer/Xcode/DerivedData": ("xcode-derived-data", "cache"),
            "Library/Developer/Xcode/iOS DeviceSupport/17.0 (21A)": ("device-support", "temp"),
            "Library/Containers/com.example.sandboxed/Data/Library/Caches":
                ("app-container-cache", "cache"),
            "Library/Containers/com.example.sandboxed": ("app-container", "apps"),
            "Library/Application Support/Example": ("app-support", "apps"),
            "Library/Application Support/MobileSync/Backup": ("device-backups", "user"),
            "Documents": ("documents", "user"),
            "Documents/side-project/node_modules": ("node-modules", "dev"),
            "Developer/app/node_modules": ("node-modules", "dev"),
            "Developer/rusty/target": ("rust-target", "dev"),
            "Developer/py/.venv": ("python-venv", "dev"),
            ".nvm/versions": ("nvm-versions", "dev"),
            ".npm/_cacache": ("npm-cache", "cache"),
            ".cache/uv": ("uv-cache", "cache"),
            ".cache/sometool": ("xdg-cache", "cache"),
            ".Trash/old-installer.dmg": ("trash", "temp"),
            "Applications": ("user-apps", "apps"),
            "Developer": ("unknown", "unknown"),
            "big-loose-file.iso": ("unknown", "unknown"),
        }
        for rel, (item_id, kind) in expect.items():
            self.assertIn(rel, items, rel)
            self.assertEqual((items[rel]["id"], items[rel]["kind"]), (item_id, kind), rel)
        # Not project output: no marker, a global tool install, inside an app bundle.
        self.assertNotIn("Developer/notaproject/node_modules", items)
        self.assertFalse(any("lib/node_modules" in rel for rel in items))
        self.assertFalse(any("Thing.app" in rel for rel in items))
        # A nested item takes its bytes away from the item around it.
        container = items["Library/Containers/com.example.sandboxed"]["bytes"]
        cache = items["Library/Containers/com.example.sandboxed/Data/Library/Caches"]["bytes"]
        self.assertGreaterEqual(cache, 64 * KB)
        self.assertLess(container, 64 * KB + cache)
        # Unknown keeps what is left of ~/Developer after the project folders.
        inside = [c["name"] for c in items["Developer"]["biggest_inside"]]
        self.assertIn("notaproject", inside)
        self.assertEqual(sum(result["kinds"].values()), result["measured_bytes"])

    def test_text_report_names_every_kind(self):
        self.tool.LIST_MIN_BYTES = 0
        self.build()
        rc, out = self.run_tool("scan")
        self.assertEqual(rc, 0)
        for label in self.tool.KINDS.values():
            self.assertIn(label, out)
        self.assertIn("~/Developer/app/node_modules", out)
        self.assertIn("First scan", out)


class MeasuringTest(HomeTestCase):
    def test_hard_links_counted_once(self):
        self.write("Downloads/a/big.bin", 1024 * KB)
        os.makedirs(os.path.join(self.home, "Downloads/b"))
        os.link(os.path.join(self.home, "Downloads/a/big.bin"),
                os.path.join(self.home, "Downloads/b/same.bin"))
        os.link(os.path.join(self.home, "Downloads/a/big.bin"),
                os.path.join(self.home, "elsewhere.bin"))
        result, items = self.scan()
        self.assertGreaterEqual(result["measured_bytes"], 1024 * KB)
        self.assertLess(result["measured_bytes"], 1024 * KB + 200 * KB)

    def test_symlinks_are_not_followed(self):
        with open(os.path.join(self.outside, "huge.bin"), "wb") as f:
            f.write(b"\0" * (2048 * KB))
        os.symlink(self.outside, os.path.join(self.home, "link-out"))
        os.makedirs(os.path.join(self.home, "Library/Caches"))
        os.symlink(self.outside, os.path.join(self.home, "Library/Caches/linked"))
        result, items = self.scan()
        self.assertLess(result["measured_bytes"], 200 * KB)

    @unittest.skipIf(os.geteuid() == 0, "root reads everything")
    def test_refused_folder_is_not_measured_not_zero(self):
        self.write("Library/Application Support/Locked/secret")
        self.write("Library/Caches/com.example.half/inner/blob")
        self.write("Library/Caches/com.example.half/blob")
        locked = os.path.join(self.home, "Library/Application Support/Locked")
        inner = os.path.join(self.home, "Library/Caches/com.example.half/inner")
        os.chmod(locked, 0)
        os.chmod(inner, 0)
        self.tool.LIST_MIN_BYTES = 0
        result, items = self.scan()
        self.assertNotIn("Library/Application Support/Locked", items)
        rows = {r["rel"]: r for r in result["not_measured"]}
        self.assertEqual(rows["Library/Application Support/Locked"]["reason"], "permission")
        self.assertEqual(rows["Library/Application Support/Locked"]["id"], "app-support")
        self.assertTrue(items["Library/Caches/com.example.half"]["partial"])
        rc, out = self.run_tool("scan")
        self.assertIn("Not measured", out)
        self.assertIn("~/Library/Application Support/Locked: no permission", out)
        self.assertIn("at least", out)

    def test_time_limit_reports_incomplete(self):
        for i in range(50):
            self.write(f"Developer/p{i}/file", 1024)
        result, _ = self.scan(time_limit=0)
        self.assertFalse(result["complete"])
        self.assertIn("time limit", result["incomplete_reason"])
        rc, out = self.run_tool("scan", "--time-limit", "0", "--json")
        data = json.loads(out)
        self.assertFalse(data["complete"])
        rc, out = self.run_tool("scan")
        self.assertIn("stopped early", out)  # no comparison against an incomplete scan


class SnapshotTest(HomeTestCase):
    def test_second_scan_shows_what_changed(self):
        self.tool.CHANGE_MIN_BYTES = 100 * KB
        self.write("Library/Caches/com.example.grows/a", 64 * KB)
        self.write("Library/Caches/com.example.goes/a", 300 * KB)
        self.write("Library/Caches/com.example.same/a", 300 * KB)
        rc, out = self.run_tool("scan", "--json")
        first = json.loads(out)
        self.assertTrue(first["first_scan"])
        self.write("Library/Caches/com.example.grows/b", 300 * KB)
        self.write("Library/Caches/com.example.new/a", 300 * KB)
        os.unlink(os.path.join(self.home, "Library/Caches/com.example.goes/a"))
        rc, out = self.run_tool("scan", "--json")
        ch = json.loads(out)["changes"]
        self.assertTrue(ch["available"])
        self.assertEqual([r["rel"] for r in ch["new"]], ["Library/Caches/com.example.new"])
        self.assertEqual([r["rel"] for r in ch["grown"]], ["Library/Caches/com.example.grows"])
        self.assertEqual([r["rel"] for r in ch["shrunk"]], ["Library/Caches/com.example.goes"])
        state = os.path.join(self.home, ".local/state/disk-tool")
        self.assertTrue(os.path.exists(os.path.join(state, "latest.json")))
        self.assertTrue(os.path.exists(os.path.join(state, "previous.json")))
        rc, out = self.run_tool("scan")
        self.assertIn("Nothing changed by more than", out)

    def test_state_follows_xdg(self):
        os.environ["XDG_STATE_HOME"] = os.path.join(self.outside, "state")
        self.run_tool("scan")
        self.assertTrue(os.path.exists(os.path.join(self.outside, "state/disk-tool/latest.json")))

    def test_explain_says_never_then_the_date(self):
        rc, out = self.run_tool("explain")
        self.assertEqual(rc, 0)
        self.assertIn("never opens or reads your files", out)
        self.assertTrue(out.strip().endswith("Last scan: never"))
        self.run_tool("scan")
        rc, out = self.run_tool("explain")
        self.assertIn("(complete)", out.strip().splitlines()[-1])


if __name__ == "__main__":
    unittest.main()
