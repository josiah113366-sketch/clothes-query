"""설정 모음.

모든 설정은 환경변수로 받는다. 로컬에서는 review-simulator/.env 파일에 적어 두면 되고
(.env.example 참고), ECS Fargate 에서는 태스크 정의의 environment 항목으로 같은 이름을 넣으면 된다.
그래서 코드 수정 없이 로컬 → AWS 로 옮길 수 있다.

CLI 옵션(rsim run 등)이 주어지면 CLI 값이 환경변수보다 우선한다.
상대 경로와 .env 는 **현재 작업 폴더**(review-simulator/) 기준이다. simulator/ 의 설정 방식과 같다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    # .env 파일이 있으면 읽어서 환경변수로 올린다. (python-dotenv 미설치여도 동작하도록 선택적 import)
    from dotenv import load_dotenv

    load_dotenv(Path.cwd() / ".env", override=False)
except ImportError:  # pragma: no cover - dotenv 가 없으면 OS 환경변수만 사용
    pass


def _env(name: str, default: str) -> str:
    """환경변수를 읽되, 비어 있으면 기본값을 쓴다."""
    value = os.getenv(name, "").strip()
    return value or default


def _path(name: str, default: str) -> Path:
    """경로형 환경변수. 상대 경로면 현재 작업 폴더(review-simulator/ 에서 실행한다고 가정) 기준으로 바꾼다."""
    p = Path(_env(name, default))
    return p if p.is_absolute() else Path.cwd() / p


def _path_or_s3(name: str, default: str) -> Path | str:
    """로컬 경로 또는 s3://버킷/키. S3 면 문자열 그대로 둔다(Path 로 바꾸면 s3:/ 로 깨진다).

    ECS 태스크는 PC 파일을 못 읽으므로 입력 파일(incidents JSON 등)을 S3 에 두고 경로만 넘긴다(2026-10-18 sim/review-ecs).
    """
    value = _env(name, default)
    return value if value.startswith("s3://") else _path(name, default)


@dataclass
class Settings:
    # ---------------------------------------------------------------- Bedrock
    # Bedrock 리전. 팀 결정(2026-10-08)에 따라 도쿄(ap-northeast-1)가 기본값.
    # 사용하려는 모델이 그 리전에서 열려 있어야 한다 (Bedrock 콘솔 > 모델 카탈로그에서 확인).
    aws_region: str = field(default_factory=lambda: _env("AWS_REGION", "ap-northeast-1"))
    # Bedrock API 키. 필수(--llm fake 일 때만 없어도 됨). AWS 계정 권한이 없어도 된다.
    # 키는 .env 에만 두고 저장소·노션에 올리지 않는다.
    bedrock_api_key: str = field(default_factory=lambda: _env("AWS_BEARER_TOKEN_BEDROCK", ""))
    # Bedrock 모델 ID. 2026-10-13 벤치마크(10건 x 8개 모델, 사람 평가)로 gemma-3-12b 를 기본값으로 확정.
    #  - google.gemma-3-12b-it                       : 기본값. 사람 평가 4.6/5, 1,000건당 약 $0.07 (도쿄)
    #  - jp.anthropic.claude-haiku-4-5-20251001-v1:0 : 평가 4.7/5 로 가장 높지만 약 14배 비쌈
    #  - apac.amazon.nova-lite-v1:0                  : 가장 싸고 빠르지만 짧게 쓰는 편 (평가 4.1)
    # 결과 상세: 노션 "리뷰 생성 모델 벤치마킹".
    bedrock_model_id: str = field(
        default_factory=lambda: _env("BEDROCK_MODEL_ID", "google.gemma-3-12b-it")
    )
    # 생성 온도. 높을수록 표현이 다양해지고, 너무 높으면 문장이 엉뚱해진다. 0.5~1.0 권장.
    # 벤치마크는 0.8 로 측정했다.
    bedrock_temperature: float = field(
        default_factory=lambda: float(_env("BEDROCK_TEMPERATURE", "0.8"))
    )
    # 검수 루프에서 실패한 명세(속성 누락·감성 차이)를 몇 번 다시 생성할지. 0 이면 재생성 없이 바로 버린다.
    aspect_retries: int = field(default_factory=lambda: int(_env("ASPECT_RETRIES", "1")))
    # 검수 루프(verifier.py)에서 본문을 다시 라벨링할 모델 ID. 비워 두면 생성 모델(BEDROCK_MODEL_ID)과 같은 모델을 쓴다
    verifier_model_id: str = field(default_factory=lambda: _env("VERIFIER_MODEL_ID", ""))
    # Bedrock 한 번 호출에 몇 건의 리뷰를 같이 만들지.
    # 크게 하면 호출 수(= 시스템 프롬프트·예시 토큰 반복)가 줄어 싸지지만, 한 번 실패하면 여러 건이 같이 날아간다.
    # 5~10 사이를 권장.
    batch_size: int = field(default_factory=lambda: int(_env("BATCH_SIZE", "5")))
    # 프롬프트에 넣을 말투 예시(시드) 개수. 많을수록 말투가 다양해지지만 입력 토큰이 늘어난다.
    few_shot_k: int = field(default_factory=lambda: int(_env("FEW_SHOT_K", "8")))
    # 생성 프롬프트 예시 세트 버전 (data/examples/<버전>.md, 2026-10-16 지시서 2단계).
    # 예시 칸 문장과 말투 예시 출처(seed_sources)가 함께 바뀐다. 버전별 성능은 docs/examples-scorecard.md.
    # 2026-10-18 lemin 결정: 기본값 ex-v1 (ex-v0 과 성능은 같고, 사람이 쓴 예시 + Gemini 합성 예시 제외)
    examples_version: str = field(default_factory=lambda: _env("EXAMPLES_VERSION", "ex-v1"))
    # 예시 세트 파일 폴더
    examples_dir: Path = field(default_factory=lambda: _path("EXAMPLES_DIR", "data/examples"))
    # 자동 재시도 횟수 (429 스로틀링, 5xx, 네트워크 오류에 대해 지수 백오프로 재시도)
    bedrock_max_retries: int = field(default_factory=lambda: int(_env("BEDROCK_MAX_RETRIES", "5")))

    # ---------------------------------------------------------------- Kafka
    # 호스트(윈도우)에서 실행할 때: localhost:9092
    # docker compose 안의 simulator 컨테이너로 실행할 때: kafka:29092 (docker-compose.yaml 에서 자동 설정)
    kafka_bootstrap: str = field(default_factory=lambda: _env("KAFKA_BOOTSTRAP", "localhost:9092"))
    # 리뷰 이벤트를 보낼 토픽 이름
    kafka_topic: str = field(default_factory=lambda: _env("KAFKA_TOPIC", "reviews.raw"))
    # 정답(학습·채점용) 이벤트를 보낼 토픽. 운영 흐름과 분리해서 학습 쪽만 소비한다.
    # 'none' 으로 두면 정답 이벤트를 보내지 않는다 (실제 운영처럼 리뷰만 흘릴 때).
    kafka_truth_topic: str = field(
        default_factory=lambda: _env("KAFKA_TRUTH_TOPIC", "reviews.truth")
    )
    # 토픽이 없을 때 만들면서 쓸 파티션 수. 메시지 키가 product_id 라서 같은 상품 리뷰는 같은 파티션(=순서 보장)으로 간다.
    kafka_partitions: int = field(default_factory=lambda: int(_env("KAFKA_PARTITIONS", "3")))

    # ---------------------------------------------------------------- 레이크 (--sink lake)
    # 리뷰를 날짜(dt)별로 쓰는 레이크 경로 (2026-10-14 결정: 리뷰는 S3 에 바로 쓴다).
    # 로컬 폴더 또는 s3://버킷/접두사. 팀 버킷은 s3://<버킷>/bronze_v2 로 주면 bronze_v2/reviews/year=YYYY/month=MM/day=DD/ 에 쓴다.
    # 버킷 이름은 공개 저장소에 넣지 않고 .env 에만 둔다. 기본값은 로컬 폴더(Bedrock·AWS 없이 시험).
    lake_root: str = field(default_factory=lambda: _env("LAKE_ROOT", ".local/lake"))
    # 정답(reviews_truth) 저장 경로. 운영 레이크(bronze_v2)에 정답 라벨을 섞지 않으려고 따로 둔다. 기본은 로컬.
    lake_truth_root: str = field(default_factory=lambda: _env("LAKE_TRUTH_ROOT", ".local/lake"))

    # ---------------------------------------------------------------- 데이터 파일
    # rsim seeds 가 만든 시드(말투 예시) 파일. AI Hub 원문이 들어 있어서 .local/ 에만 두고 커밋하지 않는다.
    seeds_path: Path = field(default_factory=lambda: _path("SEEDS_PATH", ".local/seeds.jsonl"))
    # 상품 목록 CSV (선택). 없으면 시드의 상품명으로 자동 생성한다. 형식은 catalog.py 참고.
    products_path: Path = field(default_factory=lambda: _path("PRODUCTS_PATH", "data/products.csv"))
    # 이상 상황(불만 급증) 시나리오 JSON (선택). 형식은 scenario.py 와 incidents.example.json 참고.
    # 로컬 경로 또는 s3://버킷/키 (ECS 에서는 deploy/run_incident.py 가 S3 에 올리고 이 값을 바꿔 실행한다)
    incidents_path: Path | str = field(
        default_factory=lambda: _path_or_s3("INCIDENTS_PATH", "data/incidents.json")
    )

    # ---------------------------------------------------------------- 주문 기반 리뷰 (rsim run --source orders)
    # 주문(결제) 파일. 결제 데이터가 S3 에 쌓이기 전까지 쓰는 로컬 입력이다(review/orders.py 참고).
    # rsim orders-fake 가 만든 가짜 주문을 기본으로 읽는다. 회원 ID 가 들어 있어서 .local/ 에만 둔다.
    orders_path: Path = field(default_factory=lambda: _path("ORDERS_PATH", ".local/orders.jsonl"))
    # RDS 접속 주소 (rsim run --source rds 에서 orders·order_items·payments·상품·회원 테이블을 읽는다, 2026-10-21).
    # 형식: postgresql://사용자:비밀번호@호스트:5432/DB이름. 비밀번호가 들어 있으므로 .env 또는 ECS Secret 에만 둔다.
    # 읽기만 하므로 SELECT 권한만 있는 계정을 쓰면 된다. 로컬에서는 kubectl port-forward 로 localhost 를 줘도 된다.
    orders_database_url: str = field(default_factory=lambda: _env("ORDERS_DATABASE_URL", ""))
    # 주문 중 리뷰를 쓰는 비율 (0~1). 1.0 = 모든 주문에 리뷰. 실제 쇼핑몰 리뷰 작성률에 맞춰 낮추면 된다.
    # 하루 리뷰 수 ≈ 하루 주문 수 x 이 값. 값을 바꾸면 "어느 주문에 리뷰가 달리는지"도 바뀐다.
    review_rate: float = field(default_factory=lambda: float(_env("REVIEW_RATE", "1.0")))
    # 결제 후 리뷰까지 걸리는 기간(일). 주문마다 이 사이에서 고르게 정해진다.
    # 2026-10-14 구상은 1~14일이었으나 2026-10-21 lemin 결정으로 0~7일로 바꿈(프로젝트 기간이 짧아서 7일로 좁히고, 결제 당일 리뷰도 나오게 최소 0일).
    # 늘리면 결제 후 리뷰가 늦게 달려 첫 리뷰가 쌓이기까지 더 오래 걸린다.
    review_delay_min_days: float = field(
        default_factory=lambda: float(_env("REVIEW_DELAY_MIN_DAYS", "0"))
    )
    review_delay_max_days: float = field(
        default_factory=lambda: float(_env("REVIEW_DELAY_MAX_DAYS", "7"))
    )

    # ---------------------------------------------------------------- 시뮬레이션
    # 난수 시드. 같은 값이면 같은 명세(상품·별점·속성)와 ID 가 같은 순서로 나온다(LLM 문장은 매번 다를 수 있음).
    # 비워 두면 실행마다 새로 만들고 로그에 남긴다(common/rng.resolve_seed).
    random_seed: int | None = field(
        default_factory=lambda: int(v) if (v := os.getenv("RANDOM_SEED", "").strip()) else None
    )


def load_settings() -> Settings:
    """환경변수 기준 설정 객체를 만든다."""
    return Settings()
