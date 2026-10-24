<#
.SYNOPSIS
  대시보드 이미지를 빌드해 ECR 에 올리고, digest 를 k8s/deployment.yaml 에 채운 뒤 EKS 에 배포한다.
.DESCRIPTION
  사람이 하던 "push -> digest 확인 -> deployment.yaml 의 image 수정 -> kubectl apply" 를 한 번에 한다.
  순서:
    1. 이미지 태그 정하기: <커밋 7자리> (커밋 안 한 변경이 있으면 <커밋>-dirty<시각>)
       ECR 저장소가 IMMUTABLE(태그 덮어쓰기 불가)이라 push 마다 새 태그가 필요하다.
    2. ECR 로그인 -> docker build(저장소 루트가 컨텍스트) -> docker push
    3. ECR 에서 그 태그의 digest(sha256:...)를 읽어 deployment.yaml 의 image 줄을 <저장소>@<digest> 로 바꾼다
       (바뀐 deployment.yaml 은 그대로 남는다. 커밋은 사람이 한다)
    4. 계정 Secret(dashboard-accounts)이 있는지 확인 (-UpdateAccounts 면 .local/accounts.json 으로 덮어쓴다)
    5. kubectl apply --dry-run=server 로 검사 -> apply -> rollout 완료까지 기다린다

  필요한 것: Docker Desktop(실행 중), AWS CLI 로그인(aws login 또는 aws configure sso), kubectl.
  kubectl 접속 파일: $env:KUBECONFIG 가 없고 저장소 루트에 .cache\eks-kubeconfig.private 가 있으면 그것을 쓴다.
  스크립트는 비밀번호·계정 파일 내용을 출력하지 않는다.
.PARAMETER DryRun
  무엇을 할지만 보여 준다. 빌드·push·파일 수정·apply 를 하지 않는다 (AWS·kubectl 조회는 한다).
.PARAMETER Tag
  이미 ECR 에 올린 태그로 다시 배포할 때. -SkipBuild 와 같이 쓴다.
.PARAMETER SkipBuild
  빌드·push 를 건너뛰고 -Tag 의 이미지 digest 만 읽어 배포한다 (이전 이미지로 되돌릴 때도 이것을 쓴다).
.PARAMETER NoApply
  빌드·push·deployment.yaml 수정까지만 하고 클러스터에는 적용하지 않는다.
.PARAMETER UpdateAccounts
  dashboard\.local\accounts.json 으로 계정 Secret 을 덮어쓴다. 이미지가 그대로여도 파드를 재시작해 새 계정을 읽게 한다.
  계정 추가는 먼저 python dashboard\make_test_accounts.py --add <이메일> 로 파일을 고친 뒤 이 옵션을 쓴다.
.PARAMETER AccountsOnly
  이미지는 건드리지 않고 계정 Secret 만 덮어쓰고 파드를 재시작한다 (계정 추가·비밀번호 변경용).
.PARAMETER Region
  AWS 리전. 기본 ap-northeast-1 (도쿄, EKS·ECR 위치).
.PARAMETER Repository
  ECR 저장소 이름. 기본 clothes-query-dev/dashboard (infra/stacks/dashboard 가 만든 저장소).
.EXAMPLE
  .\infra\platform\dashboard\deploy.ps1 -DryRun
.EXAMPLE
  .\infra\platform\dashboard\deploy.ps1
.EXAMPLE
  .\infra\platform\dashboard\deploy.ps1 -AccountsOnly
.EXAMPLE
  .\infra\platform\dashboard\deploy.ps1 -Tag 3eca2dd -SkipBuild
#>
param(
    [switch] $DryRun,
    [string] $Tag,
    [switch] $SkipBuild,
    [switch] $NoApply,
    [switch] $UpdateAccounts,
    [switch] $AccountsOnly,
    [string] $Region = "ap-northeast-1",
    [string] $Repository = "clothes-query-dev/dashboard"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# 고정값. 이름을 바꾸면 k8s/*.yaml 과 같이 바꾼다.
$Namespace = "dashboard"
$Deployment = "dashboard"
$SecretName = "dashboard-accounts"
# rollout 을 기다리는 최대 시간. 노드가 새로 떠야 하면(EKS Auto Mode) 몇 분 걸릴 수 있어 넉넉히 잡았다.
$RolloutTimeout = "300s"

# 이 파일은 infra\platform\dashboard\ 에 있다
$DashDeploy = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$K8sDir = Join-Path $DashDeploy "k8s"
$DeploymentYaml = Join-Path $K8sDir "deployment.yaml"
$AccountsFile = Join-Path $RepoRoot "dashboard\.local\accounts.json"

function Write-Step([string] $msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Write-Cmd([string] $msg) { Write-Host "> $msg" -ForegroundColor DarkGray }

# 외부 명령을 실행하고 실패(종료 코드 0 이 아님)면 멈춘다.
function Invoke-Checked {
    param([Parameter(Mandatory)] [string] $Exe, [string[]] $Arguments = @())
    Write-Cmd "$Exe $($Arguments -join ' ')"
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe 실패 (종료 코드 $LASTEXITCODE)" }
}

# 외부 명령의 표준 출력을 문자열로 받는다. 실패하면 $null (오류 메시지는 숨긴다. 있는지 확인하는 조회용).
function Get-Output {
    param([Parameter(Mandatory)] [string] $Exe, [string[]] $Arguments = @())
    # Windows PowerShell 5.1 은 Stop 상태에서 stderr 를 리다이렉트하면 예외로 바꾸므로 잠시 Continue 로 둔다
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $Exe @Arguments 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        return (($out | Out-String).Trim())
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Assert-Tool([string] $name, [string] $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { throw "$name 명령이 없습니다. $hint" }
}

# 계정 Secret 을 accounts.json 으로 덮어쓴다 (없으면 만든다).
function Update-AccountsSecret {
    if (-not (Test-Path $AccountsFile)) {
        throw "계정 파일이 없습니다: $AccountsFile`n  python dashboard\make_test_accounts.py --force 로 먼저 만든다 (README 3번)."
    }
    Write-Cmd "kubectl create secret generic $SecretName -n $Namespace --from-file=accounts.json=<accounts.json> --dry-run=client -o yaml | kubectl apply -f -"
    if ($DryRun) { return }
    $yaml = & kubectl create secret generic $SecretName -n $Namespace "--from-file=accounts.json=$AccountsFile" --dry-run=client -o yaml
    if ($LASTEXITCODE -ne 0) { throw "Secret YAML 만들기 실패" }
    # Secret 내용(해시)은 화면에 찍지 않는다
    $yaml | & kubectl apply -f - | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Secret 적용 실패" }
    Write-Host "  Secret $SecretName 갱신함"
}

# ---------------------------------------------------------------- 0. 준비
Assert-Tool "aws" "AWS CLI 를 설치하고 로그인한다."
Assert-Tool "kubectl" "kubectl 을 설치한다."
if ($Tag -and -not $SkipBuild) { throw "-Tag 는 -SkipBuild 와 같이 쓴다 (새로 빌드하면 태그는 스크립트가 정한다)." }
if ($AccountsOnly -and ($Tag -or $SkipBuild -or $NoApply)) { throw "-AccountsOnly 는 -Tag/-SkipBuild/-NoApply 와 같이 쓰지 않는다." }

if (-not $env:KUBECONFIG) {
    $kc = Join-Path $RepoRoot ".cache\eks-kubeconfig.private"
    if (Test-Path $kc) { $env:KUBECONFIG = $kc; Write-Host "KUBECONFIG = $kc (이 창에서만)" }
}

Write-Step "AWS 계정과 클러스터 확인"
$account = Get-Output aws @("sts", "get-caller-identity", "--query", "Account", "--output", "text")
if (-not $account) { throw "AWS 로그인이 안 돼 있습니다. aws login (또는 aws sso login) 후 다시 실행한다." }
$ctx = Get-Output kubectl @("config", "current-context")
if (-not $NoApply) {
    if (-not $ctx) { throw "kubectl 접속 설정이 없습니다. infra/EKS_ACCESS.md 대로 kubeconfig 를 준비한다." }
    Write-Host "  kubectl context: $ctx"
    # 접속이 되는지(허용 IP, 토큰) 미리 확인한다. 공인 IP 가 바뀌면 여기서 막힌다.
    if (-not (Get-Output kubectl @("get", "namespace", "kube-system", "-o", "name"))) {
        throw "클러스터에 접속하지 못했습니다. 공인 IP 가 EKS 허용 CIDR 에 있는지, AWS 로그인이 유효한지 확인한다."
    }
}

# ---------------------------------------------------------------- 계정만 바꾸는 경우
if ($AccountsOnly) {
    Write-Step "계정 Secret 갱신 후 파드 재시작"
    Update-AccountsSecret
    if (-not $DryRun) {
        Invoke-Checked kubectl @("rollout", "restart", "deployment/$Deployment", "-n", $Namespace)
        Invoke-Checked kubectl @("rollout", "status", "deployment/$Deployment", "-n", $Namespace, "--timeout=$RolloutTimeout")
    }
    Write-Host "`n완료. 재시작으로 접속 중인 세션과 로그인 실패 잠금이 초기화됐다." -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------- 1. 태그
$repoUri = Get-Output aws @("ecr", "describe-repositories", "--repository-names", $Repository, "--region", $Region,
                            "--query", "repositories[0].repositoryUri", "--output", "text")
if (-not $repoUri) { throw "ECR 저장소 $Repository 를 찾지 못했습니다 ($Region). infra/stacks/dashboard 를 apply 했는지 확인한다." }
$registry = $repoUri.Split("/")[0]

if (-not $Tag) {
    Assert-Tool "git" "Git 을 설치한다."
    $commit = Get-Output git @("-C", $RepoRoot, "rev-parse", "--short=7", "HEAD")
    if (-not $commit) { throw "git 커밋을 읽지 못했습니다." }
    # 이미지에 들어가는 파일만 본다 (dashboard/, agent 승인 코드, 이 배포 폴더의 Dockerfile)
    $dirty = Get-Output git @("-C", $RepoRoot, "status", "--porcelain", "--", "dashboard", "agent/approval/approval.py",
                              "agent/detect/athena_io.py", "infra/platform/dashboard/Dockerfile", "infra/platform/dashboard/Dockerfile.dockerignore")
    $Tag = $commit
    if ($dirty) {
        $Tag = "$commit-dirty$(Get-Date -Format 'yyyyMMddHHmmss')"
        Write-Host "  커밋 안 한 변경이 이미지에 들어갑니다. 태그: $Tag" -ForegroundColor Yellow
    }
}
$image = "${repoUri}:$Tag"
Write-Host "  이미지: $image"

$exists = Get-Output aws @("ecr", "describe-images", "--repository-name", $Repository, "--region", $Region,
                           "--image-ids", "imageTag=$Tag", "--query", "imageDetails[0].imageDigest", "--output", "text")

# ---------------------------------------------------------------- 2. 빌드·push
if ($SkipBuild) {
    if (-not $exists) { throw "ECR 에 태그 $Tag 가 없습니다. -SkipBuild 없이 빌드하거나 태그를 확인한다." }
    Write-Step "빌드 건너뜀 (ECR 의 $Tag 사용)"
} elseif ($exists) {
    # 같은 커밋을 다시 배포하는 경우. IMMUTABLE 이라 다시 push 할 수 없으니 있는 이미지를 쓴다.
    Write-Step "ECR 에 $Tag 가 이미 있어 빌드를 건너뜀"
} else {
    Assert-Tool "docker" "Docker Desktop 을 설치·실행한다."
    Write-Step "ECR 로그인, 빌드, push"
    if ($DryRun) {
        Write-Cmd "aws ecr get-login-password | docker login --username AWS --password-stdin $registry"
        Write-Cmd "docker build --platform linux/amd64 -f infra/platform/dashboard/Dockerfile -t $image ."
        Write-Cmd "docker push $image"
    } else {
        # 토큰을 변수에 담았다가 넘기면 400 Bad Request 로 거절되는 경우가 있어(2026-10-24 lemin PC),
        # 손으로 칠 때와 똑같이 aws 출력을 docker 로 바로 파이프한다.
        & aws ecr get-login-password --region $Region | & docker login --username AWS --password-stdin $registry
        if ($LASTEXITCODE -ne 0) {
            throw "docker login 실패. aws sts get-caller-identity 로 자격증명(만료·계정)을 먼저 확인한다. Docker Desktop 이 꺼져 있어도 실패한다."
        }
        Push-Location $RepoRoot
        try {
            # 노드가 x86(t3a)이라 linux/amd64 로 고정한다. ARM PC 에서 빌드해도 노드에서 돈다.
            Invoke-Checked docker @("build", "--platform", "linux/amd64", "-f", "infra/platform/dashboard/Dockerfile", "-t", $image, ".")
        } finally {
            Pop-Location
        }
        Invoke-Checked docker @("push", $image)
    }
}

# ---------------------------------------------------------------- 3. digest -> deployment.yaml
Write-Step "digest 를 deployment.yaml 에 반영"
$digest = Get-Output aws @("ecr", "describe-images", "--repository-name", $Repository, "--region", $Region,
                           "--image-ids", "imageTag=$Tag", "--query", "imageDetails[0].imageDigest", "--output", "text")
if (-not $digest -and -not $DryRun) { throw "push 한 이미지의 digest 를 ECR 에서 찾지 못했습니다 (태그 $Tag)." }
if (-not $digest) { $digest = "sha256:<push 후 정해짐>" }
$pinned = "$repoUri@$digest"

# 파일의 줄바꿈(CRLF)·인코딩(BOM 없는 UTF-8)을 그대로 두고 image 값만 바꾼다.
# "image:" 로 시작하는 줄(주석 제외)이 정확히 하나여야 한다. 컨테이너를 늘리면 이 부분을 고친다.
$text = [System.IO.File]::ReadAllText($DeploymentYaml)
$pattern = '(?m)^([ \t]+image:[ \t]*)\S+'
$found = [regex]::Matches($text, $pattern)
if ($found.Count -ne 1) { throw "deployment.yaml 에서 image 줄을 1개 찾아야 하는데 $($found.Count)개 찾았습니다." }
$old = ($found[0].Value -replace '^[ \t]+image:[ \t]*', '')
if ($old -eq $pinned) {
    Write-Host "  이미 같은 이미지입니다: $pinned"
} else {
    Write-Host "  이전: $old"
    Write-Host "  이후: $pinned"
    if (-not $DryRun) {
        $new = [regex]::Replace($text, $pattern, { param($m) $m.Groups[1].Value + $pinned }, 1)
        [System.IO.File]::WriteAllText($DeploymentYaml, $new, (New-Object System.Text.UTF8Encoding($false)))
    }
}

if ($NoApply) {
    Write-Host "`n클러스터 적용은 건너뜀 (-NoApply). deployment.yaml 만 바뀌었다." -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------- 4. namespace·계정 Secret
Write-Step "namespace, 계정 Secret 확인"
if ($DryRun) {
    Write-Cmd "kubectl apply -f k8s/namespace.yaml"
} else {
    Invoke-Checked kubectl @("apply", "-f", (Join-Path $K8sDir "namespace.yaml"))
}
$hasSecret = Get-Output kubectl @("get", "secret", $SecretName, "-n", $Namespace, "-o", "name")
if ($UpdateAccounts -or -not $hasSecret) {
    if (-not $hasSecret) { Write-Host "  Secret $SecretName 이 없어 accounts.json 으로 만든다" }
    Update-AccountsSecret
} else {
    Write-Host "  Secret $SecretName 있음 (계정을 바꾸려면 -UpdateAccounts)"
}

# ---------------------------------------------------------------- 5. 적용·rollout
Write-Step "Deployment, Service 적용"
$files = @("-f", $DeploymentYaml, "-f", (Join-Path $K8sDir "service.yaml"))
if ($DryRun) {
    # 실제 파일은 바꾸지 않았으므로 서버 검사도 바꾸기 전 파일 기준이다
    Invoke-Checked kubectl (@("apply", "--dry-run=server") + $files)
    Write-Host "`n-DryRun: 여기까지. 실제로는 apply 후 rollout 을 기다린다." -ForegroundColor Green
    exit 0
}
Invoke-Checked kubectl (@("apply", "--dry-run=server") + $files)
# 적용 전 파드 템플릿 버전. image 가 그대로면 apply 로 재시작되지 않는다.
$before = Get-Output kubectl @("get", "deployment", $Deployment, "-n", $Namespace, "-o", "jsonpath={.metadata.generation}")
Invoke-Checked kubectl (@("apply") + $files)
$after = Get-Output kubectl @("get", "deployment", $Deployment, "-n", $Namespace, "-o", "jsonpath={.metadata.generation}")
if ($UpdateAccounts -and $before -and ($before -eq $after)) {
    # 이미지가 같으면 파드가 그대로라 새 Secret 을 읽지 않는다. 직접 재시작한다.
    Invoke-Checked kubectl @("rollout", "restart", "deployment/$Deployment", "-n", $Namespace)
}
Invoke-Checked kubectl @("rollout", "status", "deployment/$Deployment", "-n", $Namespace, "--timeout=$RolloutTimeout")

Write-Host "`n완료: $pinned" -ForegroundColor Green
Write-Host "deployment.yaml 의 image 가 바뀌었으면 커밋해 둔다 (지금 클러스터에 올라간 버전 기록)."
if ($Tag -like "*-dirty*") { Write-Host "커밋 안 한 변경으로 만든 이미지다. 커밋 후 다시 배포하면 깨끗한 태그가 남는다." -ForegroundColor Yellow }
