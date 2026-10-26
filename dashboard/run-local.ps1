param(
    [switch]$Setup,
    [string]$Profile = "",
    [ValidateRange(1024, 65535)][int]$Port = 8501
)

$ErrorActionPreference = 'Stop'
$dashboardRoot = $PSScriptRoot
$repoRoot = Split-Path -Parent $dashboardRoot
$python = Join-Path $dashboardRoot '.venv\Scripts\python.exe'

function Assert-Exit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." }
}

if ($Setup) {
    if (-not (Test-Path -LiteralPath $python)) {
        & python -m venv (Join-Path $dashboardRoot '.venv')
        Assert-Exit 'Create local venv'
    }
    & $python -m pip install -r (Join-Path $dashboardRoot 'requirements.txt')
    Assert-Exit 'Install dashboard requirements'
}
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Run .\dashboard\run-local.ps1 -Setup first.'
}
if ($Profile) { $env:AWS_PROFILE = $Profile }
$env:AWS_REGION = 'ap-northeast-1'
$env:AWS_DEFAULT_REGION = 'ap-northeast-1'
$env:GOLD_A_DATA_SOURCE = 'athena'
$env:GOLD_A_ATHENA_WORKGROUP = 'clothes-query-dev-dashboard'
$env:GOLD_A_DATABASE = 'gold_a'
$env:GOLD_A_OUTPUT_ROOT = 's3://clothes-query-datalake'
$env:DATA_SOURCE = 'auto'
$env:AUTH_MODE = 'dev' # Loopback-only local preview; never used by EKS deployment.
$env:AGENT_CODE_DIR = Join-Path $repoRoot 'agent'
$env:PYTHONIOENCODING = 'utf-8'

# Use boto3's existing credential chain. Never copy access keys into config files.
& $python -c 'import boto3; s=boto3.Session(); i=s.client("sts").get_caller_identity(); print("AWS identity:",i["Arn"]); w=s.client("athena").get_work_group(WorkGroup="clothes-query-dev-dashboard")["WorkGroup"]; print("Athena:",w["Name"],w["Configuration"]["ResultConfiguration"].get("OutputLocation"))'
Assert-Exit 'AWS authentication/workgroup read check'
Write-Host "Real Gold A / local-only URL: http://localhost:$Port"
Write-Host 'Choose Gold view mode in the sidebar. Stop with Ctrl+C.'
Push-Location $dashboardRoot
try {
    & $python -m streamlit run app.py --server.address=127.0.0.1 --server.port=$Port --server.headless=true --browser.gatherUsageStats=false
    Assert-Exit 'Streamlit'
} finally {
    Pop-Location
}
