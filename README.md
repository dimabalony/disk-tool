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

   It keeps the result, so the next scan can say what is new or has grown. Something the
   last scan skipped or measured only partly is shown apart, as *measured now, skipped last
   time*, and is not counted as new or grown.
2. **Policy.** One small file, `~/.config/disk-tool/policy.json`, says per kind, per item
   or per path: *keep*, *ask*, or *clean when unused for N days*. The defaults clean only caches that
   rebuild themselves, after 30 days unused. Claude writes it only after you agree.
3. **Clean.** First a dry run: the exact list and how much it frees. Only after your yes to
   that list does it remove them, moving them to the Trash where it can.

   What *unused for N days* means:
   - Some caches are cleaned part by part: Xcode DerivedData (per project), `~/.konan`
     (per Kotlin/Native version and dependency), JetBrains caches (per IDE version),
     Swift Package Manager (per package) and Gradle versions. Each part goes when nothing
     in it changed for N days; the rest stays. A Kotlin/Native version that a project's
     `gradle/libs.versions.toml` names is kept, and so is every version while a catalog
     cannot be read.
   - Build output and dependencies (`node_modules`, `.venv`, `build` and the like) go
     only when their project is idle too: no commit and no change to the project's own
     files for N days. A `git status` is not use. `--apply` looks at the project again
     and leaves the output if it was used since, or if it cannot tell.
   - A git worktree made with `git worktree add` is *ask* until you name it
     (`policy set git-worktree clean`, 60 days unless you give `--older-than-days`).
     Then it is offered only when it is not locked, nothing in it is uncommitted, staged
     or untracked, it holds no ignored files beyond build output (a `.env` or a key file
     keeps it, inside build output too), no file is marked assume-unchanged or
     skip-worktree, its branch has a remote-tracking upstream with every commit (as far
     as this Mac knows: git does not ask the server), and no commit or file changed for
     N days. Its repository must be inside your home
     folder. `--apply` checks all of this again right before it runs `git worktree
     remove`, which removes it instead of moving it to the Trash; the branch stays.
   - `clean --path <item>` is your own pick: it skips the *unused for N days* wait and
     works on an *ask* item, so a worktree needs no `git-worktree` rule then. A *keep*
     rule still holds, and so do every git check above.

Folders macOS keeps private (Mail, Messages, some app data) show as *not measured*, never as
empty. macOS may ask whether your terminal may open some of them; answer or ignore it. A
folder macOS holds for more than 20 seconds is skipped, and a whole scan stops after 10
minutes with what it has and names what it did not reach, so it never hangs.

Outside your home folder it only adds up sizes, read-only, of /Applications, /Library,
/Users/Shared, /private/var, /opt and /usr/local, names other accounts on the Mac without
looking inside them, and counts local Time Machine snapshots. Nothing outside your home
folder is ever offered for cleaning. To measure those folders, give your terminal
app Full Disk Access in System Settings › Privacy & Security.

## Never surprised by a full disk

`watch` is made to run on a schedule you add yourself, for example daily with `crontab -e`:

```text
0 10 * * * ~/.local/share/disk-tool/bin/disk-tool watch >/dev/null 2>&1
```

Each run scans, compares with the last scan and adds one line to
`~/.local/state/disk-tool/changes.jsonl`: free space then and now, and the 20 biggest
items that are new, grew, shrank or are gone. It alerts when free space is below 40 GB,
dropped by more than 5 GB since the last scan, or one item grew by more than 3 GB
(`--min-free-gb`, `--max-drop-gb`, `--max-item-growth-gb` change these). An alert prints
the free space and the biggest causes, shows a macOS notification (`--no-notify` turns it
off) and exits with code 3; otherwise it prints one line and exits with 0.
`watch --log [N]` prints the last N runs in plain words. Private folders appear there as
their path and total only.

Anything new that your policy says *ask* for is *undecided*. `undecided` lists those items
biggest first, with the date each was first seen and how much it grew since
(`--since 30d` keeps only what appeared lately). Decide one with
`policy set ~/path keep` (or `clean --older-than-days N` where the tool may clean it):
the decision is saved under `paths` in the policy file and the item leaves the list. An
item you keep still shows in a watch alert when it grows past the limit. The alert's
last line says how many items are undecided.

## Private folders

If a folder holds work whose contents must not show up anywhere, such as an employer's
checkout or client files, mark it private (Claude asks on the first run):

```sh
~/.local/share/disk-tool/bin/disk-tool private add ~/Developer/Acme
```

The report then shows that folder as one line, its path and total size. Nothing inside it
is listed, matched, saved with the scan, shown while scanning, or ever cleaned, and
marking it also removes what earlier saved scans recorded inside it. `private list` shows
them and `private remove` undoes one. They live in `~/.config/disk-tool/private.json`.

## What it never does

- Open or read your files. It looks at sizes and dates only, except a project's
  `gradle/libs.versions.toml` (for the Kotlin version), a git worktree's `.git` file
  and the `gitdir` file its repository keeps for it, and what `git` itself reads when
  `clean` checks a git project.
- Use the network or send anything anywhere. No telemetry.
- Remove your own files (*user*) or anything it does not recognise (*unknown*).
- Look inside another account's folder, or remove anything outside your home folder.
- Follow a link out of your home folder, or touch a git project with uncommitted or
  unpushed work.
- Run by itself. If you want a daily check, Claude gives you the line to add; it never
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
$T watch            # for a schedule: scan, log what changed, alert when space runs low
$T watch --log      # what changed on the disk, and when
$T undecided        # what nothing decided yet, biggest first (--since 30d: only new)
$T policy set ~/Movies/old keep   # decide one item; it leaves the undecided list
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
