#!/bin/sh
# Sets the tool up from its checkout in ~/.local/share/<name>, or removes it again.
#   install:    ~/.local/share/disk-tool/install.sh
#   uninstall:  ~/.local/share/disk-tool/install.sh --uninstall
# Safe to run again. Prints everything it does. Needs nothing but macOS and python3.
set -eu

NAME=disk-tool
DEST="$HOME/.local/share/$NAME"
SKILL_LINK="$HOME/.claude/skills/$NAME"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/$NAME"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/$NAME"

HERE=$(cd "$(dirname "$0")" && pwd -P)
DEST_REAL=$(cd "$DEST" 2>/dev/null && pwd -P || echo "$DEST")

if [ "$HERE" != "$DEST_REAL" ]; then
  echo "This copy is in $HERE, but it must live in $DEST."
  echo "Clone it there first:  git clone <repository link> $DEST"
  echo "then run:              $DEST/install.sh${1:+ $1}"
  exit 1
fi

if [ "${1:-}" = "--uninstall" ]; then
  if [ -L "$SKILL_LINK" ]; then
    rm "$SKILL_LINK"
    echo "removed the skill link $SKILL_LINK"
  elif [ -e "$SKILL_LINK" ]; then
    echo "left $SKILL_LINK alone: it is not a link this script made"
  fi
  for dir in "$CONFIG" "$STATE"; do
    if [ -d "$dir" ]; then
      rm -rf "$dir"
      echo "removed $dir"
    fi
  done
  rm -rf "$DEST"
  echo "removed $DEST"
  echo "Done. Anything clean moved to the Trash is still in the Trash."
  exit 0
fi

if [ -n "${1:-}" ]; then
  echo "usage: $0 [--uninstall]" >&2
  exit 2
fi

[ "$(uname -s)" = Darwin ] || echo "note: made for macOS; on $(uname -s) the catalog fits less well"

if ! command -v python3 >/dev/null 2>&1 ||
   ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
  echo "needs python3 3.9 or newer. On macOS: xcode-select --install" >&2
  exit 1
fi

chmod +x "$DEST/bin/$NAME"
"$DEST/bin/$NAME" --version >/dev/null
echo "checked $DEST/bin/$NAME runs ($(python3 --version 2>&1))"

mkdir -p "$(dirname "$SKILL_LINK")"
TARGET="$DEST/skills/$NAME"
if [ -L "$SKILL_LINK" ] && [ "$(readlink "$SKILL_LINK")" = "$TARGET" ]; then
  echo "skill already linked: $SKILL_LINK"
elif [ -L "$SKILL_LINK" ]; then
  ln -sfn "$TARGET" "$SKILL_LINK"
  echo "relinked the skill: $SKILL_LINK -> $TARGET"
elif [ -e "$SKILL_LINK" ]; then
  echo "$SKILL_LINK exists and is not a link; left it alone. Move it away and run again." >&2
  exit 1
else
  ln -s "$TARGET" "$SKILL_LINK"
  echo "linked the skill: $SKILL_LINK -> $TARGET"
fi

echo
echo "Installed. Nothing runs in the background. Next: ask Claude Code \"what's on my disk?\""
echo "(a new Claude Code session picks up the skill; or run $DEST/bin/$NAME explain)"
