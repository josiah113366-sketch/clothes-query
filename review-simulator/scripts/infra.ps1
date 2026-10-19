<#
.SYNOPSIS
  리뷰 시뮬레이터 Terraform 스택(infra\stacks\ecs-review-simulator) init / plan / apply.
.DESCRIPTION
  비공개 파일 두 개가 스택 폴더에 있어야 한다 (둘 다 git 제외):
    deployment.backend.hcl  : bucket, region
    deployment.local.tfvars : state_bucket 등 (terraform.tfvars.example 참고)
  그리고 $env:TF_VAR_expected_account_id 를 미리 넣어 둔다.
  init  : backend 연결 (-Reconfigure 로 state key 를 바꾼 뒤 다시 연결)
  check : 계정 연결 없이 fmt·validate
  plan  : plan 을 파일(ecs-review-simulator.tfplan)로 저장
  apply : 저장한 plan 파일만 적용 (plan 을 눈으로 확인한 뒤)
.EXAMPLE
  .\scripts\infra.ps1 plan
.EXAMPLE
  .\scripts\infra.ps1 apply
#>
param(
    [Parameter(Mandatory, Position = 0)] [ValidateSet("init", "check", "plan", "apply")] [string] $Action,
    [switch] $Reconfigure
)
. "$PSScriptRoot\_common.ps1"
$stack = Join-Path $RepoRoot "infra\stacks\ecs-review-simulator"
$plan = "ecs-review-simulator.tfplan"
Push-Location $stack
# Windows PowerShell 5.1 은 -이름=값.확장자 형태 인자를 점(.)에서 둘로 쪼개 넘긴다
# (terraform 이 "Too many command line arguments" 로 멈춤). 그래서 -옵션=값 인자는 모두 따옴표로 감싼다.
try {
    # terraform 은 진행 메시지를 stderr 로도 쓴다. 5.1 에서 Stop 때문에 멈추지 않게 종료 코드로만 판단한다
    # (throw 는 이 설정과 상관없이 항상 멈춘다)
    $ErrorActionPreference = "Continue"
    switch ($Action) {
        "check" {
            terraform init "-backend=false" "-lockfile=readonly" "-input=false"
            if ($LASTEXITCODE -eq 0) { terraform fmt -check }
            if ($LASTEXITCODE -eq 0) { terraform validate }
        }
        "init" {
            if (-not (Test-Path "deployment.backend.hcl")) { throw "deployment.backend.hcl 이 없습니다 (bucket, region)" }
            $extra = @()
            if ($Reconfigure) { $extra += "-reconfigure" }
            terraform init "-backend-config=deployment.backend.hcl" "-lockfile=readonly" "-input=false" @extra
        }
        "plan" {
            if (-not $env:TF_VAR_expected_account_id) { throw "`$env:TF_VAR_expected_account_id 를 먼저 넣어 주세요" }
            if (-not (Test-Path "deployment.local.tfvars")) { throw "deployment.local.tfvars 가 없습니다 (terraform.tfvars.example 복사)" }
            terraform plan "-input=false" "-var-file=deployment.local.tfvars" "-out=$plan"
            if ($LASTEXITCODE -eq 0) { Write-Host "plan 저장: $plan. 내용을 확인한 뒤 .\scripts\infra.ps1 apply" -ForegroundColor Green }
        }
        "apply" {
            if (-not (Test-Path $plan)) { throw "$plan 이 없습니다. 먼저 .\scripts\infra.ps1 plan" }
            terraform apply $plan
            if ($LASTEXITCODE -eq 0) { Remove-Item $plan }
        }
    }
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $code
