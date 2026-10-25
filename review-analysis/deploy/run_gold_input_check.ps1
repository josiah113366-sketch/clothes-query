<#
.SYNOPSIS
  Gold A 리뷰 점수 입력 검증 쿼리(gold_input_check.sql)를 Athena 에서 하나씩 실행하고 결과를 JSON 으로 저장한다.

.DESCRIPTION
  무엇을 하나
    1. gold_input_check.sql 을 "-- @q<이름>" 줄 기준으로 쿼리 여러 개로 나눈다. (첫 "-- @q" 줄 앞의 머리말 주석은 버린다)
    2. 모든 쿼리에서 {{run_id}} 를 -RunId 값으로 바꾼다.
    3. 실행 전에 안전 검사를 한다. 아래 중 하나라도 걸리면 Athena 를 한 번도 부르지 않고 멈춘다.
         - 쓰기 쿼리 키워드: INSERT / MERGE / DELETE / CREATE / ALTER / DROP / UNLOAD
           (UPDATE / TRUNCATE / VACUUM / OPTIMIZE / MSCK / GRANT 도 같이 막는다. 주석과 '...' 문자열 안은 검사에서 뺀다)
         - 치환 뒤에도 {{...}} 가 남아 있는 쿼리
         - 결과 폴더(private\)가 .gitignore 대상이 아닐 때 (후기 관련 결과를 실수로 올리지 않기 위함)
    4. SSM 파라미터에서 Athena 워크그룹을 읽는다. (기본 /clothes-query/dev/athena-review-score/config 의 workgroup. 리전 ap-northeast-1)
    5. 쿼리를 순서대로 실행하고 끝날 때까지 기다린다. 한 쿼리가 실패해도 이유를 남기고 다음 쿼리로 넘어간다.
    6. 쿼리마다 이름, 시작 시각(UTC), QueryExecutionId, 상태, 스캔 바이트, 결과 행을 화면에 출력하고,
       전부 private\gold_input_check_<UTC시각>.json 에 저장한다.

  언제 돌리나
    점수 채점 루프(s2c)가 끝나 점수가 더 바뀌지 않을 때 돌린다. 채점 도중에 돌리면 건수가 매번 달라진다.

  사용하는 AWS 권한(읽기 전용)
    ssm:GetParameter, athena:StartQueryExecution / GetQueryExecution / GetQueryResults, 워크그룹 결과 S3 쓰기(Athena 가 결과 파일을 만든다),
    Glue·S3 읽기. 쿼리 자체는 SELECT 뿐이다. 후기 원문(text)과 주문·상품 식별 열은 읽지 않으므로 결과에는 건수·날짜 범위만 있다.

  요구 사항
    AWS CLI v2 가 PATH 에 있고 자격 증명이 잡혀 있어야 한다(예: $env:AWS_PROFILE). Windows PowerShell 5.1 과 PowerShell 7 모두 동작한다.
    패키지 설치는 필요 없다.

.PARAMETER RunId
  완료된 Silver 실행 ID. 기본값 reviews-v2-20261024T155307Z. 영문·숫자·. _ - 만 허용한다.

.PARAMETER Only
  일부 쿼리만 실행한다. 예: -Only q3,q4b  (이름은 SQL 파일의 "-- @q" 뒤 단어)

.PARAMETER DryRun
  AWS 를 전혀 부르지 않는다. 쿼리 분리·치환·안전 검사·출력 폴더 검사까지만 하고 쿼리 목록을 보여 준다.
  (SSM 도 읽지 않으므로 -Workgroup 을 안 주면 워크그룹 이름은 "(SSM 에서 읽음)" 으로 표시된다)

.PARAMETER Workgroup
  워크그룹을 직접 지정한다. 주면 SSM 을 읽지 않는다.

.PARAMETER ConfigParameter
  Athena 설정이 들어 있는 SSM 파라미터 이름.

.PARAMETER Region
  AWS 리전. 기본 ap-northeast-1.

.PARAMETER SqlFile
  쿼리 파일. 기본은 이 스크립트 옆의 gold_input_check.sql.

.PARAMETER OutDir
  결과 폴더. 기본은 review-analysis\private (이 폴더는 .gitignore 대상이어야 한다).

.PARAMETER PollSec
  상태 확인 간격(초). 기본 3.

.PARAMETER TimeoutSec
  쿼리 하나의 최대 대기 시간(초). 기본 900. 넘으면 취소를 요청하고 TIMEOUT 으로 기록한다.

.EXAMPLE
  # 1) 먼저 AWS 없이 분리·검사만 확인
  .\run_gold_input_check.ps1 -DryRun

.EXAMPLE
  # 2) 채점 루프가 끝난 뒤 전체 실행(기본 RunId)
  .\run_gold_input_check.ps1

.EXAMPLE
  # 3) 다른 Silver 실행, 일부 쿼리만
  .\run_gold_input_check.ps1 -RunId reviews-v2-20261024T155307Z -Only q3,q4

.NOTES
  종료 코드: 0 = 전부 SUCCEEDED, 1 = 실패·취소·시간초과가 하나라도 있음, 2 = 실행 전 검사에서 멈춤(Athena 호출 없음).
#>
[CmdletBinding()]
param(
    [string]$RunId = 'reviews-v2-20261024T155307Z',
    [string[]]$Only,
    [switch]$DryRun,
    [string]$Workgroup,
    [string]$ConfigParameter = '/clothes-query/dev/athena-review-score/config',
    [string]$Region = 'ap-northeast-1',
    [string]$SqlFile = (Join-Path $PSScriptRoot 'gold_input_check.sql'),
    [string]$OutDir = (Join-Path (Split-Path $PSScriptRoot -Parent) 'private'),
    [int]$PollSec = 3,
    [int]$TimeoutSec = 900
)

Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'

function Stop-Check([string]$msg) {
    Write-Host "[중단] $msg" -ForegroundColor Red
    exit 2
}

# 쓰기·DDL 키워드. 주석과 문자열 리터럴을 지운 뒤 단어 경계로 찾는다.
$WriteWords = 'INSERT|MERGE|DELETE|CREATE|ALTER|DROP|UNLOAD|UPDATE|TRUNCATE|VACUUM|OPTIMIZE|MSCK|GRANT|REVOKE'

function Find-WriteKeyword([string]$sql) {
    $s = [regex]::Replace($sql, '(?m)--.*$', ' ')
    $s = [regex]::Replace($s, '(?s)/\*.*?\*/', ' ')
    $s = [regex]::Replace($s, "'(?:[^']|'')*'", "''")
    $m = [regex]::Match($s, "(?i)\b($WriteWords)\b")
    if ($m.Success) { return $m.Groups[1].Value.ToUpper() }
    return $null
}

# aws CLI 호출. 성공하면 표준출력 문자열, 실패하면 예외(메시지에 stderr 첫 줄들).
function Invoke-Aws([string[]]$CliArgs) {
    $prev = $ErrorActionPreference
    $prevIo = $env:PYTHONIOENCODING
    $env:PYTHONIOENCODING = 'utf-8'        # aws CLI 가 한글 결과(미분석, 속성 이름)를 cp949 가 아니라 UTF-8 로 내보내게 한다
    $ErrorActionPreference = 'Continue'   # 5.1 은 native stderr 를 오류 레코드로 바꾸므로 잠시 완화
    try {
        $all = & aws @CliArgs 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
        $env:PYTHONIOENCODING = $prevIo
    }
    $err = @($all | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] } | ForEach-Object { $_.ToString() })
    $out = @($all | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }) -join "`n"
    if ($code -ne 0) {
        $msg = ($err -join ' ').Trim()
        if ($msg.Length -gt 400) { $msg = $msg.Substring(0, 400) }
        throw "aws $($CliArgs[0..1] -join ' ') 실패(종료코드 $code): $msg"
    }
    return $out
}

# ---------- 1. 입력 검사 ----------
if ($RunId -notmatch '^[A-Za-z0-9._-]+$') { Stop-Check "RunId 형식이 이상합니다: 영문·숫자·. _ - 만 쓸 수 있습니다." }
if (-not (Test-Path -LiteralPath $SqlFile)) { Stop-Check "SQL 파일이 없습니다: $SqlFile" }

# ---------- 2. SQL 분리·치환 ----------
$text = [System.IO.File]::ReadAllText($SqlFile, (New-Object System.Text.UTF8Encoding($false)))
$queries = New-Object System.Collections.ArrayList
$cur = $null
foreach ($line in ($text -split "\r?\n")) {
    $m = [regex]::Match($line, '^\s*--\s*@(\S+)\s*(.*)$')
    if ($m.Success) {
        $cur = [pscustomobject]@{ Name = $m.Groups[1].Value; Title = $m.Groups[2].Value.Trim(); Lines = (New-Object System.Collections.ArrayList) }
        [void]$queries.Add($cur)
    } elseif ($null -ne $cur) {
        [void]$cur.Lines.Add($line)
    }
}
if ($queries.Count -eq 0) { Stop-Check "SQL 파일에서 '-- @q' 줄을 찾지 못했습니다." }

$items = @()
foreach ($q in $queries) {
    $sql = (($q.Lines -join "`n").Replace('{{run_id}}', $RunId)).Trim()
    $sql = $sql -replace ';\s*$', ''
    $items += [pscustomobject]@{ Name = $q.Name; Title = $q.Title; Sql = $sql }
}
if ($Only) {
    $unknown = @($Only | Where-Object { $items.Name -notcontains $_ })
    if ($unknown.Count) { Stop-Check "없는 쿼리 이름: $($unknown -join ', ')  (있는 것: $($items.Name -join ', '))" }
    $items = @($items | Where-Object { $Only -contains $_.Name })
}

# ---------- 3. 안전 검사 (Athena 호출 전에 전부) ----------
foreach ($it in $items) {
    $w = Find-WriteKeyword $it.Sql
    if ($w) { Stop-Check "$($it.Name): 쓰기/DDL 키워드($w)가 들어 있습니다. 읽기 전용 검증만 허용합니다." }
    if ($it.Sql -match '\{\{[^}]*\}\}') { Stop-Check "$($it.Name): 치환되지 않은 {{...}} 가 남아 있습니다." }
    $head = [regex]::Replace($it.Sql, '(?m)^\s*--.*$', '')   # 쿼리 앞의 이어지는 주석 줄(q4b 등)은 빼고 본다
    if ($head -notmatch '(?is)^\s*(WITH|SELECT)\b') { Stop-Check "$($it.Name): SELECT/WITH 로 시작하지 않습니다." }
}

# 결과 폴더가 .gitignore 대상인지: git check-ignore (읽기 전용) 로 확인하고, git 이 없으면 .gitignore 에 private/ 가 있는지 본다.
function Test-Ignored([string]$dir) {
    $probe = Join-Path $dir 'gold_input_check_probe.json'
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try { & git -C $dir check-ignore -q -- $probe 2>$null; $code = $LASTEXITCODE } finally { $ErrorActionPreference = $prev }
        if ($code -eq 0) { return $true }
        if ($code -eq 1) { return $false }
    }
    $gi = Join-Path (Split-Path $dir -Parent) '.gitignore'
    if (Test-Path -LiteralPath $gi) {
        return [bool](Select-String -LiteralPath $gi -Pattern ('^/?' + [regex]::Escape((Split-Path $dir -Leaf)) + '/?\s*$') -Quiet)
    }
    return $false
}
if (-not (Test-Path -LiteralPath $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }
if (-not (Test-Ignored $OutDir)) { Stop-Check "결과 폴더가 .gitignore 대상이 아닙니다: $OutDir  (확인 후 다시 실행하세요)" }

Write-Host "RunId      : $RunId"
Write-Host "쿼리       : $($items.Name -join ', ')  (총 $($items.Count)개)"
Write-Host "안전 검사  : 통과(쓰기 키워드 없음, 치환 완료, 결과 폴더 gitignore 확인)"

if ($DryRun) {
    Write-Host "`n[DryRun] AWS 를 호출하지 않습니다. 치환된 쿼리:" -ForegroundColor Yellow
    foreach ($it in $items) { Write-Host "`n=== $($it.Name) $($it.Title)"; Write-Host $it.Sql }
    exit 0
}

# ---------- 4. 워크그룹 ----------
$prevEnc = [Console]::OutputEncoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)   # aws 출력의 한글(예: 미분석)이 깨지지 않게. 끝나면 되돌린다.
# aws CLI(파이썬)가 Windows 코드페이지(cp949)로 출력하면 한글 값(예: 미분석, 속성명)이 JSON 에 깨져 저장되므로 UTF-8 을 강제한다.
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('gold_input_check_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
$failed = 0
$results = @()
try {
    if (-not $Workgroup) {
        $v = Invoke-Aws @('ssm', 'get-parameter', '--name', $ConfigParameter, '--region', $Region, '--query', 'Parameter.Value', '--output', 'text')
        $Workgroup = [string](($v | ConvertFrom-Json).workgroup)
        if (-not $Workgroup) { Stop-Check "SSM 설정($ConfigParameter)에 workgroup 이 없습니다." }
    }
    Write-Host "워크그룹   : $Workgroup ($Region)`n"

    # ---------- 5. 실행 ----------
    foreach ($it in $items) {
        $rec = [ordered]@{
            name = $it.Name; title = $it.Title
            started_utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
            query_execution_id = $null; state = $null; reason = $null
            data_scanned_bytes = $null; engine_ms = $null; columns = @(); rows = @()
        }
        Write-Host "[$($it.Name)] $($it.Title)  시작 $($rec.started_utc)"
        try {
            # 한글이 명령행에서 깨지지 않게 입력을 UTF-8 JSON 파일로 넘긴다.
            $inFile = Join-Path $tmp ($it.Name + '.json')
            $body = @{ QueryString = $it.Sql; WorkGroup = $Workgroup } | ConvertTo-Json -Compress
            # aws CLI 는 file:// 를 시스템 코드페이지(한국어 Windows 는 cp949)로 읽는다. 비ASCII 를 \uXXXX 로 바꿔 ASCII 파일로 만든다.
            $body = [regex]::Replace($body, '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
            [System.IO.File]::WriteAllText($inFile, $body, $utf8)
            $qid = (Invoke-Aws @('athena', 'start-query-execution', '--region', $Region, '--cli-input-json', ('file://' + $inFile), '--query', 'QueryExecutionId', '--output', 'text')).Trim()
            $rec.query_execution_id = $qid

            $deadline = (Get-Date).AddSeconds($TimeoutSec)
            do {
                Start-Sleep -Seconds $PollSec
                $ex = (Invoke-Aws @('athena', 'get-query-execution', '--region', $Region, '--query-execution-id', $qid, '--output', 'json')) | ConvertFrom-Json
                $state = $ex.QueryExecution.Status.State
            } while ($state -in @('QUEUED', 'RUNNING') -and (Get-Date) -lt $deadline)

            if ($state -in @('QUEUED', 'RUNNING')) {
                try { [void](Invoke-Aws @('athena', 'stop-query-execution', '--region', $Region, '--query-execution-id', $qid)) } catch { }
                $rec.state = 'TIMEOUT'; $rec.reason = "$TimeoutSec 초 안에 끝나지 않아 취소 요청"
            } else {
                $rec.state = $state
                $rec.reason = if ($ex.QueryExecution.Status.PSObject.Properties['StateChangeReason']) { [string]$ex.QueryExecution.Status.StateChangeReason } else { $null }
                $st = $ex.QueryExecution.Statistics
                if ($st) {
                    $rec.data_scanned_bytes = $st.DataScannedInBytes
                    $rec.engine_ms = $st.EngineExecutionTimeInMillis
                }
            }

            if ($rec.state -eq 'SUCCEEDED') {
                $res = (Invoke-Aws @('athena', 'get-query-results', '--region', $Region, '--query-execution-id', $qid, '--output', 'json')) | ConvertFrom-Json
                $all = @($res.ResultSet.Rows)
                $cols = @($all[0].Data | ForEach-Object { $_.VarCharValue })
                $rec.columns = $cols
                $rows = @()
                for ($i = 1; $i -lt $all.Count; $i++) {
                    $o = [ordered]@{}
                    for ($c = 0; $c -lt $cols.Count; $c++) {
                        $d = $all[$i].Data[$c]
                        $o[$cols[$c]] = if ($d -and $d.PSObject.Properties['VarCharValue']) { $d.VarCharValue } else { $null }
                    }
                    $rows += [pscustomobject]$o
                }
                $rec.rows = $rows
            }
        } catch {
            $rec.state = 'ERROR'; $rec.reason = $_.Exception.Message
        }

        if ($rec.state -ne 'SUCCEEDED') { $failed++ }
        $color = if ($rec.state -eq 'SUCCEEDED') { 'Green' } else { 'Red' }
        Write-Host ("  QueryExecutionId : {0}" -f $rec.query_execution_id)
        Write-Host ("  상태             : {0}" -f $rec.state) -ForegroundColor $color
        if ($rec.reason) { Write-Host ("  이유             : {0}" -f $rec.reason) -ForegroundColor $color }
        Write-Host ("  스캔 바이트      : {0}" -f $rec.data_scanned_bytes)
        if ($rec.rows.Count -gt 0) { Write-Host (($rec.rows | Format-Table -AutoSize | Out-String).TrimEnd()) }
        Write-Host ""
        $results += [pscustomobject]$rec
    }
} finally {
    [Console]::OutputEncoding = $prevEnc
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

# ---------- 6. 저장 ----------
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$outFile = Join-Path $OutDir "gold_input_check_$stamp.json"
$doc = [ordered]@{
    run_id = $RunId; region = $Region; workgroup = $Workgroup
    finished_utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    failed_queries = $failed; queries = $results
}
[System.IO.File]::WriteAllText($outFile, ($doc | ConvertTo-Json -Depth 8), $utf8)
Write-Host "저장: $outFile  (실패 $failed / $($results.Count))"
if ($failed -gt 0) { exit 1 }
exit 0
