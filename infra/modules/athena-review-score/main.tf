# 리뷰 점수 결과를 Iceberg 테이블로 관리하기 위한 Athena/Glue 기반 (stacks/athena-review-score) — 초안 (2026-10-22)
#
# 배경: 점수 결과를 날짜+모델버전별 파일 덮어쓰기(방식 A) 대신, Iceberg 테이블에 MERGE 로 반영(방식 D)한다.
#   흐름: SageMaker Job -> S3 staging(Parquet) -> Athena `MERGE INTO` -> Iceberg 테이블(S3 + Glue 카탈로그) -> Gold/대시보드가 Athena 로 읽기
#
# 이 모듈이 만드는 것
#   - Glue 데이터베이스 1개
#   - Athena 워크그룹 1개(엔진 v3, 결과 저장 위치, 쿼리당 스캔 한도, 설정 강제)
#   - Airflow 가 붙일 IAM 정책 1개(athena_runner): Athena 쿼리 실행·조회, Glue 해당 DB/테이블, S3 해당 prefix. 어떤 역할에도 자동으로 붙지 않는다
#   - 스크립트용 설정 묶음(SSM 파라미터 JSON 1개)
#
# 만들지 않는 것
#   - Iceberg 테이블, staging 외부 테이블: Terraform 의 aws_glue_catalog_table 은 Iceberg 파티션 사양을 정할 수 없어서
#     Athena DDL(stacks/athena-review-score/sql/*.sql)로 만든다. 실행은 사람이 한 번 하거나 Airflow 초기화 태스크가 한다.
#   - 버킷·S3 수명주기: 버킷은 storage 스택 소유다. 수명주기 규칙은 버킷당 한 리소스만 둘 수 있어 이 스택에서 건드리면 충돌한다.
#   - MERGE/OPTIMIZE/VACUUM 실행: Airflow 태스크 몫이다(sql/ 의 템플릿 사용).
#   - SageMaker Job 쪽 변경(출력 prefix 를 staging 으로): stacks/sagemaker-review-score 의 별도 변경이다.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  staging_arn = "${var.bucket_arn}/${var.staging_prefix}/*"
  table_arn   = "${var.bucket_arn}/${var.table_prefix}/*"
  results_arn = "${var.bucket_arn}/${var.results_prefix}/*"

  # s3:ListBucket 은 리소스 제한이 안 되어 prefix 조건으로 좁힌다.
  list_prefixes = [
    "${var.staging_prefix}/*",
    "${var.table_prefix}/*",
    "${var.results_prefix}/*",
  ]

  catalog_arn  = "arn:${local.partition}:glue:${var.region}:${local.account_id}:catalog"
  database_arn = "arn:${local.partition}:glue:${var.region}:${local.account_id}:database/${aws_glue_catalog_database.this.name}"
  tables_arn   = "arn:${local.partition}:glue:${var.region}:${local.account_id}:table/${aws_glue_catalog_database.this.name}/*"
}

# ------------------------------------------------------------------ Glue 데이터베이스
# 테이블(점수 Iceberg 테이블, staging 외부 테이블)이 속하는 논리적 묶음. 데이터는 S3 에 있고 여기엔 메타데이터만 있다.
resource "aws_glue_catalog_database" "this" {
  name        = var.database_name
  description = "review aspect scores (Iceberg table + staging external table)"
}

# ------------------------------------------------------------------ Athena 워크그룹
# 이 워크그룹으로 실행한 쿼리는 아래 설정이 강제된다(쿼리마다 결과 위치를 따로 지정할 수 없다).
# 비용: Athena 는 스캔한 데이터량 기준으로 과금한다(단가는 도쿄 리전 요금표에서 확인). bytes_scanned_cutoff 가 폭주 쿼리를 막는다.
resource "aws_athena_workgroup" "this" {
  name        = var.name
  description = "review score Iceberg MERGE/OPTIMIZE/VACUUM and reads"
  state       = "ENABLED"

  # false: 쿼리 기록이 남은 워크그룹을 destroy 가 지우지 못하게 한다(삭제하려면 일부러 true 로 바꾼다).
  force_destroy = false

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.bytes_scanned_cutoff

    engine_version {
      # Iceberg MERGE/OPTIMIZE/VACUUM 은 엔진 v3 에서 지원한다.
      selected_engine_version = "Athena engine version 3"
    }

    result_configuration {
      output_location = "s3://${var.bucket_name}/${var.results_prefix}/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}

# ------------------------------------------------------------------ IAM: Airflow 가 붙일 정책
# Airflow 가 쓰는 역할은 이 스택 소관이 아니므로 "붙일 수 있는 정책"만 만든다(sagemaker-review-score 의 launcher 와 같은 방식).
# 권한이 넓어 보이는 곳과 이유:
#   - S3 table_prefix 의 DeleteObject: VACUUM 이 오래된 파일을 지우고 MERGE 가 파일을 새로 쓰기 때문
#   - Glue UpdateTable/CreateTable: Iceberg 가 커밋할 때 카탈로그의 메타데이터 위치를 갱신하기 때문(해당 DB의 테이블만)
data "aws_iam_policy_document" "athena_runner" {
  statement {
    sid = "RunQueriesInWorkgroup"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StopQueryExecution",
      "athena:GetWorkGroup",
    ]
    resources = [aws_athena_workgroup.this.arn]
  }

  statement {
    sid = "GlueCatalogRead"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetTableVersion",
      "glue:GetTableVersions",
      "glue:GetPartition",
      "glue:GetPartitions",
    ]
    resources = [local.catalog_arn, local.database_arn, local.tables_arn]
  }

  statement {
    sid       = "GlueTableWrite"
    actions   = ["glue:CreateTable", "glue:UpdateTable"]
    resources = [local.catalog_arn, local.database_arn, local.tables_arn]
  }

  statement {
    sid       = "ReadStaging"
    actions   = ["s3:GetObject"]
    resources = [local.staging_arn]
  }

  statement {
    sid       = "ReadWriteTable"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [local.table_arn]
  }

  statement {
    sid       = "AthenaResults"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
    resources = [local.results_arn]
  }

  statement {
    sid       = "ListUsedPrefixes"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = local.list_prefixes
    }
  }
}

resource "aws_iam_policy" "athena_runner" {
  name        = "${var.name}-runner"
  description = "Attach to the Airflow role that runs MERGE/OPTIMIZE/VACUUM on the review score Iceberg table"
  policy      = data.aws_iam_policy_document.athena_runner.json
}

# ------------------------------------------------------------------ 스크립트용 설정 묶음
# Airflow/스크립트가 Terraform 을 몰라도 되게 이 값 하나만 읽는다. 버킷 이름이 들어 있어 저장소에는 두지 않고 SSM 에만 둔다.
# sql/*.sql 의 {{자리표시자}} 를 이 값으로 채운다.
resource "aws_ssm_parameter" "config" {
  name        = var.config_parameter_name
  description = "review score Iceberg/Athena config for Airflow tasks (managed by Terraform)"
  type        = "String"
  value = jsonencode({
    region             = var.region
    workgroup          = aws_athena_workgroup.this.name
    database           = aws_glue_catalog_database.this.name
    table              = var.table_name
    staging_table      = var.staging_table_name
    staging_location   = "s3://${var.bucket_name}/${var.staging_prefix}/"
    table_location     = "s3://${var.bucket_name}/${var.table_prefix}/"
    results_location   = "s3://${var.bucket_name}/${var.results_prefix}/"
    runner_policy_name = aws_iam_policy.athena_runner.name
  })
}
