<#
.SYNOPSIS
  실행 모드(리뷰 작성 비율 REVIEW_RATE)를 바꾼다. 하루 리뷰 수 ≈ 가짜 주문 1,000건 x 비율.
.DESCRIPTION
  low 0.1 (약 100건) / normal 0.5 (약 500건) / high 1.0 (약 1,000건) 또는 -Rate 로 직접 지정 (0 초과 1 이하).
  REVIEW_RATE 만 바꾼 새 리비전을 등록한다. 스케줄이 켜져 있으면 다음 예약 실행부터 적용된다.
.EXAMPLE
  .\scripts\switch.ps1 -Show
.EXAMPLE
  .\scripts\switch.ps1 high
.EXAMPLE
  .\scripts\switch.ps1 -Rate 0.3
#>
param(
    [Parameter(Position = 0)] [ValidateSet("low", "normal", "high")] [string] $Preset,
    [double] $Rate = 0,
    [switch] $Show,
    [string] $Region
)
. "$PSScriptRoot\_common.ps1"
$a = @()
if ($Preset) { $a += $Preset }
if ($Rate -gt 0) { $a += @("--rate", $Rate.ToString([System.Globalization.CultureInfo]::InvariantCulture)) }
if ($Show -or (-not $Preset -and $Rate -le 0)) { $a += "--show" }
Invoke-Deploy -Name "switch" -Arguments $a -Region $Region
