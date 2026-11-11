#!/usr/bin/env bash
# Prepare a NON-shallow copy of the Loominous history for GitLab.
# Works on a COPY: never touches this repository's branches, working tree or remotes, never pushes,
# never contacts a network. Output: <outdir>/loominous-gitlab-import.bundle + commit-map.txt + report.txt
# Usage: scripts/prepare_gitlab_import.sh <outdir>
set -euo pipefail
OUT="${1:?usage: prepare_gitlab_import.sh <outdir>}"
SRC="$(git rev-parse --show-toplevel)"
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
cp -r "$SRC/.git" "$W/.git"; cd "$W"
git config core.bare false; git reset -q --hard HEAD
BR=$(git for-each-ref --format='%(refname:short)' refs/heads | grep -vx main)   # stale local 'main' is never exported
git branch -f gl-main origin/main            # production-equivalent main (local 'main' is behind origin/main)
if [ -f .git/shallow ]; then
  for c in $(cat .git/shallow); do git replace --graft "$c"; done   # boundary commits become roots
  rm .git/shallow
fi
: > "$OUT/commit-map.txt"
export FILTER_BRANCH_SQUELCH_WARNING=1
git filter-branch -f --commit-filter 'n=$(git commit-tree "$@"); echo "$GIT_COMMIT $n" >> "'"$OUT"'/commit-map.txt"; echo $n' -- gl-main $BR >/dev/null 2>&1
git replace -d $(git replace -l) >/dev/null 2>&1 || true
: > "$OUT/report.txt"; ok=1
for b in gl-main $BR; do
  old=$(git rev-parse "refs/original/refs/heads/$b"); new=$(git rev-parse "$b")
  same=NO; [ "$(git rev-parse "$old^{tree}")" = "$(git rev-parse "$new^{tree}")" ] && same=YES || ok=0
  echo "$b  old=${old:0:9} new=${new:0:9} tree_identical=$same commits=$(git rev-list --count "$new")" | tee -a "$OUT/report.txt"
done
[ "$ok" = 1 ] || { echo "TREE MISMATCH - do not use" >&2; exit 1; }
# only the rewritten branches go into the bundle (not refs/original, not remote-tracking refs)
git bundle create "$OUT/loominous-gitlab-import.bundle" gl-main $BR >/dev/null 2>&1
git bundle verify "$OUT/loominous-gitlab-import.bundle" >/dev/null 2>&1 && echo "bundle verified" | tee -a "$OUT/report.txt"
