<#
.SYNOPSIS
  내 AWS 계정에 ECS 배포·운영 권한이 있는지 읽기 전용으로 확인한다 (아무것도 만들지 않음).
.EXAMPLE
  .\scripts\check-access.ps1
#>
param([string] $Region)
. "$PSScriptRoot\_common.ps1"
Invoke-Deploy -Name "check_access" -Region $Region
