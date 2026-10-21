# scripts/ — Windows PowerShell 스크립트 (2026-10-19)

ECS 배포·운영 기능(`deploy/*.py`)을 PowerShell 에서 바로 부르는 얇은 포장이다. 하는 일은 `deploy/` 와 같고,
자세한 설명은 [deploy/README.md](../deploy/README.md). 어느 폴더에서 실행해도 `review-simulator\` 기준으로 돈다.

| 스크립트 | 하는 일 | 예 |
|---|---|---|
| `check-access.ps1` | AWS 권한 확인 (읽기 전용) | `.\scripts\check-access.ps1` |
| `infra.ps1` | Terraform 스택 `check` / `init` / `plan` / `apply` | `.\scripts\infra.ps1 plan` |
| `secret.ps1` | Bedrock API 키 넣기·확인, RDS 접속 주소(`-OrdersDb`) | `.\scripts\secret.ps1 -FromEnv` · `-Check` · `-OrdersDb` |
| `deploy.ps1` | 이미지 빌드 → ECR → 태스크 정의 등록 | `.\scripts\deploy.ps1 -DryRun` |
| `onoff.ps1` | 예약 실행 켜기 / 끄기 | `.\scripts\onoff.ps1 off` |
| `run-once.ps1` | 지금 한 번 하루치 실행 | `.\scripts\run-once.ps1 -Fake` · `-Date 2026-10-17` |
| `run-rds.ps1` | RDS 주문으로 실제 리뷰(Bedrock) 한 번 생성 (주문 입력을 rds 로 맞춘 뒤 실행, 비용 확인 후 시작) | `.\scripts\run-rds.ps1` · `-Date 2026-10-20` |
| `switch.ps1` | 리뷰 작성 비율 low · normal · high, 주문 입력 rds · fake | `.\scripts\switch.ps1 high` · `-Rate 0.3` · `-Orders rds` · `-Show` |
| `status.ps1` | 상태·최근 실행·추정 비용 | `.\scripts\status.ps1 -Cost` |
| `run-incident.ps1` | 특정 상품·카테고리 긍정·부정 비율 올려 실행 | `.\scripts\run-incident.ps1 -ProductId W-0003 -Aspect 품질·내구성 -Sentiment 부정 -Share 0.6` |
| `run-inject.ps1` | 직접 쓴 리뷰 파일 넣기 | `.\scripts\run-inject.ps1 -File .local\manual\a.csv` |

각 스크립트 `Get-Help .\scripts\<이름>.ps1 -Detailed` 로 옵션과 예시를 볼 수 있다. 모든 스크립트에 `-Region` 이 있다(기본 ap-northeast-1).

## 처음 한 번

```powershell
cd C:\workspace\e-commerce\clothes-query\review-simulator
# 스크립트 실행이 막혀 있으면 (이 창에서만 허용)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
aws login                                  # 또는 aws configure sso
.\scripts\check-access.ps1
$env:TF_VAR_expected_account_id = "<계정 ID>"
.\scripts\infra.ps1 init -Reconfigure      # state key 를 바꾼 뒤라 한 번은 -Reconfigure
.\scripts\infra.ps1 plan                   # 내용 확인 후
.\scripts\infra.ps1 apply
.\scripts\secret.ps1 -FromEnv
.\scripts\deploy.ps1
.\scripts\run-once.ps1 -Fake               # 비용 0원 시험
.\scripts\status.ps1
```

## 참고

- 파이썬은 `review-simulator\.venv` 를 쓴다. 다른 파이썬은 `$env:RSIM_PYTHON` 으로 지정한다.
- 파일은 UTF-8(BOM) 로 저장되어 있다. 한글 옵션(`-Aspect 배송` 등)이 Windows PowerShell 5.1 에서도 깨지지 않게 하기 위해서다.
  편집기로 고칠 때 인코딩을 바꾸지 않는다.
- 스크립트는 AWS 키·Bedrock 키를 출력하지 않는다. 계정 ID 는 환경변수로만 넣고 파일에 적지 않는다.
