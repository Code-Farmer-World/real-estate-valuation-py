#!/usr/bin/env bash
#
# 一次跑完所有防護，印一份摘要。錄影片或交接前跑這一支就夠。
#
#   ./scripts/verify-all.sh              後端全部 + 前端全部
#   ./scripts/verify-all.sh --backend    只跑後端
#
# 任何一步失敗就中止並回非零。每一步都印出實際數字，不只印「通過」，
# 因為「指令沒報錯」不等於「做對了」。

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

FRONTEND="$(cd "$HERE/../real-estate-valuation" 2>/dev/null && pwd || true)"
TEMPLATES="$(cd "$HERE/../正式題目" 2>/dev/null && pwd || true)"
DOCS="$(cd "$HERE/../docs/official/real-estate-valuation" 2>/dev/null && pwd || true)"

ONLY_BACKEND=0
[[ "${1:-}" == "--backend" ]] && ONLY_BACKEND=1

PY=".venv/bin/python"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

step() { printf '\n\033[1m── %s\033[0m\n' "$1"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$1"; exit 1; }
ok() { printf '\033[32m✓\033[0m %s\n' "$1"; }

[[ -x "$PY" ]] || fail "找不到 $PY，先建 venv 並安裝相依"
[[ -n "$DOCS" ]] || fail "找不到 ../docs/official/real-estate-valuation，parser 與 pdfform 的測試會掛"
[[ -n "$TEMPLATES" ]] || fail "找不到 ../正式題目，產不出書表"

export VALUATION_DOC_DIR="$DOCS"
export VALUATION_TEMPLATE_DIR="$TEMPLATES"

step "1/6 後端測試"
TEST_OUT="$($PY -m pytest -q -p no:warnings 2>&1 | tail -3)"
echo "$TEST_OUT" | tail -1
echo "$TEST_OUT" | grep -qE "[0-9]+ passed" || fail "後端測試沒通過"
echo "$TEST_OUT" | grep -qE "failed|error" && fail "後端測試有失敗項"
ok "後端測試通過"

step "2/6 規則集對照官方基準表"
$PY -m pytest kernel/tests/test_ruleset_matches_official_pdf.py -q -p no:warnings 2>&1 | tail -1
ok "29 個細項的矩陣與門檻與評價基準明細表逐格一致"

step "3/6 產出三份書表"
$PY -m xlsxform.cli --templates "$TEMPLATES" --out "$OUT" | tail -14

step "4/6 回填完整性盤點"
AUDIT="$($PY -W ignore -m xlsxform.audit --templates "$TEMPLATES" --out "$OUT" 2>&1)"
echo "$AUDIT" | grep "小計：" | sed 's/^/   /'
$PY -m pytest xlsxform/tests/test_audit.py -q -p no:warnings 2>&1 | tail -1
ok "動過的格位與釘住的清單一致，沒有覆寫範本印好的標籤"

step "5/6 自我驗證報告"
$PY - "$OUT/verification-report.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
v = r.get("verification") or r
checks = v.get("checks") or []
passed = sum(1 for c in checks if c.get("passed"))
for c in checks:
    print("   %s %s" % ("✓" if c.get("passed") else "✗", c.get("name")))
print("   %d / %d 項通過" % (passed, len(checks)))
if passed != len(checks):
    raise SystemExit("自我驗證未全數通過")
PY
ok "自我驗證全數通過"

if [[ "$ONLY_BACKEND" == "1" ]]; then
  step "跳過前端（--backend）"
  printf '\n\033[32m全部通過\033[0m\n'
  exit 0
fi

step "6/6 前端"
[[ -n "$FRONTEND" ]] || fail "找不到 ../real-estate-valuation"
cd "$FRONTEND"
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
# shellcheck disable=SC1091
[[ -s "$NVM_DIR/nvm.sh" ]] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1 || true

echo "   node $(node -v)"
npm run type-check >/dev/null 2>&1 || fail "前端 type-check 失敗"
ok "type-check"
npx tsc --noEmit -p e2e/tsconfig.json >/dev/null 2>&1 || fail "e2e type-check 失敗"
ok "e2e type-check"
npx vitest run 2>&1 | grep -E "Tests +[0-9]+ passed" | sed 's/^/   /' || fail "vitest 失敗"
npm run build >/dev/null 2>&1 || fail "production build 失敗"
ok "production build"

printf '\n\033[32m全部通過\033[0m\n'
printf '沒跑到的：Playwright 端到端測試需要後端在 :8000 跑著，指令見前端 README\n'
