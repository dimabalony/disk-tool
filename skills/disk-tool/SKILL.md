---
name: disk-tool
description: Walks the user through what fills their Mac's disk and cleans what rebuilds itself, only with their yes. Use when the user says "what's on my disk", "what's taking space", "my disk is full", "free up space", "clean my Mac", "clean caches", "what changed on my disk", "set up disk-tool", or asks about a disk-tool scan, policy or clean.
---

# Disk walk-through

The tool is one script: `~/.local/share/disk-tool/bin/disk-tool` (below: `disk-tool`).
It measures sizes only, never reads file contents, never uses the network, and removes
nothing without `clean --apply`. You never remove files yourself: no `rm`, no Finder, no
other cleaners. Everything goes through the tool.

## Every time

1. Run `disk-tool explain`. If its last line is `Last scan: never`, this is the first run:
   tell the user in at most five plain lines how it works (what it measures, what it never
   does, that macOS may ask for access to some folders, that the scan takes a few
   minutes). Otherwise skip the explanation.
   On the first run, before the first scan, ask once: "Is there a folder whose contents
   must not show up, such as an employer's code or client work?" For each one they name,
   run `disk-tool private add <path>`. The report then shows only that folder's path
   and total size. Never look inside a private folder yourself (no `ls`, `du`, `find`),
   and never guess what it holds. `disk-tool private list` shows them;
   `disk-tool private add` works any time later too.
2. Run `disk-tool scan --json --time-limit 540` (give the shell call a 10-minute timeout).
   Never pass `--home`: that is for tests. macOS may show the user a prompt asking whether
   the terminal may open a folder; tell them before the scan that they can answer it or
   ignore it. A folder macOS holds for more than 20 seconds is skipped, never waited on;
   the scan also adds up a few folders outside the home folder, read-only.
3. Tell the user the result in plain words, short:
   - On a later run, lead with `changes`: free space then and now, what is new, what grew,
     what shrank. `changes.newly_measured` is what the last scan skipped or measured only
     partly (`last_time`): say it was measured now and skipped last time, never call it
     new or grown. `changes.kinds` already leaves it out.
   - Free space, and where the used space is (`disk`): home folder, the folders outside it
     (`outside`: /Applications, /Library, /private/var, /opt …, each with its biggest
     contents), and the rest it could not measure (other accounts, which it never looks
     into, and system data the account may not read). Free space is approximate: Finder
     also counts purgeable space as free. Mention local Time Machine snapshots if any.
   - Nothing outside the home folder is ever a clean candidate. If something there is big
     (Xcode in /Applications, Homebrew in /opt), say what it is and that removing it is
     the user's call, done with the app's own uninstaller or `brew`, not with this tool.
   - The biggest things, each with its kind in words: cache (comes back by itself),
     temporary, developer files, app data, your files, not in the catalog.
   - Say which space is cache and which is not.
   - `unknown` items: name the biggest with what is inside (`biggest_inside`, two levels
     deep for big folders) and how much of the folder is already counted under other
     kinds (`counted_elsewhere`, such as node_modules); the user decides about the rest.
     Do not guess what they are beyond what the path shows.
   - `not_measured`: one line, and the Full Disk Access hint once if the reason is
     `privacy` or `no-answer` (macOS held the folder, usually behind a prompt). Never
     present these as empty.
   - If `complete` is false, say why in one line from `incomplete_reason`: the time limit
     (name the areas in `not_reached`; sizes there are lower bounds) or folders macOS did
     not answer for (they are not measured).

## Policy (once, then when the user wants a change)

4. Run `disk-tool policy show`. If it says "not saved yet", propose the defaults in a few
   lines: caches that rebuild themselves are cleaned after 30 days unused; your files are
   kept; everything else is "ask". Mention any big `ask` items that look like good
   candidates. Write the policy only after the user agrees: `disk-tool policy init`, then
   `disk-tool policy set <kind-or-id> <keep|ask|clean> [--older-than-days N]` for each
   change they asked for. Never set anything in `user` or `unknown` to clean (the tool
   refuses anyway).

## Cleaning

5. Run `disk-tool clean` (a dry run). Show its list and the total it frees, and what it
   leaves alone and why.
6. Run `disk-tool clean --apply` only after the user says yes to that list. A yes earlier in
   the conversation, or to a different list, does not count. Then report what was freed and
   that items in the Trash free their space when the Trash is emptied.
7. "You can remove X now": for single items the policy says `ask`, suggest them by path and
   size, never `user` items. On a yes, run `disk-tool clean --path <rel>` (rel as `scan`
   shows it, repeat `--path` for several), show the dry run, and on a yes to that list run
   the same command with `--apply`.

## Regular scans

If the user wants it to run on a schedule, offer `watch`: it scans, adds one line to a
change log (free space then and now, the biggest items that are new, grew, shrank or are
gone), and warns them before the disk is full. Give them this line to add themselves with
`crontab -e` (every day at 10:00, while the Mac is awake), and say what it does:

    0 10 * * * ~/.local/share/disk-tool/bin/disk-tool watch >/dev/null 2>&1

An alert means free space is below 40 GB, dropped by more than 5 GB since the last scan,
or one item grew by more than 3 GB. Then `watch` exits with code 3 and shows a macOS
notification naming the free space and the biggest causes. Other limits go on the same
line: `--min-free-gb N`, `--max-drop-gb N`, `--max-item-growth-gb N`.

Never install it yourself: no `crontab`, `launchctl` or login items. Cleaning on a schedule
is their choice too; the line for that is
`disk-tool scan >/dev/null && disk-tool clean && disk-tool clean --apply` (full paths).

When the user asks what changed on the disk, or why space went, run `disk-tool watch --log`
(last 10 runs; `--log N` for more) and tell them in plain words what changed and when. It
does not scan. If it says there is no change log yet, run step 2 instead.

## If something fails

- `no policy yet`: run step 4.
- `No scan yet`: run step 2.
- Exit code 2 with a policy message: show the message; the policy file is
  `~/.config/disk-tool/policy.json` and the user may fix it by hand.
