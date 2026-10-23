<#
.SYNOPSIS
  지금 한 번 하루치를 실행한다: 가짜 주문 → 그날 리뷰 → S3 bronze 날짜 파티션(덮어쓰기).
.PARAMETER Date
  리뷰 날짜 (yyyy-MM-dd). 없으면 어제(KST 달력, 2026-10-23 변경).
.PARAMETER Fake
  가짜 문장으로 실행 (Bedrock 호출 없음, 비용 0원). 배관 확인용.
.EXAMPLE
  .\scripts\run-once.ps1 -Fake
.EXAMPLE
  .\scripts\run-once.ps1 -Date 2026-10-17
#>
param(
    [ValidatePattern("^\d{4}-\d{2}-\d{2}$")] [string] $Date,
    [switch] $Fake,
    [string] $Region
)
. "$PSScriptRoot\_common.ps1"
$a = @("once")
if ($Date) { $a += @("--date", $Date) }
if ($Fake) { $a += "--fake" }
Invoke-Deploy -Name "onoff" -Arguments $a -Region $Region
