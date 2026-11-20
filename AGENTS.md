# Instructions for AI agents

## If the user asked you to set this up

Requirements: macOS, `git`, and `python3` 3.9 or newer (it comes with the Xcode Command
Line Tools). Nothing else is installed.

1. Get the code into its fixed place:

   ```sh
   git clone https://github.com/dimabalony/disk-tool ~/.local/share/disk-tool
   ```

   If that folder already exists, update it instead:
   `git -C ~/.local/share/disk-tool pull --ff-only`.
2. Run the installer. It links the skill into `~/.claude/skills/disk-tool`, checks the
   tool runs, and prints each step. It is safe to run again.

   ```sh
   ~/.local/share/disk-tool/install.sh
   ```
3. Do the first walk-through now. Skills load when a session starts, so read
   `~/.local/share/disk-tool/skills/disk-tool/SKILL.md` and follow it from step 1.

Do not install anything that runs on a schedule; the skill says what to offer instead.

## If the user asked you to remove it

```sh
~/.local/share/disk-tool/install.sh --uninstall
```

It removes the skill link, the policy (`~/.config/disk-tool`), the saved scans
(`~/.local/state/disk-tool`) and the tool folder, and prints each. Items an earlier clean
moved to the Trash stay there.

## If you are changing the code

- `bin/disk-tool` is one Python file, standard library only, Python 3.9 compatible.
  The catalog (`CATALOG`, `PROJECT_FOLDERS`) is a plain table at the top.
- The name lives in `NAME` in `bin/disk-tool` and `NAME` in `install.sh`; the rest is text.
- Never run `scan` or `clean` against a real home folder while developing; pass
  `--home <temporary folder>`.
- Tests: `python3 -m unittest discover -s tests -v` (they build temporary home folders).
