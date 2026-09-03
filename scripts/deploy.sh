#!/usr/bin/env bash
# Deploy custom_components/pv_history_forecast to a live Home Assistant
# instance over scp, then restart HA Core.
#
# Bypasses HACS entirely — useful for testing a branch/PR before it's
# released. Deploys committed state only (via `git archive`); uncommitted
# working-tree changes are never included, so it's safe to run mid-edit.
#
# Usage:
#   scripts/deploy.sh [ref] [--host HOST] [--dry-run]
#
#   ref        git ref to deploy: branch, tag, or commit (default: HEAD)
#   --host     ssh config alias or user@host (default: homeassistant)
#   --dry-run  export and list files, but skip scp + restart
#
# Requires: a working `ssh <host>` (see ~/.ssh/config), and the official
# "Terminal & SSH" add-on (or equivalent) on the target so `ha core restart`
# is available.
#
# NOTE: this only checks that ref differs from what's on disk here — it does
# NOT know what's actually installed on the target. Before deploying a ref
# you haven't recently compared, sanity-check it yourself (or ask Claude):
#   git diff <currently-installed-version-or-tag> <ref> -- custom_components/
# to avoid silently shipping a regression.
set -euo pipefail

REF="HEAD"
HOST="homeassistant"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    *)
      REF="$1"
      shift
      ;;
  esac
done

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

resolved_commit="$(git rev-parse --short "$REF")"
echo "== Deploying custom_components/pv_history_forecast @ $REF ($resolved_commit) to $HOST =="
git log -1 --format='    %h %s' "$REF"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "NOTE: working tree has uncommitted changes — those are NOT included (only committed state of $REF is deployed)."
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

git archive "$REF" -- custom_components/pv_history_forecast | tar -x -C "$tmpdir"

echo "-- Files:"
find "$tmpdir" -type f | sed "s|^$tmpdir/||" | sort

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "-- Dry run: skipping upload and restart."
  exit 0
fi

echo "-- Uploading via scp to $HOST:/config/custom_components/ ..."
scp -r "$tmpdir/custom_components/pv_history_forecast" "$HOST:/config/custom_components/"

echo "-- Restarting Home Assistant Core..."
ssh "$HOST" "ha core restart"

echo "Done. Tail logs with: ssh $HOST 'ha core logs -f'"
