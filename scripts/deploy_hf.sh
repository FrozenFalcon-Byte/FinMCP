#!/usr/bin/env bash
# Sync the backend into a Hugging Face Space and push.
#
#   scripts/deploy_hf.sh <hf-user>/<space-name>
#
# Keeps the GitHub repo's own README untouched: the Space gets deploy/hf/README.md
# (which carries the Spaces YAML front-matter) as its README.md.
#
# Auth: `pip install -U "huggingface_hub[cli]" && hf auth login`, or export HF_TOKEN.
set -euo pipefail

SPACE="${1:-${HF_SPACE:-}}"
[ -n "$SPACE" ] || { echo "usage: scripts/deploy_hf.sh <hf-user>/<space-name>" >&2; exit 2; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/.hf-space"
REMOTE="https://huggingface.co/spaces/$SPACE"
[ -n "${HF_TOKEN:-}" ] && REMOTE="https://user:$HF_TOKEN@huggingface.co/spaces/$SPACE"

if [ -d "$WORK/.git" ]; then
  git -C "$WORK" remote set-url origin "$REMOTE"
  git -C "$WORK" fetch --depth 1 origin && git -C "$WORK" reset --hard origin/main
else
  rm -rf "$WORK"
  git clone --depth 1 "$REMOTE" "$WORK"
fi

# Replace the tracked payload wholesale so deletions propagate.
( cd "$WORK" && git rm -rq --ignore-unmatch . )
for path in finmcp api agent supabase Dockerfile .dockerignore pyproject.toml; do
  cp -R "$ROOT/$path" "$WORK/"
done
cp "$ROOT/deploy/hf/README.md" "$WORK/README.md"
find "$WORK" -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$WORK" -name '*.egg-info' -prune -exec rm -rf {} + 2>/dev/null || true

git -C "$WORK" add -A
if git -C "$WORK" diff --cached --quiet; then
  echo "Space is already up to date."
  exit 0
fi
git -C "$WORK" commit -qm "Deploy backend $(git -C "$ROOT" rev-parse --short HEAD)"
git -C "$WORK" push -q origin HEAD:main
echo "Pushed to $REMOTE — build logs: https://huggingface.co/spaces/$SPACE?logs=build"
