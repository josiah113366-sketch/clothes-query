# athena-review-score stack (초안)

리뷰 점수 결과를 **Iceberg 테이블 + MERGE** 로 관리하기 위한 Athena/Glue 기반 (방식 D). 담당: lemin 이 작성하고, apply 는 인프라 담당(재영)이 plan 을 확인한 뒤 실행한다.
작업 지시서: [infra-athena-review-score.md](../../../docs/tasks/infra-athena-review-score.md). 모듈: [modules/athena-review-score](../../modules/athena-review-score/README.md).

- 선행: bootstrap(state 버킷), storage(데이터 버킷). 후행/연동: [sagemaker-review-score](../sagemaker-review-score/README.md) 의 출력 prefix 를 staging 으로 바꾸는 별도 변경이 필요하다.
- backend key: `clothes-query/dev/athena-review-score/terraform.tfstate`.
- 만드는 것(6개): Glue 데이터베이스, **Iceberg 테이블**(`review_aspect_scores`, 파티션 `review_date`)과 **staging 외부 테이블**(Glue 테이블 리소스), Athena 워크그룹(엔진 v3, 결과 위치, 쿼리당 스캔 10GB 한도, 설정 강제), Airflow 용 IAM 정책 `athena_runner`(어떤 역할에도 자동으로 붙지 않음), 스크립트용 SSM 파라미터.
- 만들지 않는 것: 버킷·S3 수명주기(storage 소유), MERGE/OPTIMIZE/VACUUM 실행(Airflow), SageMaker 스택 변경.
- 비용: 만들어 두기만 하면 0. Athena 는 쿼리가 스캔한 데이터량 기준 과금(단가는 도쿄 리전 요금표 확인), 쿼리 결과·Iceberg 파일은 S3 저장 요금.

## 전체 흐름

```
Airflow(silver DAG 종료) → SageMaker Job → S3 staging(Parquet, year=/month=/day=)
   → Athena MERGE INTO → Iceberg 테이블(S3 table_prefix + Glue 카탈로그) → Gold/대시보드가 Athena 로 읽기
정기: Airflow → Athena OPTIMIZE(작은 파일 합치기), VACUUM(오래된 스냅샷 삭제)
```

그림: 세션에서 공유한 `iceberg-flow.svg` 참고(저장소 미포함).

## 실행 (Terraform)

비공개 입력은 Git 제외 파일에만 둔다 (`deployment.backend.hcl`, `deployment.local.tfvars`).

```powershell
cd infra/stacks/athena-review-score
# 비공개 파일 2개 (커밋 안 됨): deployment.backend.hcl (bucket, region), deployment.local.tfvars (terraform.tfvars.example 복사)
$env:TF_VAR_expected_account_id = "<계정 ID>"

terraform init -backend=false -lockfile=readonly   # 정적 검사
terraform fmt -check
terraform validate

terraform init -backend-config=deployment.backend.hcl -lockfile=readonly
terraform plan -input=false -var-file=deployment.local.tfvars -out=athena-review-score.tfplan
terraform apply athena-review-score.tfplan      # plan 을 확인한 담당자가 실행
```

첫 plan 은 6 create 여야 한다(다른 스택 리소스를 바꾸지 않음). destroy/replace 가 보이면 멈추고 확인한다.

## apply 후: 사용 순서

테이블(Iceberg, staging)은 **Terraform 이 만든다**(Glue 테이블 리소스의 `open_table_format_input`). [sql/](sql/) 에는 반영·유지보수·읽기용 쿼리 템플릿만 있다.
`{{자리표시자}}` 는 SSM 설정 파라미터(`config_parameter_name` output)의 값으로 채운다(버킷 이름을 저장소에 쓰지 않기 위해서).

| 순서 | 파일 | 실행 시점 | 자리표시자 |
|---|---|---|---|
| 1 | `merge.sql` | 매일, Job 완료 후 날짜마다 | `database`, `table`, `staging_table`, `year`, `month`, `day`, `model_version` |
| 2 | `optimize.sql` | 정기(예: 주 1회) | `database`, `table`, `since` |
| 3 | `vacuum.sql` | 정기(OPTIMIZE 뒤) | `database`, `table` |
| - | `read_latest.sql` | 읽기 예시 | `database`, `table`, `date` |

모든 쿼리는 `workgroup` 으로 실행한다. 예(수동, 첫 확인용):

```powershell
$cfg = (aws ssm get-parameter --name /clothes-query/dev/athena-review-score/config --region ap-northeast-1 --query Parameter.Value --output text | ConvertFrom-Json)
# merge.sql 등의 자리표시자를 $cfg 값으로 바꿔 변수 $sql 에 담은 뒤:
aws athena start-query-execution --work-group $cfg.workgroup --query-string $sql --region ap-northeast-1
aws athena get-query-execution --query-execution-id <ID> --region ap-northeast-1 --query "QueryExecution.Status"
```

(Git Bash 에서는 SSM 이름 앞에 `MSYS_NO_PATHCONV=1` 이 필요하다.)

## SageMaker 스택과의 연결 (별도 변경)

`stacks/sagemaker-review-score` 의 `output_prefix` 를 이 스택의 `staging_prefix`(기본 `staging/review-score`)로 바꿔야 Job 이 staging 에 쓴다. 그 스택의 Job 역할 쓰기 권한과 SSM 설정이 같이 바뀐다.
이 변경은 이 초안에 포함하지 않았다(이미 apply 된 스택이라 별도 plan 확인 후).

## 열린 질문 (결정 필요)

1. **다시 점수화했더니 사라진 속성**: MERGE 는 원본에 없는 행을 지우지 않는다. 예전에 속성 X 가 있었는데 새 결과에는 없으면 옛 행이 남는다. 후기 단위로 지우고 다시 넣는 방식(DELETE + INSERT, 비원자적)을 쓸지 정해야 한다.
2. **staging 정리**: 반영이 끝난 staging 파일을 누가 지울지(Airflow 태스크 vs S3 수명주기). 수명주기는 버킷 소유 스택(storage)의 변경이라 이 스택에서 하지 않았다.
3. **Athena 결과 정리**: 쿼리마다 작은 결과 파일이 쌓인다. 같은 이유로 수명주기는 storage 스택에서 정해야 한다.
4. **Gold 의 버전 선택 규칙**: `read_latest.sql` 처럼 최신 버전만 읽을지, 특정 버전을 고정할지.
5. **타임스탬프 타입**: `analyzed_at` 이 Parquet 의 UTC timestamp 인데 Athena Hive 테이블·Iceberg 의 `timestamp`(시간대 없음)로 읽힌다. 첫 실행에서 값이 맞는지 확인해야 한다.
6. **검증 전 가정**: Terraform 이 만든 Iceberg 테이블(필드 id, 파티션 사양, `jsonencode` 한 타입)이 Athena 에서 정상으로 읽히고 `MERGE`/`OPTIMIZE`/`VACUUM` 이 되는지는 첫 apply 에서 확인해야 한다. `sql/*.sql` 도 실제 Athena 에서 실행해 보지 않았다.
   Glue 가 테이블 생성 뒤 값을 채워 diff 가 계속 보일 수 있어 `open_table_format_input`·`parameters` 는 `ignore_changes` 로 두었다(스키마 변경은 Athena `ALTER TABLE`).
   안 되면 테이블 리소스 2개를 Terraform 에서 빼고 Athena DDL(`CREATE TABLE ... TBLPROPERTIES ('table_type'='ICEBERG')` / 파티션 프로젝션 Hive 외부 테이블)로 만드는 방식으로 바꾼다.
7. **Airflow 실행 방식**: Athena 쿼리 시작/대기는 Airflow Operator(예: AthenaOperator) 사용 여부, 실패 시 재시도 정책.

## 삭제 및 운영 주의

- destroy 하면 Glue 테이블 정의는 지워지지만 Iceberg 의 S3 데이터·메타데이터 파일은 자동으로 지워지지 않는다(S3 에서 직접 정리).
- Athena 워크그룹은 쿼리 기록이 남아 있어 `force_destroy=false` 다. 지우려면 일부러 바꾼 뒤 apply 한다.
- 점수 스키마를 바꾸려면 Athena `ALTER TABLE` 을 쓴다. Terraform 은 `ignore_changes` 라서 스키마 변경을 적용하지 않는다.
