param([switch]$Integration, [switch]$Eval)
$PY = 'B:\Applications\MiniConda\envs\docmind-service\python.exe'
Set-Location (Split-Path -Parent $PSScriptRoot)
$failed = $false
function Step($name, [scriptblock]$run) {
  Write-Host "== $name"
  & $run
  if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: $name"; $script:failed = $true }
}
Step 'ruff check'  { & $PY -m ruff check . }
Step 'ruff format' { & $PY -m ruff format --check . }
Step 'unit tests'  { & $PY -m pytest -q }
Step 'contract'    { & $PY scripts\export_openapi.py; git diff --exit-code openapi.json }
if ($Integration -or $Eval) { if (-not $env:DOCMIND_TEST_DATABASE_URL) { $env:DOCMIND_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:5433/docmind_test' } }
if ($Integration) { Step 'integration + model tests' { & $PY -m pytest -q -m "integration or model" } }
if ($Eval) {
  Step 'retrieval eval' { & $PY -m evaluation.run_retrieval --out evaluation\results\retrieval-local.json --label local }
  Step 'gates'          { & $PY -m evaluation.check_gates --results evaluation\results\retrieval-local.json --stage retrieval }
}
if ($failed) { exit 1 }
