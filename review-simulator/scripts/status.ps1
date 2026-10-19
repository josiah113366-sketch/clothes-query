<#
.SYNOPSIS
  상태 한 화면: 예약 실행, 실행 설정, 돌고 있는 태스크, 최근 종료 기록·실행(리뷰 수·토큰·추정 비용), S3 마지막 날짜.
.PARAMETER Cost
  이번 달 실제 청구액도 본다 (Cost Explorer, 호출 1번에 $0.01).
.EXAMPLE
  .\scripts\status.ps1
.EXAMPLE
  .\scripts\status.ps1 -Cost
#>
param(
    [switch] $Cost,
    [string] $Region
)
. "$PSScriptRoot\_common.ps1"
$a = @()
if ($Cost) { $a += "--cost" }
Invoke-Deploy -Name "status" -Arguments $a -Region $Region
