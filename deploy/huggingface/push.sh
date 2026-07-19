#!/usr/bin/env bash
# Publish DocSentry to a Hugging Face Space.
#
#   deploy/huggingface/push.sh https://huggingface.co/spaces/<user>/<space>
#
# Run it from anywhere inside the repo, on the branch you want to deploy
# (v2-deploy-ready, or main once merged). It exports the *tracked* files only —
# so your gitignored .env never leaves your machine — swaps in the Hugging Face
# Space README (which sets the Docker SDK and port), and force-pushes to the
# Space. Re-run it any time to redeploy.
#
# You will be asked for Hugging Face credentials on push: username, and an
# access token *with write scope* as the password (https://huggingface.co/settings/tokens).
set -euo pipefail

SPACE_URL="${1:-}"
if [[ -z "$SPACE_URL" ]]; then
  echo "usage: $0 https://huggingface.co/spaces/<user>/<space>" >&2
  exit 2
fi

ROOT="$(git rev-parse --show-toplevel)"
REF="$(git rev-parse --abbrev-ref HEAD)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Exporting tracked files from '$REF' (gitignored files, incl. .env, are excluded)…"
git -C "$ROOT" archive HEAD | tar -x -C "$TMP"

# The file named README.md at the Space root must carry the HF front matter,
# or the Space defaults to the wrong port and shows no running app.
cp "$ROOT/deploy/huggingface/README.md" "$TMP/README.md"

cd "$TMP"
git init -q -b main
git add -A
git -c user.name="DocSentry Deploy" -c user.email="deploy@local" \
    commit -q -m "Deploy DocSentry"
git remote add space "$SPACE_URL"

echo "Pushing to $SPACE_URL …"
git push -f space main

echo
echo "Done. The Space will now build (a few minutes). Watch the Build logs."
echo "When it's up, open the Space URL for the dashboard, and /health for readiness."
