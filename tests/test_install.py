import os
import shutil
import subprocess
import tempfile
import unittest

from helpers import ROOT


class InstallTest(unittest.TestCase):
    """install.sh against a temporary HOME only."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = os.path.realpath(tmp.name)
        self.dest = os.path.join(self.home, ".local/share/disk-tool")
        os.makedirs(self.dest)
        for name in ("bin", "skills"):
            shutil.copytree(os.path.join(ROOT, name), os.path.join(self.dest, name))
        shutil.copy(os.path.join(ROOT, "install.sh"), self.dest)
        self.env = {"HOME": self.home, "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        self.link = os.path.join(self.home, ".claude/skills/disk-tool")

    def run_sh(self, script, *args):
        return subprocess.run(["sh", script] + list(args), env=self.env, capture_output=True,
                              text=True)

    def test_install_is_safe_to_rerun_and_uninstall_removes_everything(self):
        script = os.path.join(self.dest, "install.sh")
        first = self.run_sh(script)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("linked the skill", first.stdout)
        self.assertEqual(os.readlink(self.link), os.path.join(self.dest, "skills/disk-tool"))
        self.assertTrue(os.path.exists(os.path.join(self.link, "SKILL.md")))

        again = self.run_sh(script)
        self.assertEqual(again.returncode, 0)
        self.assertIn("already linked", again.stdout)

        os.makedirs(os.path.join(self.home, ".config/disk-tool"))
        os.makedirs(os.path.join(self.home, ".local/state/disk-tool"))
        gone = self.run_sh(script, "--uninstall")
        self.assertEqual(gone.returncode, 0, gone.stderr)
        for path in (self.link, self.dest, os.path.join(self.home, ".config/disk-tool"),
                     os.path.join(self.home, ".local/state/disk-tool")):
            self.assertFalse(os.path.lexists(path), path)

    def test_refuses_to_run_from_another_folder(self):
        result = self.run_sh(os.path.join(ROOT, "install.sh"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("must live in", result.stdout)
        self.assertFalse(os.path.lexists(self.link))

    def test_leaves_a_foreign_skill_folder_alone(self):
        os.makedirs(self.link)
        result = self.run_sh(os.path.join(self.dest, "install.sh"))
        self.assertEqual(result.returncode, 1)
        self.assertTrue(os.path.isdir(self.link) and not os.path.islink(self.link))


class SkillTest(unittest.TestCase):
    def test_frontmatter(self):
        with open(os.path.join(ROOT, "skills/disk-tool/SKILL.md")) as f:
            text = f.read()
        self.assertTrue(text.startswith("---\nname: disk-tool\ndescription: "))
        self.assertIn("\n---\n", text[4:])


class CommandLineTest(unittest.TestCase):
    def test_runs_as_a_program_and_honours_the_home_variable(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.realpath(tmp)
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "DISK_TOOL_HOME": home,
                   "HOME": home}
            out = subprocess.run([os.path.join(ROOT, "bin/disk-tool"), "explain"], env=env,
                                 capture_output=True, text=True, check=True).stdout
            self.assertIn(os.path.join(home, ".config/disk-tool/policy.json"), out)
            self.assertIn("Last scan: never", out)


if __name__ == "__main__":
    unittest.main()
