"""Shared test helpers: load the one-file tool as a module and build temporary home folders."""

import contextlib
import importlib.machinery
import importlib.util
import io
import os
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "bin", "disk-tool")


def load_tool():
    loader = importlib.machinery.SourceFileLoader("disk_tool", TOOL)
    spec = importlib.util.spec_from_loader("disk_tool", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class HomeTestCase(unittest.TestCase):
    """Each test gets a fresh, empty home folder and a fresh copy of the tool."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._cleanup)
        self.home = os.path.realpath(os.path.join(self.tmp.name, "home"))
        os.makedirs(self.home)
        self.outside = os.path.realpath(os.path.join(self.tmp.name, "outside"))
        os.makedirs(self.outside)
        gitconfig = os.path.join(self.tmp.name, "gitconfig")
        open(gitconfig, "w").close()
        env = {"XDG_CONFIG_HOME": None, "XDG_STATE_HOME": None, "DISK_TOOL_HOME": None,
               "GIT_CONFIG_GLOBAL": gitconfig, "GIT_CONFIG_NOSYSTEM": "1"}
        for key, value in env.items():
            old = os.environ.get(key)
            self.addCleanup(self._restore_env, key, old)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tool = load_tool()

    @staticmethod
    def _restore_env(key, old):
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old

    def _cleanup(self):
        for root, dirs, _files in os.walk(self.tmp.name):
            for d in dirs:
                try:
                    os.chmod(os.path.join(root, d), 0o700)
                except OSError:
                    pass
        self.tmp.cleanup()

    # building the home folder
    def write(self, rel, size=64 * 1024):
        path = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"\0" * size)
        return path

    def mkdir(self, rel):
        path = os.path.join(self.home, rel)
        os.makedirs(path, exist_ok=True)
        return path

    def shift_clock(self, days):
        real = self.tool._now
        self.tool._now = lambda: real() + days * 86400

    def touch_future(self, rel, days):
        """Set mtimes under rel to `days` days from the real now (for a shifted clock)."""
        t = time.time() + days * 86400
        top = os.path.join(self.home, rel)
        for root, dirs, files in os.walk(top):
            for name in dirs + files:
                os.utime(os.path.join(root, name), (t, t))
        os.utime(top, (t, t))

    # running the tool in-process
    def run_tool(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = self.tool.main(list(argv) + ["--home", self.home])
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue() + err.getvalue()

    def scan(self, time_limit=60):
        result = self.tool.scan_home(self.home, time_limit)
        return result, {r["rel"]: r for r in result["items"]}


def git(cwd, *argv):
    cmd = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
           "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false"] + list(argv)
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


HAS_GIT = shutil.which("git") is not None and subprocess.run(
    ["git", "--version"], capture_output=True).returncode == 0
