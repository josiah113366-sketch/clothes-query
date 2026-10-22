<#
.SYNOPSIS
  Bedrock API 키를 Secrets Manager 에 넣거나 바꾼다. 키 값은 화면에 출력하지 않는다.
.PARAMETER FromEnv
  review-simulator\.env 의 AWS_BEARER_TOKEN_BEDROCK 값을 그대로 올린다. 없으면 키를 직접 입력(화면에 안 보임).
.PARAMETER Check
  값이 들어 있는지만 확인한다.
.PARAMETER OrdersDb
  Bedrock 키 대신 RDS 접속 주소(ORDERS_DATABASE_URL) secret 을 다룬다 (2026-10-21). -FromEnv 면 .env 의 ORDERS_DATABASE_URL.
  postgresql://review_sim_ro:<비밀번호>@<RDS 주소>:5432/postgres?sslmode=require 형식. localhost 주소는 거절한다.
.EXAMPLE
  .\scripts\secret.ps1 -FromEnv
.EXAMPLE
  .\scripts\secret.ps1 -Check
.EXAMPLE
  .\scripts\secret.ps1 -OrdersDb
#>
param(
    [switch] $FromEnv,
    [switch] $Check,
    [switch] $OrdersDb,
    [string] $Region
)
. "$PSScriptRoot\_common.ps1"
$a = @()
if ($FromEnv) { $a += "--from-env" }
if ($Check) { $a += "--check" }
if ($OrdersDb) { $a += "--orders-db" }
Invoke-Deploy -Name "secret" -Arguments $a -Region $Region
