#!/bin/bash
set -e
STYLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OS_DIR="${1:-$STYLE_DIR/dist/ReDeck-open-source}"

if [[ "$OS_DIR" == "$STYLE_DIR" ]]; then
  echo "Refusing to export over the source tree: $STYLE_DIR" >&2
  exit 2
fi
mkdir -p "$OS_DIR"

echo "=== Step 1: Clean garbage ==="
find "$OS_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
rm -rf "$OS_DIR/.venv" "$OS_DIR/redeck.egg-info"
rm -f "$OS_DIR/cases"
rm -rf "$OS_DIR/papers" "$OS_DIR/runs"
rm -f "$OS_DIR/CONTENT_DROPOUT_QUICK_REFERENCE.txt" "$OS_DIR/CONTENT_ISSUE_INVESTIGATION.md"
rm -f "$OS_DIR/app/modules/repairs/code_repair.py" "$OS_DIR/app/modules/redeck/repair_worker.py"
echo "Step 1 done"

echo "=== Step 2: Sync core code ==="
cp "$STYLE_DIR/app/modules/redeck/html_spatial_state.py" "$OS_DIR/app/modules/redeck/"
cp "$STYLE_DIR/app/modules/redeck/spatial_state.py" "$OS_DIR/app/modules/redeck/"
cp "$STYLE_DIR/app/modules/redeck/agent_repair.py" "$OS_DIR/app/modules/redeck/"
cp "$STYLE_DIR/app/modules/redeck/repair_utils.py" "$OS_DIR/app/modules/redeck/"
cp "$STYLE_DIR/scripts/redeck_repair.py" "$OS_DIR/scripts/"
cp "$STYLE_DIR/scripts/redeck_loop.py" "$OS_DIR/scripts/"
cp "$STYLE_DIR/app/prompts/codegen/slide_html_repair.system.md" "$OS_DIR/app/prompts/codegen/"
echo "Step 2 done"

echo "=== Step 6: Copy demo pairs ==="
mkdir -p "$OS_DIR/demo/repair_pairs"
cp -r "$STYLE_DIR/runs/demo_pairs/"* "$OS_DIR/demo/repair_pairs/"
echo "Step 6 done"

echo "=== Verification ==="
echo "Symlinks remaining:"
find "$OS_DIR" -type l 2>/dev/null | grep -v .git || echo "  (none)"
echo "pycache remaining:"
find "$OS_DIR" -name "__pycache__" 2>/dev/null || echo "  (none)"
echo "Disk usage:"
du -sh "$OS_DIR" --exclude=".git"
echo ""
echo "ALL STEPS DONE. Manual steps remaining: llm_client.py rewrite, sanitization scan, config updates."
