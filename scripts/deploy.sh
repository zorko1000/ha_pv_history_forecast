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
#   --host     ssh config alias, hostname, or IP (default: homeassistant.local)
#   --dry-run  export and list files, but skip scp + restart
#
# Requires: a working `ssh -l root <host>` (see ~/.ssh/config), and the
# official "Terminal & SSH" add-on (or equivalent) on the target so
# `ha core restart` is available.
#
# HA's SSH add-on only accepts the `root` login (it's a sandboxed shell with
# /config, /addons, /ssl, /backup, /share mounted — not real host root), and
# only ever via public-key auth. The script always connects as -l root,
# regardless of what --host is set to or what your ~/.ssh/config says.
#
# On Windows, this prefers the native C:\Windows\System32\OpenSSH ssh/scp
# (checked at both /c/... and /mnt/c/... — Git Bash and WSL mount the C:
# drive differently) over whatever `ssh`/`scp` resolve to on PATH. Both Git
# Bash's bundled OpenSSH build and WSL's own Linux ssh can neither resolve
# mDNS `.local` names nor reach the Windows ssh-agent service the way the
# native client does — so a passphrase-protected key that works fine in a
# plain PowerShell `ssh` call can fail here with a bare "Permission denied
# (publickey)" and no passphrase prompt, or a hostname resolution error.
# Falls back to plain `ssh`/`scp` on PATH on real Linux/macOS, or Windows
# without the native client present.
#
# When using the native client, the exported files are staged under
# .deploy-tmp/ inside the repo (not the system temp dir): under WSL,
# `mktemp -d` lands inside the WSL VM's own filesystem, which the native
# scp.exe (a real Windows process) cannot see under any drive letter at all —
# no path translation fixes that. The repo itself is on a real Windows drive
# either way, so staging there and converting *that* path to C:/... form
# (only for the native client) works from both Git Bash and WSL.
#
# NOTE: this only checks that ref differs from what's on disk here — it does
# NOT know what's actually installed on the target. Before deploying a ref
# you haven't recently compared, sanity-check it yourself (or ask Claude):
#   git diff <currently-installed-version-or-tag> <ref> -- custom_components/
# to avoid silently shipping a regression.
set -euo pipefail

REF="HEAD"
HOST="homeassistant.local"
SSH_USER="root"
DRY_RUN=0

SSH_BIN="ssh"
SCP_BIN="scp"
for win_ssh in "/c/Windows/System32/OpenSSH/ssh.exe" "/mnt/c/Windows/System32/OpenSSH/ssh.exe"; do
  if [[ -x "$win_ssh" ]]; then
    SSH_BIN="$win_ssh"
    SCP_BIN="${win_ssh%ssh.exe}scp.exe"
    break
  fi
done
echo "-- Using ssh: $SSH_BIN"

# Convert a /mnt/c/... (WSL) or /c/... (Git Bash/MSYS) path to C:/... form.
# Passed through unchanged for any other shape (e.g. already a real Linux
# path, only ever relevant when SSH_BIN/SCP_BIN are the native .exe).
to_win_path() {
  local p="$1" drive rest
  case "$p" in
    /mnt/?/*)
      drive="${p:5:1}"
      rest="${p:6}"
      ;;
    /?/*)
      drive="${p:1:1}"
      rest="${p:2}"
      ;;
    *)
      printf '%s' "$p"
      return
      ;;
  esac
  printf '%s:%s' "${drive^^}" "$rest"
}

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
echo "== Deploying custom_components/pv_history_forecast @ $REF ($resolved_commit) to $SSH_USER@$HOST =="
git log -1 --format='    %h %s' "$REF"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "NOTE: working tree has uncommitted changes — those are NOT included (only committed state of $REF is deployed)."
fi

tmpdir="$repo_root/.deploy-tmp"
rm -rf "$tmpdir"
mkdir -p "$tmpdir"
trap 'rm -rf "$tmpdir"' EXIT

git archive "$REF" -- custom_components/pv_history_forecast | tar -x -C "$tmpdir"

echo "-- Files:"
find "$tmpdir" -type f | sed "s|^$tmpdir/||" | sort

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "-- Dry run: skipping upload and restart."
  exit 0
fi

local_src="$tmpdir/custom_components/pv_history_forecast"
if [[ "$SCP_BIN" != "scp" ]]; then
  local_src="$(to_win_path "$local_src")"
fi

echo "-- Uploading via $SCP_BIN to $SSH_USER@$HOST:/config/custom_components/ ..."
"$SCP_BIN" -r "$local_src" "$SSH_USER@$HOST:/config/custom_components/"

echo "-- Restarting Home Assistant Core..."
"$SSH_BIN" -l "$SSH_USER" "$HOST" "ha core restart"

echo "Done. Tail logs with: $SSH_BIN -l $SSH_USER $HOST 'ha core logs -f'"
