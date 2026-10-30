#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH_DIR="$ROOT_DIR/patches/nested_repos"
check_only=false
case "${1:-}" in
  --check) check_only=true ;;
  '') ;;
  *) echo 'Usage: apply_nested_repo_patches.sh [--check]' >&2; exit 2 ;;
esac

if [ ! -d "$PATCH_DIR" ]; then
  echo "No patch directory found: $PATCH_DIR"
  exit 0
fi

pending_patches=()
pending_repos=()
for patch in "$PATCH_DIR"/*.patch; do
  [ -f "$patch" ] || continue
  name="$(basename "$patch" .patch)"
  repo="${name//__//}"
  repo_path="$ROOT_DIR/$repo"

  if [ ! -e "$repo_path/.git" ]; then
    echo "ERROR: $repo: missing independent checkout; run git submodule update --init --recursive" >&2
    exit 1
  fi
  expected="$(git -C "$ROOT_DIR" ls-tree HEAD -- "$repo" | awk '$1 == "160000" {print $3}')"
  actual="$(git -C "$repo_path" rev-parse HEAD)"
  if [ -z "$expected" ] || [ "$actual" != "$expected" ]; then
    echo "ERROR: $repo: expected pinned commit $expected, found $actual" >&2
    exit 1
  fi
  if git -C "$repo_path" apply --reverse --check "$patch" >/dev/null 2>&1; then
    echo "already applied: $(basename "$patch")"
  elif git -C "$repo_path" apply --check "$patch" >/dev/null 2>&1; then
    pending_patches+=("$patch")
    pending_repos+=("$repo_path")
  else
    echo "ERROR: $repo: patch conflicts with checkout; preserve local changes and resolve explicitly" >&2
    exit 1
  fi
done

# Validate every checkout before making any changes.
for i in "${!pending_patches[@]}"; do
  if "$check_only"; then
    echo "ready to apply: $(basename "${pending_patches[$i]}")"
    continue
  fi
  echo "applying $(basename "${pending_patches[$i]}")"
  git -C "${pending_repos[$i]}" apply "${pending_patches[$i]}"
done
