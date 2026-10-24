<#
대시보드 파드의 AWS 읽기 권한 확인 (읽기만 한다. 아무것도 바꾸지 않는다).

무엇을 보나
  1. Pod Identity 연결: dashboard namespace 의 ServiceAccount 에 어떤 IAM 역할이 붙어 있나
  2. 역할 정책: 그 역할이 읽을 수 있는 Glue 테이블과 S3 경로 목록 (IAM 조회 권한이 있을 때)
  3. 실제 조회: 대시보드 파드 안에서 파드의 권한으로 S3 목록과 Athena 쿼리를 한 번씩 실행해 OK/실패를 찍는다.
     흐름도(파이프라인 상태 > 데이터 흐름)가 읽는 곳 + 비교용으로 원래 허용된 곳(anomaly_current)을 본다.

비용: Athena 쿼리는 dt/hour 파티션 조건과 LIMIT 1 을 걸어 KB 단위만 읽는다. 결과 파일은 workgroup 결과 경로(athena-results/dashboard/)에 남는다.

실행 (저장소의 infra/platform 에서, deploy.ps1 과 같은 셸)
  aws login
  $env:KUBECONFIG = "<저장소>\.cache\eks-kubeconfig.private"
  .\dashboard\check-access.ps1            # 전부
  .\dashboard\check-access.ps1 -SkipIam   # IAM 조회 권한이 없을 때 1·2번 건너뛰기
#>
param(
    [string] $Namespace = "dashboard",
    [string] $Deployment = "dashboard",
    [string] $Cluster = "clothes-query-dev-eks",
    [string] $Region = "ap-northeast-1",
    # infra/modules/dashboard-access 가 만드는 역할·정책 이름. 바뀌면 여기만 고친다
    [string] $RoleName = "clothes-query-dev-approval-dashboard",
    [string] $PolicyName = "dashboard-reads-and-reprocess-event-writes",
    [switch] $SkipIam
)
$ErrorActionPreference = "Stop"

function Write-Step([string] $t) { Write-Host "`n== $t" -ForegroundColor Cyan }

if (-not $SkipIam) {
    Write-Step "1. Pod Identity 연결 ($Namespace)"
    & aws eks list-pod-identity-associations --cluster-name $Cluster --namespace $Namespace --region $Region `
        --query "associations[].{serviceAccount:serviceAccount,associationId:associationId}" --output table
    if ($LASTEXITCODE -ne 0) { Write-Warning "연결 조회 실패 (eks:ListPodIdentityAssociations 권한 또는 클러스터 이름 확인)" }

    Write-Step "2. 역할 정책 ($RoleName / $PolicyName)"
    $raw = & aws iam get-role-policy --role-name $RoleName --policy-name $PolicyName --output json
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "정책 조회 실패 (iam:GetRolePolicy 권한이 없으면 -SkipIam 으로 3번만 본다)"
    } else {
        $doc = ($raw | Out-String | ConvertFrom-Json).PolicyDocument
        foreach ($s in $doc.Statement) {
            # Glue 테이블·DB 와 S3 경로만 추려서 보여 준다 (계정 번호는 지워서 짧게)
            $res = @($s.Resource) | ForEach-Object { $_ -replace "arn:aws:(glue|s3):[^:]*:\d*:?", "" }
            Write-Host ("  [{0}] {1} {2}" -f $s.Effect, $s.Sid, ($s.Action -join ","))
            $res | ForEach-Object { Write-Host "      $_" }
        }
    }
}

Write-Step "3. 파드 안에서 실제 조회 (deploy/$Deployment)"
# 파드 안 python 으로 실행한다. boto3 는 대시보드 이미지에 들어 있다. 이 코드는 파일로 남기지 않고 stdin 으로 넘긴다
$py = @'
import os, time, datetime as dt
import boto3
from botocore.exceptions import ClientError

region = os.getenv("AWS_REGION", "ap-northeast-1")
wg = os.getenv("DASHBOARD_ATHENA_WORKGROUP") or os.getenv("APPROVAL_ATHENA_WORKGROUP", "")
bucket = "clothes-query-datalake"
now = dt.datetime.now(dt.timezone.utc)
d, h = now.strftime("%Y-%m-%d"), now.strftime("%H")

print("역할:", boto3.client("sts", region_name=region).get_caller_identity()["Arn"])
print("workgroup:", wg or "(없음)")

# S3: 흐름도가 읽는 경로마다 1개만 나열해 본다 (ListBucket 권한 확인)
s3 = boto3.client("s3", region_name=region)
for p in ["gold_b/bronze_lag_snapshots/", "gold_b/topic_messages/", "gold_b/payment_events/",
          "gold_b/malformed_events/", "silver/runtime/trade/catalog/completed/", "gold_a/catalog/",
          "gold_b/anomaly/", "bronze/reviews/"]:
    try:
        n = s3.list_objects_v2(Bucket=bucket, Prefix=p, MaxKeys=1).get("KeyCount", 0)
        print(f"  S3 OK    {p}  ({'파일 있음' if n else '비어 있음'})")
    except ClientError as e:
        print(f"  S3 실패  {p}  {e.response['Error']['Code']}")

# Athena: Glue 테이블 읽기 + S3 데이터 읽기를 함께 확인한다 (한 줄만)
checks = {
    "gold_b.bronze_lag_snapshots": f"SELECT 1 FROM gold_b.bronze_lag_snapshots WHERE dt='{d}' AND hour='{h}' LIMIT 1",
    "gold_b.topic_messages": f"SELECT 1 FROM gold_b.topic_messages WHERE dt='{d}' LIMIT 1",
    "gold_b.payment_events": f"SELECT 1 FROM gold_b.payment_events WHERE dt='{d}' LIMIT 1",
    "gold_b.malformed_events": f"SELECT 1 FROM gold_b.malformed_events WHERE dt='{d}' LIMIT 1",
    "silver.silver_runs": "SELECT 1 FROM silver.silver_runs LIMIT 1",
    "gold_a.gold_runs": "SELECT 1 FROM gold_a.gold_runs LIMIT 1",
    "gold_b.anomaly_current (비교용)": "SELECT 1 FROM gold_b.anomaly_current LIMIT 1",
}
if not wg or wg.startswith("<"):
    print("  Athena 건너뜀: workgroup 환경변수가 없음")
else:
    ath = boto3.client("athena", region_name=region)
    for name, sql in checks.items():
        try:
            qid = ath.start_query_execution(QueryString=sql, WorkGroup=wg)["QueryExecutionId"]
            for _ in range(60):
                s = ath.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
                if s["State"] not in ("QUEUED", "RUNNING"):
                    break
                time.sleep(0.5)
            if s["State"] == "SUCCEEDED":
                rows = len(ath.get_query_results(QueryExecutionId=qid)["ResultSet"]["Rows"]) - 1
                print(f"  Athena OK    {name}  ({'행 있음' if rows else '행 없음'})")
            else:
                print(f"  Athena 실패  {name}  {s['State']}: {s.get('StateChangeReason', '')[:200]}")
        except ClientError as e:
            print(f"  Athena 실패  {name}  {e.response['Error']['Code']}: {e.response['Error']['Message'][:200]}")
'@
$py | & kubectl exec -i -n $Namespace "deploy/$Deployment" -- python -
if ($LASTEXITCODE -ne 0) { Write-Warning "파드 안 실행 실패 (kubectl 접속, 파드 상태 확인)" }

Write-Host "`n읽는 법: '실패 ... AccessDenied' 는 권한 부족, 'TABLE_NOT_FOUND'·'EntityNotFound' 는 테이블이 Glue 에 없음,"
Write-Host "        'OK (행 없음)' 은 권한은 있고 그 파티션에 데이터가 아직 없는 것. 비교용 anomaly_current 가 OK 면 workgroup 자체는 정상."
