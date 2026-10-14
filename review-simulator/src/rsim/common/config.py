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

    # ---------------------------------------------------------------- 데이터 파일
    # rsim seeds 가 만든 시드(말투 예시) 파일. AI Hub 원문이 들어 있어서 .local/ 에만 두고 커밋하지 않는다.
    seeds_path: Path = field(default_factory=lambda: _path("SEEDS_PATH", ".local/seeds.jsonl"))
    # 상품 목록 CSV (선택). 없으면 시드의 상품명으로 자동 생성한다. 형식은 catalog.py 참고.
    products_path: Path = field(default_factory=lambda: _path("PRODUCTS_PATH", "data/products.csv"))
    # 이상 상황(불만 급증) 시나리오 JSON (선택). 형식은 scenario.py 와 incidents.example.json 참고.
    incidents_path: Path = field(
        default_factory=lambda: _path("INCIDENTS_PATH", "data/incidents.json")
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
