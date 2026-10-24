<#
.SYNOPSIS
  RDS 주문으로 실제 리뷰(Bedrock)를 지금 한 번 만든다 → S3 bronze_v2 날짜 파티션(덮어쓰기). (2026-10-21, v0.3.0)
.DESCRIPTION
  1) RDS 접속 주소 secret 확인 (비어 있으면 .\scripts\secret.ps1 -OrdersDb 먼저)
  2) 주문 입력이 rds 가 아니면 rds 로 바꾼 새 리비전 등록 (되돌리기: .\scripts\switch.ps1 -Orders fake)
  3) ECS 태스크 한 번 실행. 가짜 문장이 아니라 Bedrock 으로 쓴다. 시작 전에 비용 안내 후 y 를 물어본다.
.PARAMETER Date
  리뷰 날짜 (yyyy-MM-dd). 없으면 어제(KST 달력, 2026-10-23 변경).
.PARAMETER Yes
  비용 확인 없이 바로 시작.
.EXAMPLE
  .\scripts\run-rds.ps1
.EXAMPLE
  .\scripts\run-rds.ps1 -Date 2026-10-20
#>
param(
    [ValidatePattern("^\d{4}-\d{2}-\d{2}$")] [string] $Date,
    [switch] $Yes,
    [string] $Region
)
. "$PSScriptRoot\_common.ps1"
$a = @()
if ($Date) { $a += @("--date", $Date) }
if ($Yes) { $a += "--yes" }
Invoke-Deploy -Name "run_rds" -Arguments $a -Region $Region
