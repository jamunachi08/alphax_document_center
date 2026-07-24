#!/usr/bin/env bash
# Alpha-X Document Center — release helper
#
#   ./release.sh 1.4.1        bump, commit "Update v1.4.1", tag v1.4.1
#   ./release.sh 1.4.1 --push same, then push branch + tag
#
# Bumps __version__, commits every change with the version in the message
# (matching the convention used across the Neotec/IRSAA repos), and tags it.

set -euo pipefail

APP="alphax_document_center"
INIT="${APP}/__init__.py"
VERSION="${1:-}"
PUSH="${2:-}"

if [[ -z "$VERSION" ]]; then
  echo "Usage: ./release.sh <version> [--push]"
  echo "Current: $(grep -oP '(?<=__version__ = ")[^"]+' "$INIT")"
  exit 1
fi

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Version must look like 1.4.1"
  exit 1
fi

if [[ ! -f "$INIT" ]]; then
  echo "Run this from the repository root (cannot find $INIT)."
  exit 1
fi

CURRENT=$(grep -oP '(?<=__version__ = ")[^"]+' "$INIT")
echo "  $CURRENT  ->  $VERSION"

# 1. Bump the app version. Frappe reads this for the App Versions report.
sed -i "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" "$INIT"

# 2. Remind about the changelog rather than fabricating an entry.
if ! grep -q "## \[$VERSION\]" CHANGELOG.md 2>/dev/null; then
  echo "  ! CHANGELOG.md has no '## [$VERSION]' section yet."
  read -r -p "  Continue without it? [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || { git checkout -- "$INIT"; exit 1; }
fi

# 3. Commit everything under one versioned message.
git add -A
if git diff --cached --quiet; then
  echo "  Nothing to commit."
else
  git commit -m "Update v$VERSION"
fi

# 4. Tag (idempotent).
if git rev-parse "v$VERSION" >/dev/null 2>&1; then
  echo "  Tag v$VERSION already exists, leaving it alone."
else
  git tag -a "v$VERSION" -m "Release v$VERSION"
fi

# 5. Optional push.
if [[ "$PUSH" == "--push" ]]; then
  BRANCH=$(git rev-parse --abbrev-ref HEAD)
  git push origin "$BRANCH"
  git push origin "v$VERSION"
  echo "  Pushed $BRANCH and v$VERSION."
else
  echo "  Not pushed. Run: git push origin \$(git rev-parse --abbrev-ref HEAD) && git push origin v$VERSION"
fi

echo "  Done: v$VERSION"
