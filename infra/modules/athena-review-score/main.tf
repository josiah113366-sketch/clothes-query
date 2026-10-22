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
#   - (정정 2026-10-22) 테이블은 이 모듈이 만든다: aws_glue_catalog_table 의 open_table_format_input 이 Iceberg 스키마·파티션 사양을 지원한다
#     (AWS provider 6.x 스키마로 확인). 그래서 Iceberg 테이블과 staging 외부 테이블도 Terraform 으로 만들고.
#     단, 실제 apply 로 검증하기 전이라 "Terraform 이 만든 Iceberg 테이블을 Athena 가 정상으로 읽고 MERGE 하는지"는 첫 apply 에서 확인해야 한다.
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
  # 후기별 점수 로그(review_score_log): staging 읽기, Iceberg 테이블 위치 읽기/쓰기/삭제
  staging_log_arn = "${var.bucket_arn}/${var.staging_log_prefix}/*"
  log_table_arn   = "${var.bucket_arn}/${var.log_table_prefix}/*"

  # s3:ListBucket 은 리소스 제한이 안 되어 prefix 조건으로 좁힌다.
  list_prefixes = [
    "${var.staging_prefix}/*",
    "${var.table_prefix}/*",
    "${var.results_prefix}/*",
    "${var.staging_log_prefix}/*",
    "${var.log_table_prefix}/*",
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

# ------------------------------------------------------------------ Iceberg 테이블 (최종 결과)
# Glue API 로 Iceberg 테이블을 만든다. 데이터·메타데이터는 table_location(S3) 아래에 Iceberg 가 관리한다.
# 스키마 필드 id 는 Iceberg 가 열을 식별하는 번호다(이름을 바꿔도 같은 열로 취급). 한 번 정하면 바꾸지 않는다.
# 파티션: review_date(후기 작성일, KST) 그대로(identity). 실행한 날이 아니다.
# 주의: description 을 넣지 않는다. Glue 가 Iceberg 테이블 생성 시 description 을 저장하지 않아 plan 에 매번 diff 가 생긴다(첫 apply 로 확인).
resource "aws_glue_catalog_table" "scores" {
  name          = var.table_name
  database_name = aws_glue_catalog_database.this.name

  open_table_format_input {
    iceberg_input {
      metadata_operation = "CREATE"
      version            = "2"

      iceberg_table_input {
        location = "s3://${var.bucket_name}/${var.table_prefix}/"

        # Athena 의 VACUUM 이 쓰는 보존 기준(7일 넘은 스냅샷 삭제, 최소 5개 유지) + 파일 형식
        properties = {
          "write.format.default"            = "parquet"
          "write.parquet.compression-codec" = "snappy"
          "vacuum_max_snapshot_age_seconds" = "604800"
          "vacuum_min_snapshots_to_keep"    = "5"
        }

        # 필드 type 은 JSON 문자열이어야 해서 jsonencode("string") 처럼 쓴다(provider 요구).
        schema {
          type      = "struct"
          schema_id = 0

          fields {
            id       = 1
            name     = "review_id"
            required = false
            type     = jsonencode("string")
          }
          fields {
            id       = 2
            name     = "aspect"
            required = false
            type     = jsonencode("string")
          }
          fields {
            id       = 3
            name     = "score"
            required = false
            type     = jsonencode("int")
          }
          fields {
            id       = 4
            name     = "model_version"
            required = false
            type     = jsonencode("string")
          }
          fields {
            id       = 5
            name     = "analyzed_at"
            required = false
            type     = jsonencode("timestamp")
          }
          fields {
            id       = 6
            name     = "review_date"
            required = false
            type     = jsonencode("date")
          }
          # 모델 번호 "x.y" = decimal(4,1) (2026-10-22 추가). 이미 만들어진 테이블에는 ignore_changes 때문에 이 정의가 적용되지 않는다 →
          # stacks/athena-review-score/sql/migrate_add_model_version_no.sql 로 ALTER TABLE ADD COLUMNS 를 한 번 실행한다.
          fields {
            id       = 7
            name     = "model_version_no"
            required = false
            type     = jsonencode("decimal(4, 1)")
          }
        }

        partition_spec {
          spec_id = 0
          fields {
            field_id  = 1000
            name      = "review_date"
            source_id = 6
            transform = "identity"
          }
        }
      }
    }
  }

  # 테이블이 만들어진 뒤 스키마 변경은 Athena `ALTER TABLE` 로 한다(Iceberg 스키마 진화). Terraform 이 그 변경을 되돌리거나 테이블을 다시 만들지 않게 한다.
  # Glue 가 만든 뒤 채우는 값(metadata_location 등)이 매번 diff 로 보이는 것도 막는다.
  lifecycle {
    ignore_changes = [open_table_format_input, parameters]
  }
}

# ------------------------------------------------------------------ staging 외부 테이블 (MERGE 의 입력)
# SageMaker Job 이 <staging>/year=/month=/day=/scores_<model_version>_<실행시각>.parquet 로 쓴 파일을 읽는 일반(Hive) 외부 테이블.
# 파티션 프로젝션: 파티션을 등록하지 않아도 경로 규칙(year=YYYY/month=MM/day=DD)만 맞으면 Athena 가 알아서 찾는다.
resource "aws_glue_catalog_table" "staging" {
  name          = var.staging_table_name
  database_name = aws_glue_catalog_database.this.name
  description   = "staging Parquet from the SageMaker scoring job (input of MERGE)"
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL                    = "TRUE"
    "classification"            = "parquet"
    "projection.enabled"        = "true"
    "projection.year.type"      = "integer"
    "projection.year.range"     = "2026,2035"
    "projection.year.digits"    = "4"
    "projection.month.type"     = "integer"
    "projection.month.range"    = "1,12"
    "projection.month.digits"   = "2"
    "projection.day.type"       = "integer"
    "projection.day.range"      = "1,31"
    "projection.day.digits"     = "2"
    "storage.location.template" = "s3://${var.bucket_name}/${var.staging_prefix}/year=$${year}/month=$${month}/day=$${day}/"
  }

  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "month"
    type = "string"
  }
  partition_keys {
    name = "day"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${var.bucket_name}/${var.staging_prefix}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "review_id"
      type = "string"
    }
    columns {
      name = "aspect"
      type = "string"
    }
    columns {
      name = "score"
      type = "int"
    }
    columns {
      name = "model_version"
      type = "string"
    }
    columns {
      name = "model_version_no"
      type = "decimal(4,1)"
    }
    columns {
      name = "analyzed_at"
      type = "timestamp"
    }
    # 후기 작성일(KST). SageMaker Job 이 같은 이름의 Parquet 열(date)로 쓴다. MERGE 가 Iceberg 파티션 열 review_date 를 이 값으로 채운다.
    columns {
      name = "review_date"
      type = "date"
    }
  }
}

# ------------------------------------------------------------------ 후기별 점수 로그 Iceberg 테이블
# 점수를 매긴 후기마다 한 행: 속성이 하나도 안 나온 후기(n_aspects = 0)도 기록된다.
# 점수 테이블만 보면 "속성 0개 후기"는 점수 행이 없어서 매일 다시 점수화 대상으로 잡히기 때문에 이 로그로 "점수를 매겼는가"를 판단한다.
# 파싱에 실패한 후기는 일부러 기록하지 않는다(다음 실행에서 다시 시도되고, 실패는 오류 파일에 남는다).
resource "aws_glue_catalog_table" "score_log" {
  name          = var.log_table_name
  database_name = aws_glue_catalog_database.this.name

  open_table_format_input {
    iceberg_input {
      metadata_operation = "CREATE"
      version            = "2"

      iceberg_table_input {
        location = "s3://${var.bucket_name}/${var.log_table_prefix}/"

        properties = {
          "write.format.default"            = "parquet"
          "write.parquet.compression-codec" = "snappy"
          "vacuum_max_snapshot_age_seconds" = "604800"
          "vacuum_min_snapshots_to_keep"    = "5"
        }

        schema {
          type      = "struct"
          schema_id = 0

          fields {
            id       = 1
            name     = "review_id"
            required = false
            type     = jsonencode("string")
          }
          fields {
            id       = 2
            name     = "model_version"
            required = false
            type     = jsonencode("string")
          }
          fields {
            id       = 3
            name     = "model_version_no"
            required = false
            type     = jsonencode("decimal(4, 1)")
          }
          fields {
            id       = 4
            name     = "analyzed_at"
            required = false
            type     = jsonencode("timestamp")
          }
          fields {
            id       = 5
            name     = "review_date"
            required = false
            type     = jsonencode("date")
          }
          fields {
            id       = 6
            name     = "n_aspects"
            required = false
            type     = jsonencode("int")
          }
        }

        partition_spec {
          spec_id = 0
          fields {
            field_id  = 1000
            name      = "review_date"
            source_id = 5
            transform = "identity"
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [open_table_format_input, parameters]
  }
}

# ------------------------------------------------------------------ 점수 로그 staging 외부 테이블 (merge_log.sql 의 입력)
resource "aws_glue_catalog_table" "staging_log" {
  name          = var.staging_log_table_name
  database_name = aws_glue_catalog_database.this.name
  description   = "per-review score log Parquet from the SageMaker scoring job (input of merge_log.sql)"
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL                    = "TRUE"
    "classification"            = "parquet"
    "projection.enabled"        = "true"
    "projection.year.type"      = "integer"
    "projection.year.range"     = "2026,2035"
    "projection.year.digits"    = "4"
    "projection.month.type"     = "integer"
    "projection.month.range"    = "1,12"
    "projection.month.digits"   = "2"
    "projection.day.type"       = "integer"
    "projection.day.range"      = "1,31"
    "projection.day.digits"     = "2"
    "storage.location.template" = "s3://${var.bucket_name}/${var.staging_log_prefix}/year=$${year}/month=$${month}/day=$${day}/"
  }

  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "month"
    type = "string"
  }
  partition_keys {
    name = "day"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${var.bucket_name}/${var.staging_log_prefix}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "review_id"
      type = "string"
    }
    columns {
      name = "model_version"
      type = "string"
    }
    columns {
      name = "model_version_no"
      type = "decimal(4,1)"
    }
    columns {
      name = "analyzed_at"
      type = "timestamp"
    }
    columns {
      name = "review_date"
      type = "date"
    }
    columns {
      name = "n_aspects"
      type = "int"
    }
  }
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
    resources = [local.staging_arn, local.staging_log_arn]
  }

  statement {
    sid       = "ReadWriteTable"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [local.table_arn, local.log_table_arn]
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
    region               = var.region
    workgroup            = aws_athena_workgroup.this.name
    database             = aws_glue_catalog_database.this.name
    table                = var.table_name
    staging_table        = var.staging_table_name
    log_table            = var.log_table_name
    staging_log_table    = var.staging_log_table_name
    staging_log_location = "s3://${var.bucket_name}/${var.staging_log_prefix}/"
    log_table_location   = "s3://${var.bucket_name}/${var.log_table_prefix}/"
    staging_location     = "s3://${var.bucket_name}/${var.staging_prefix}/"
    table_location       = "s3://${var.bucket_name}/${var.table_prefix}/"
    results_location     = "s3://${var.bucket_name}/${var.results_prefix}/"
    runner_policy_name   = aws_iam_policy.athena_runner.name
  })
}
