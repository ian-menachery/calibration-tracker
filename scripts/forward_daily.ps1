# Daily forward-test runner (Phase 4). Registered via Windows Task Scheduler.
#
# Runs forward-scan (log realizable spread-crossed paper fills for open Polymarket
# markets in an eligible category's entry window) then forward-settle (settle resolved
# positions: P&L, realized-minus-predicted edge, void disputed). Both are idempotent:
# forward-scan INSERT OR IGNOREs per (market, horizon); forward-settle acts only on
# open->resolved. Polymarket CLOB reads are public, so no secrets are needed.
#
# EXPECTATION, not a bug: given the Phase 3 cost verdict (gross edge dies under a
# 1-2c half-spread) and the narrow eligible slices (sports@24h, crypto@7d), most runs
# log 0 entries. This job exists for honest live confirmation/closure, not yield.

$ErrorActionPreference = "Continue"
$repo = "C:\users\ianme\projects\calibration-tracker"
$py = Join-Path $repo ".venv\Scripts\python.exe"
$db = Join-Path $repo "data\markets.db"
$rule = Join-Path $repo "reports\frozen_rule_v1.json"
$env:PYTHONPATH = Join-Path $repo "src"

$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("forward_{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

$stamp = (Get-Date -Format "o")
# Pipe native output through Out-File utf8 so the log is single-encoding (PS 5.1's
# *>> redirection would write UTF-16 and garble against the utf8 headers).
"=== $stamp  forward-scan ===" | Out-File -Append -Encoding utf8 $log
& $py -m calibration.cli forward-scan --db $db --rule $rule 2>&1 | Out-File -Append -Encoding utf8 $log
"=== $stamp  forward-settle ===" | Out-File -Append -Encoding utf8 $log
& $py -m calibration.cli forward-settle --db $db 2>&1 | Out-File -Append -Encoding utf8 $log
"=== $stamp  done ===" | Out-File -Append -Encoding utf8 $log
