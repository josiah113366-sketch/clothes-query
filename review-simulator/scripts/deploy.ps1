<#
.SYNOPSIS
  이미지를 빌드해 ECR 에 올리고 새 태스크 정의 리비전을 등록한다 (Docker Desktop 필요).
.DESCRIPTION
  이미지 태그 = <버전>-<커밋 7자리> (커밋 안 한 변경이 있으면 -dirty<시각>). 실행 비율 등 다른 설정은 이전 리비전 그대로.
  스케줄이 켜져 있으면 스케줄도 새 리비전으로 바꾼다.
.PARAMETER DryRun
  무엇을 할지만 보여 준다.
.PARAMETER Tag
  이미 ECR 에 올린 태그로 다시 등록할 때 (-SkipBuild 와 같이).
.EXAMPLE
  .\scripts\deploy.ps1 -DryRun
.EXAMPLE
  .\scripts\deploy.ps1
.EXAMPLE
  .\scripts\deploy.ps1 -Tag 0.2.0-abc1234 -SkipBuild
#>
param(
    [switch] $DryRun,
    [string] $Tag,
    [switch] $SkipBuild,
    [string] $Region
)
. "$PSScriptRoot\_common.ps1"
$a = @()
if ($DryRun) { $a += "--dry-run" }
if ($Tag) { $a += @("--tag", $Tag) }
if ($SkipBuild) { $a += "--skip-build" }
Invoke-Deploy -Name "deploy" -Arguments $a -Region $Region
