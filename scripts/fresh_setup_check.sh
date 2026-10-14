#!/bin/sh
# Rebuilds the project from a clean clone of the last commit and runs every check that needs no model.
# Usage: sh scripts/fresh_setup_check.sh        (needs network for the package install and guidance capture)
set -eu
SRC=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d)
echo "Fresh clone in $TMP"
git clone -q "$SRC" "$TMP/disputes-agent"
cd "$TMP/disputes-agent"

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -q -r requirements.txt

echo "1. Regenerate the evaluation cases from the seed"
HASH=$(python realworld/scenarios.py generate | python -c "import json,sys; print(json.load(sys.stdin)['records_hash'][:12])")
[ "$HASH" = "6cdaadd3fd1d" ] || { echo "FAIL: records hash $HASH, expected 6cdaadd3fd1d"; exit 1; }
echo "   records hash $HASH matches the frozen dataset"

echo "2. Capture the published guidance (pages can change after the snapshot in docs/source-snapshot.json)"
python realworld/guidance.py fetch > guidance-capture.json

echo "3. Checks that need no model"
python scripts/verify_baseline.py > verify_baseline.out 2>&1 && echo "   PASS verify_baseline" || echo "   FAIL verify_baseline"
for check in check_read_tools check_write_tools check_boundaries_recovery check_guards_overblock check_mcp_parity; do
  if python -m case_agent.$check > "$check.out" 2>&1; then echo "   PASS $check"; else echo "   FAIL $check (see $TMP/disputes-agent/$check.out)"; fi
done
if python realworld/score_case.py --self-test > score.out 2>&1; then echo "   PASS scorer self-test"; else echo "   FAIL scorer self-test"; fi

echo "Done. Model runs need LM Studio serving qwen3.5-4b; see README."
