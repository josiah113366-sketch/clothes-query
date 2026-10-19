# scripts/*.ps1 공통 부분 (2026-10-19 sim/review-ecs). 직접 실행하지 않고 다른 스크립트가 불러 쓴다.
#
# - 어느 폴더에서 실행해도 review-simulator/ 폴더로 옮겨서 deploy/*.py 를 부른다 (.env, .local/ 상대 경로 때문)
# - 파이썬은 review-simulator\.venv 가 있으면 그것을, 없으면 PATH 의 python 을 쓴다.
#   다른 파이썬을 쓰려면 $env:RSIM_PYTHON = "C:\...\python.exe" 로 지정한다.
# - 한글 출력이 깨지지 않게 콘솔과 파이썬을 UTF-8 로 맞춘다.
# - AWS 로그인은 미리 해 둔다 (aws login 또는 aws configure sso). 스크립트는 로그인 정보를 다루지 않는다.

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# review-simulator\ 폴더 (이 파일은 review-simulator\scripts\ 에 있다)
$RsimRoot = Split-Path -Parent $PSScriptRoot
# clothes-query\ 저장소 루트 (Terraform 스택 위치 계산용)
$RepoRoot = Split-Path -Parent $RsimRoot

function Get-RsimPython {
    if ($env:RSIM_PYTHON) { return $env:RSIM_PYTHON }
    $venv = Join-Path $RsimRoot ".venv\Scripts\python.exe"
    if (Test-Path $venv) { return $venv }
    return "python"
}

# deploy\<Name>.py 를 인자와 함께 실행하고, 파이썬의 종료 코드를 그대로 돌려준다.
function Invoke-Deploy {
    param(
        [Parameter(Mandatory)] [string] $Name,
        [string[]] $Arguments = @(),
        [string] $Region
    )
    if ($Region) { $Arguments += @("--region", $Region) }
    $py = Get-RsimPython
    $script = Join-Path (Join-Path $RsimRoot "deploy") "$Name.py"
    Push-Location $RsimRoot
    try {
        Write-Host "> python deploy\$Name.py $($Arguments -join ' ')" -ForegroundColor DarkGray
        & $py $script @Arguments
        $code = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($code -ne 0) {
        Write-Host "실패 (종료 코드 $code)" -ForegroundColor Red
    }
    exit $code
}
