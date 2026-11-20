# disk-tool *(working name)*

See what fills your Mac's disk, in plain words, and clean what rebuilds itself, only with your yes.
A small scanner plus a guide for Claude Code: no dependencies, no network, nothing running in the background.

## Set it up

Paste this into Claude Code:

```text
Set up https://github.com/dimabalony/disk-tool for me and walk me through my disk.
```

Claude installs it, explains in a few lines how it works, scans, and tells you what it found:
how much space you have, what takes it, what is cache and what is not, what you could remove
now. Later, ask *"what's on my disk?"* and it leads with what changed since last time.

## How it works

1. **Scan.** It adds up the size of every folder in your home folder (sizes and dates only)
   and sorts the space into six kinds:

   | Kind | What it is | Example |
   |---|---|---|
   | cache | rebuilds by itself | `~/Library/Caches`, Xcode DerivedData, npm, pip, Homebrew downloads |
   | temp | leftovers | the Trash, logs, old simulators, old iOS debug files |
   | dev | comes back with a command | `node_modules`, `.venv`, build folders, Docker disks |
   | apps | app data and settings | `~/Library/Application Support` |
   | user | your own files | Documents, Desktop, Downloads, Pictures, Movies, Music |
   | unknown | anything else that is big | you judge these |

   It keeps the result, so the next scan can say what is new or has grown.
2. **Policy.** One small file, `~/.config/disk-tool/policy.json`, says per kind or per item:
   *keep*, *ask*, or *clean when unused for N days*. The defaults clean only caches that
   rebuild themselves, after 30 days unused. Claude writes it only after you agree.
3. **Clean.** First a dry run: the exact list and how much it frees. Only after your yes to
   that list does it remove them, moving them to the Trash where it can.

Folders macOS keeps private (Mail, Messages, some app data) show as *not measured*, never as
empty. macOS may ask whether your terminal may open some of them; answer or ignore it. A
folder macOS holds for more than 20 seconds is skipped, and a whole scan stops after 10
minutes with what it has and names what it did not reach, so it never hangs.

Outside your home folder it only adds up sizes, read-only, of /Applications, /Library,
/Users/Shared, /private/var, /opt and /usr/local, names other accounts on the Mac without
looking inside them, and counts local Time Machine snapshots. Nothing outside your home
folder is ever offered for cleaning. To measure those folders, give your terminal
app Full Disk Access in System Settings › Privacy & Security.

## What it never does

- Open or read your files. It looks at sizes and dates only.
- Use the network or send anything anywhere. No telemetry.
- Remove your own files (*user*) or anything it does not recognise (*unknown*).
- Look inside another account's folder, or remove anything outside your home folder.
- Follow a link out of your home folder, or touch a git project with uncommitted or
  unpushed work.
- Run by itself. If you want a weekly scan, Claude gives you the line to add; it never
  installs one.

## Without Claude

```sh
git clone https://github.com/dimabalony/disk-tool ~/.local/share/disk-tool
~/.local/share/disk-tool/install.sh
T=~/.local/share/disk-tool/bin/disk-tool
$T explain          # how it works
$T scan             # what is on the disk, and what changed
$T policy init      # write the safe default rules (policy show / policy set to change them)
$T clean            # dry run: what the rules would remove
$T clean --apply    # remove exactly that list
```

Requirements: macOS and `python3` 3.9 or newer (it comes with the Xcode Command Line Tools).

## Uninstall

```sh
~/.local/share/disk-tool/install.sh --uninstall
```

It removes the Claude skill link, your policy, the saved scans and the tool itself.

## Adding to the catalog

The catalog is a plain table at the top of `bin/disk-tool`: a path, its kind, one line
saying what it is, and whether it comes back by itself. Add a row, add a test in `tests/`,
and run `python3 -m unittest discover -s tests`.

## License

MIT
