#!/usr/bin/env bash
# tools/sync_openmw_nif.sh
# Re-mirror native/third_party/openmw_nif/ from a sibling clone of OpenMW.
# Run this only when intentionally updating to a new OpenMW commit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OPENMW_DIR="${OPENMW_DIR:-$PROJECT_ROOT/../openmw}"
MIRROR_DIR="$PROJECT_ROOT/native/third_party/openmw_nif"

if [[ ! -d "$OPENMW_DIR/.git" ]]; then
  echo "error: $OPENMW_DIR is not a git checkout" >&2
  exit 1
fi

if ! git -C "$OPENMW_DIR" diff --quiet || ! git -C "$OPENMW_DIR" diff --cached --quiet; then
  echo "error: $OPENMW_DIR has uncommitted changes" >&2
  exit 1
fi

UPSTREAM_SHA="$(git -C "$OPENMW_DIR" rev-parse HEAD)"
SRC="$OPENMW_DIR/components/nif/"

mkdir -p "$MIRROR_DIR"

# Mirror only .cpp/.hpp/.h files. Preserve patches/ and our metadata.
rsync -av --delete \
  --include='*.cpp' --include='*.hpp' --include='*.h' \
  --exclude='*' \
  "$SRC" "$MIRROR_DIR/"

# Copy upstream LICENSE if present at OpenMW root.
if [[ -f "$OPENMW_DIR/LICENSE" ]]; then
  cp "$OPENMW_DIR/LICENSE" "$MIRROR_DIR/LICENSE"
fi

echo "$UPSTREAM_SHA" > "$MIRROR_DIR/UPSTREAM_VERSION"

# Re-apply local patches if any. cd into the project root so `git apply
# --directory=...` resolves the path consistently regardless of the CWD the
# script was invoked from.
cd "$PROJECT_ROOT"
if compgen -G "$MIRROR_DIR/patches/*.patch" > /dev/null; then
  for p in "$MIRROR_DIR"/patches/*.patch; do
    echo "Applying $p"
    if ! git apply --directory="native/third_party/openmw_nif" "$p"; then
      echo "error: patch $p failed to apply." >&2
      echo "error: mirror may be inconsistent. Inspect the patch or remove it from patches/." >&2
      exit 1
    fi
  done
fi

echo "Mirrored OpenMW NIF parser at $UPSTREAM_SHA into $MIRROR_DIR"
echo "Commit with: git add $MIRROR_DIR && git commit -m 'chore: sync openmw_nif from $UPSTREAM_SHA'"
