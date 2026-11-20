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
2. Run `disk-tool scan --json --time-limit 540` (give the shell call a 10-minute timeout).
   Never pass `--home`: that is for tests. macOS may show the user a prompt asking whether
   the terminal may open a folder; tell them before the scan that they can answer it or
   ignore it. A folder macOS holds for more than 20 seconds is skipped, never waited on.
3. Tell the user the result in plain words, short:
   - On a later run, lead with `changes`: free space then and now, what is new, what grew,
     what shrank.
   - Free space, then the biggest things, each with its kind in words: cache (comes back by
     itself), temporary, developer files, app data, your files, not in the catalog.
   - Say which space is cache and which is not.
   - `unknown` items: name the biggest with what is inside (`biggest_inside`); the user
     decides about them. Do not guess what they are beyond what the path shows.
   - `not_measured`: one line, and the Full Disk Access hint once if the reason is
     `privacy` or `no-answer` (macOS held the folder, usually behind a prompt). Never
     present these as empty.
   - If `complete` is false, say why in one line from `incomplete_reason`: the time limit
     (sizes are lower bounds) or folders macOS did not answer for (they are not measured).

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

If the user wants it to run on a schedule, give them this line to add themselves with
`crontab -e` (Sundays at 10:00), and say what it does:

    0 10 * * 0 ~/.local/share/disk-tool/bin/disk-tool scan >/dev/null 2>&1

Never install it yourself: no `crontab`, `launchctl` or login items. Cleaning on a schedule
is their choice too; the line for that is
`disk-tool scan >/dev/null && disk-tool clean && disk-tool clean --apply` (full paths).

## If something fails

- `no policy yet`: run step 4.
- `No scan yet`: run step 2.
- Exit code 2 with a policy message: show the message; the policy file is
  `~/.config/disk-tool/policy.json` and the user may fix it by hand.
