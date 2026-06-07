#!/usr/bin/env bash
# Install Asteria Beta from GitHub Release bundle (macOS / Linux).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="${ASTERIA_VENV:-$HOME/.asteria/venv}"
STUDIO_ROOT="${ASTERIA_STUDIO_ROOT:-$HOME/.asteria/studio}"

WHEEL="$(find "$HERE/dist-packages" -name 'asteria_runtime-*.whl' | head -n 1)"
if [[ -z "$WHEEL" ]]; then
  echo "dist-packages/*.whl not found. Run from asteria-beta-* bundle root." >&2
  exit 1
fi
if [[ ! -f "$HERE/studio/server.mjs" ]]; then
  echo "studio/server.mjs not found in bundle." >&2
  exit 1
fi

python3 --version >/dev/null
if [[ ! -d "$VENV_PATH" ]]; then
  python3 -m venv "$VENV_PATH"
fi
"$VENV_PATH/bin/python" -m pip install --upgrade pip --quiet
"$VENV_PATH/bin/pip" install "$WHEEL" --quiet

VERSION="$(basename "$WHEEL" | sed -n 's/asteria_runtime-\([0-9.]*\)-.*/\1/p')"
if [[ -z "$VERSION" ]]; then VERSION="0.1.0"; fi
STUDIO_DEST="$STUDIO_ROOT/$VERSION"
mkdir -p "$STUDIO_DEST"
cp -R "$HERE/studio/." "$STUDIO_DEST/"
echo "$STUDIO_DEST" > "$STUDIO_ROOT/current"

cat <<EOF

Asteria Beta installed.
  venv:    $VENV_PATH
  studio:  $STUDIO_DEST

Add to PATH: $VENV_PATH/bin
Then:
  asteria init --root ~/asteria-workspace
  asteria studio --root ~/asteria-workspace

Read docs/Beta用户入门.md and docs/Beta试跑清单.md in this folder.
EOF
