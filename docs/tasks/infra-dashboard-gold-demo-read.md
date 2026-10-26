# Dashboard Gold A 시연 근거 읽기 권한

상태: 구현·검증 완료 / 사용자 머지 승인·재영 적용 대기

## 범위와 검증

- 소유 스택: `infra/stacks/dashboard-access`, 모듈 `infra/modules/dashboard-access`.
- 실제 Pod: namespace `dashboard`, ServiceAccount `approval-dashboard`, Pod Identity 역할 `clothes-query-dev-approval-dashboard`.
- 별도 inline policy `gold-a-demo-evidence-read-only`: checkpoint tip, 퍼널 고정·완료 manifest, 입력 inventory의 네 경로 패턴에 `s3:GetObject`만 추가한다.
- 정확한 키를 GetObject하므로 새 ListBucket은 불필요하다. 기존 지표의 prefix 제한 ListBucket은 유지한다.
- 기존 공유 정책, Gold B·Airflow·Spark 역할, trust policy, workgroup, 쓰기·삭제는 변경하지 않는다.
- 최신 main `78ae762` 기준 `terraform fmt -check`, `validate` 성공. 실제 remote state plan: **1 add / 0 change / 0 destroy**.
- 유일한 변경: `module.dashboard_access.aws_iam_role_policy.gold_a_demo_evidence[0]` 생성. apply·운영 빌드·배포는 하지 않았다.

## 내일 적용 순서 (재영)

1. 사용자 승인 후 **이 IAM PR만 먼저 main에 머지**한다. 이 PR은 대시보드 소스·배포 workflow를 바꾸지 않아 이미지 배포를 시작하지 않는다.
2. 깨끗한 운영 checkout에서 최신 main을 받는다. 내일의 state로 plan을 다시 만들고 정책 하나만 추가되는지 검토한다.

```powershell
# 저장소 루트 / PowerShell
git switch main
git pull --ff-only
terraform '-chdir=infra/stacks/dashboard-access' init -input=false '-backend-config=deployment.backend.hcl'
terraform '-chdir=infra/stacks/dashboard-access' fmt -check
terraform '-chdir=infra/stacks/dashboard-access' validate
terraform '-chdir=infra/stacks/dashboard-access' plan -input=false '-out=gold-demo.tfplan'
# 1 add / 0 change / 0 destroy 및 위 정책 하나인지 확인. 다른 변경은 중단·검토.
terraform '-chdir=infra/stacks/dashboard-access' apply 'gold-demo.tfplan'
```

3. IAM 적용 후 실제 Pod 역할로 네 경로가 읽히는지 확인한다. 원문·세션 ID는 출력하지 않는다.

```powershell
$pod = kubectl --context clothes-query-dev-admin get pods -n dashboard -l app=dashboard -o jsonpath='{.items[0].metadata.name}'
@'
import boto3,json,hashlib
s=boto3.client('s3',region_name='ap-northeast-1'); b='clothes-query-datalake'
def read(key): return s.get_object(Bucket=b,Key=key)['Body'].read()
c=json.loads(read('silver/runtime/clicks/catalog-control/incremental.json'))
r=read(c['tip']['uri'].split('/',3)[3]); assert hashlib.sha256(r).hexdigest()==c['tip']['sha256']
m=json.loads(r); assert json.loads(read('gold_a/runtime/funnels/completed/'+m['run_id']+'.json'))==m
v=read(m['inventory']['uri'].split('/',3)[3]); assert hashlib.sha256(v).hexdigest()==m['inventory']['sha256']
print('EVIDENCE_READ_OK',m['run_id'],m['status'],len(m['processed']),len(json.loads(v)['objects']),m['batch']['remaining_files'])
'@ | kubectl --context clothes-query-dev-admin exec -i -n dashboard $pod -- python -
```

4. **그 다음** 사용자 승인 후 대시보드 앱 PR을 머지한다. 기존 `Dashboard deploy` workflow가 main SHA 이미지 빌드→ECR push→digest를 `deploy/dashboard`에 기록하고 Argo CD가 반영한다.
5. 앱 PR의 운영 검증 절차에 따라 운영 모드 유지·시연 PARTIAL 범위와 출처·리뷰 PASS를 확인한다.

`deploy.ps1`이나 `kubectl set image`로 이미지를 별도 변경하면 Argo CD selfHeal과 충돌한다. 기존 workflow를 사용한다. 로컬 plan·state·인증 정보는 커밋하지 않는다.

## 작업 결과

대시보드 전용 읽기 정책과 실제 plan 검증을 준비했다. IAM 선행 적용 후 앱 PR을 머지하면 추가 개발 없이 기존 CI/CD로 반영된다. 머지·apply는 승인 대기다.
