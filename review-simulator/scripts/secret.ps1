<#
.SYNOPSIS
  Bedrock API 키를 Secrets Manager 에 넣거나 바꾼다. 키 값은 화면에 출력하지 않는다.
.PARAMETER FromEnv
  review-simulator\.env 의 AWS_BEARER_TOKEN_BEDROCK 값을 그대로 올린다. 없으면 키를 직접 입력(화면에 안 보임).
.PARAMETER Check
  값이 들어 있는지만 확인한다.
.EXAMPLE
  .\scripts\secret.ps1 -FromEnv
.EXAMPLE
  .\scripts\secret.ps1 -Check
#>
param(
    [switch] $FromEnv,
    [switch] $Check,
    [string] $Region
)
. "$PSScriptRoot\_common.ps1"
$a = @()
if ($FromEnv) { $a += "--from-env" }
if ($Check) { $a += "--check" }
Invoke-Deploy -Name "secret" -Arguments $a -Region $Region
