<#
.SYNOPSIS
  특정 상품(또는 카테고리)의 긍정·부정 리뷰 비율을 올려 하루치를 한 번 실행한다 (이미 있는 incidents 기능).
.DESCRIPTION
  그날 그 상품 리뷰 중 Share 비율에 지정한 속성·감성이 들어간다. 부정이면 별점도 1~3점으로 내려간다.
  그날 파티션(part-00000.jsonl)을 덮어쓴다. 원래대로 돌리려면 같은 날짜로 run-once.ps1.
  속성 이름은 taxonomy.py 의 11개 중 하나 (예: 사이즈·핏, 품질·내구성, 배송, 색상·디자인).
.EXAMPLE
  .\scripts\run-incident.ps1 -ProductId W-0003 -Aspect 품질·내구성 -Sentiment 부정 -Share 0.6 -Date 2026-10-17
.EXAMPLE
  .\scripts\run-incident.ps1 -Category 패션슈즈 -Aspect 배송 -Sentiment 부정 -Share 0.4 -DryRun
#>
param(
    [string] $ProductId,
    [string] $Category,
    [Parameter(Mandatory)] [string] $Aspect,
    [Parameter(Mandatory)] [ValidateSet("긍정", "중립", "부정")] [string] $Sentiment,
    [ValidateRange(0.01, 1.0)] [double] $Share = 0.6,
    [ValidatePattern("^\d{4}-\d{2}-\d{2}$")] [string] $Date,
    [string] $Id,
    [string] $Note,
    [switch] $Fake,
    [switch] $DryRun,
    [string] $Region
)
. "$PSScriptRoot\_common.ps1"
if ([bool]$ProductId -eq [bool]$Category) {
    Write-Host "-ProductId 또는 -Category 중 하나만 주세요" -ForegroundColor Red
    exit 2
}
$a = @()
if ($ProductId) { $a += @("--product-id", $ProductId) }
if ($Category) { $a += @("--category", $Category) }
$a += @("--aspect", $Aspect, "--sentiment", $Sentiment)
$a += @("--share", $Share.ToString([System.Globalization.CultureInfo]::InvariantCulture))
if ($Date) { $a += @("--date", $Date) }
if ($Id) { $a += @("--id", $Id) }
if ($Note) { $a += @("--note", $Note) }
if ($Fake) { $a += "--fake" }
if ($DryRun) { $a += "--dry-run" }
Invoke-Deploy -Name "run_incident" -Arguments $a -Region $Region
