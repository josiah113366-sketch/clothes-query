<#
.SYNOPSIS
  하루 1번 예약 실행(매일 00:30 UTC = 09:30 KST)을 켜거나 끈다.
.DESCRIPTION
  on  : 최신 태스크 정의 리비전으로 예약 실행을 켠다.
  off : 예약 실행을 끄고, 돌고 있는 태스크도 멈춘다 (현재 배치까지만 쓰고 끝남).
  지금 한 번만 돌리려면 run-once.ps1.
.EXAMPLE
  .\scripts\onoff.ps1 off
#>
param(
    [Parameter(Mandatory, Position = 0)] [ValidateSet("on", "off")] [string] $Action,
    [string] $Region
)
. "$PSScriptRoot\_common.ps1"
Invoke-Deploy -Name "onoff" -Arguments @($Action) -Region $Region
