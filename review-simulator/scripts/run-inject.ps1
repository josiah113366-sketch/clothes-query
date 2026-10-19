<#
.SYNOPSIS
  직접 쓴 리뷰 파일(CSV/JSONL)을 검사 → S3 업로드 → ECS 에서 rsim inject 한 번 실행.
.DESCRIPTION
  그 날짜 파티션에 part-manual-<파일 이름>.jsonl 로 따로 쓴다(매일 실행분은 그대로). 같은 이름이면 덮어쓴다.
  형식은 data\manual_reviews.example.csv. 실제 쇼핑몰 리뷰를 옮겨 적은 파일은 넣지 않는다(private 경로는 거부).
.EXAMPLE
  .\scripts\run-inject.ps1 -File .local\manual\size_spike_1008.csv -DryRun
#>
param(
    [Parameter(Mandatory)] [string] $File,
    [switch] $DryRun,
    [string] $Region
)
. "$PSScriptRoot\_common.ps1"
# 상대 경로는 지금 폴더 기준으로 절대 경로로 바꾼다 (deploy 스크립트는 review-simulator\ 에서 돈다)
$full = (Resolve-Path -LiteralPath $File).Path
$a = @("--file", $full)
if ($DryRun) { $a += "--dry-run" }
Invoke-Deploy -Name "run_inject" -Arguments $a -Region $Region
