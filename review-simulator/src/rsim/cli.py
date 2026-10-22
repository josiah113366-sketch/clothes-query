"""rsim 명령 진입점 (typer).

review-simulator/ 폴더에서 실행한다. 상대 경로(.env, .local/, data/)는 모두 현재 폴더 기준이다.

  rsim run ...          리뷰를 만들어 Kafka / 콘솔 / 파일로 보낸다 (review/run.py)
  rsim orders-fake ...  주문 기반 실행용 가짜 주문 파일 만들기 (review/orders.py)
  rsim inject ...       직접 작성한 리뷰(CSV/JSONL)를 레이크에 넣기 (review/inject.py, LLM 호출 없음)
  rsim seeds ...        말투 예시(시드) 파일 .local/seeds.jsonl 만들기 (seeds_prep.py)
  rsim bench ...        소량 실행으로 비용·검수 결과 확인 (bench/bench.py, Kafka 로 안 보냄)
  rsim scorecard        bench 결과를 예시 세트 점검표로 출력 (bench/scorecard.py, 호출 없음)
  rsim verify-eval ...  검수 모델 정확도 측정 (bench/verify_eval.py)
  rsim version          버전 출력

Bedrock 을 실제로 부르는 명령(run --llm bedrock, bench --yes, verify-eval --yes)은 비용이 든다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import typer

from rsim import __version__

app = typer.Typer(help="clothes-query 리뷰 시뮬레이터", no_args_is_help=True)


class Llm(str, Enum):
    bedrock = "bedrock"  # Bedrock(gemma)으로 생성 + 검수
    fake = "fake"  # 규칙 기반 가짜 문장 (비용 0원, 배관 확인용)


class Source(str, Enum):
    random = "random"  # 가상 시계 + 무작위 상품 (예전 방식)
    rds = "rds"  # RDS orders 테이블에서 결제 후 0~7일(당일 포함) 주문 항목에 리뷰 (2026-10-21 lemin 결정)
    orders = "orders"  # 주문 파일에서 결제 후 0~7일(당일 포함) 주문에 리뷰 (2026-10-14 구상, 2026-10-21 에 1~14일 → 0~7일)


class SinkKind(str, Enum):
    kafka = "kafka"
    stdout = "stdout"
    jsonl = "jsonl"
    lake = "lake"  # S3 레이크 경로 구조 (LAKE_ROOT, dt 별 파티션 덮어쓰기)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.callback()
def main() -> None:
    """clothes-query 리뷰 시뮬레이터."""


@app.command()
def version() -> None:
    """버전을 출력한다."""
    typer.echo(__version__)


@app.command()
def run(
    llm: Annotated[
        Llm, typer.Option(help="bedrock: Bedrock(gemma)으로 생성 / fake: 가짜 문장(0원)")
    ] = Llm.bedrock,
    sink: Annotated[SinkKind, typer.Option(help="결과를 보낼 곳")] = SinkKind.stdout,
    source: Annotated[
        Source,
        typer.Option(
            help="random: 무작위 상품 / orders: 주문 파일 기반 / rds: RDS orders 테이블 기반"
            " (orders·rds 는 결제 후 0~7일, 날짜별)"
        ),
    ] = Source.random,
    count: Annotated[
        int | None,
        typer.Option(
            help="만들 리뷰 수. random 기본 10(0 이면 멈출 때까지), orders·rds 기본 0(그날 주문 전부)"
        ),
    ] = None,
    max_rps: Annotated[float, typer.Option(help="초당 전송 상한. 0 이면 제한 없음")] = 0.0,
    start: Annotated[
        datetime | None,
        typer.Option(
            formats=["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"],
            help="가상 시계 시작 시각 (예: 2026-10-10T00:00:00+09:00). 없으면 현재 시각",
        ),
    ] = None,
    reviews_per_hour: Annotated[
        float, typer.Option(help="--start 를 줬을 때 가상 시간당 평균 리뷰 수")
    ] = 20.0,
    out: Annotated[
        Path,
        typer.Option(help="--sink jsonl 저장 파일 (정답은 같은 폴더 *_truth.jsonl)"),
    ] = Path(".local/out/reviews.jsonl"),
    batch_size: Annotated[
        int | None, typer.Option(help="Bedrock 호출당 리뷰 수 (기본: .env 의 BATCH_SIZE)")
    ] = None,
    orders: Annotated[
        Path | None, typer.Option(help="--source orders 주문 파일 (기본: .env 의 ORDERS_PATH)")
    ] = None,
    date: Annotated[
        datetime | None,
        typer.Option(
            formats=["%Y-%m-%d"],
            help="--source orders·rds 날짜(UTC, 예: 2026-10-08). 그날 리뷰 시각인 주문만. 없으면 어제",
        ),
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="디버그 로그 출력")] = False,
) -> None:
    """리뷰를 만들어 Kafka / 콘솔 / 파일로 보낸다."""
    from rsim.review.run import run as run_reviews  # 무거운 import 는 명령을 실행할 때만

    _setup_logging(verbose)
    run_reviews(
        llm=llm.value,
        sink_kind=sink.value,
        source=source.value,
        count=count,
        max_rps=max_rps,
        start=start,
        reviews_per_hour=reviews_per_hour,
        out=out,
        batch_size=batch_size,
        orders_path=orders,
        day=date.date() if date else None,
    )


@app.command("orders-fake")
def orders_fake(
    start: Annotated[
        datetime,
        typer.Option(
            formats=["%Y-%m-%dT%H:%M:%S%z"],
            help="첫 결제 시각 (시간대 필수, 예: 2026-10-01T00:00:00+09:00)",
        ),
    ],
    days: Annotated[int, typer.Option(help="며칠치 주문을 만들지")] = 14,
    per_day: Annotated[float, typer.Option(help="하루 평균 주문 수")] = 1000.0,
    out: Annotated[
        Path | None, typer.Option(help="주문 파일 (기본: .env 의 ORDERS_PATH). 덮어쓴다")
    ] = None,
    seed: Annotated[int, typer.Option(help="주문 난수 시드 (같으면 같은 주문)")] = 42,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="디버그 로그 출력")] = False,
) -> None:
    """결제 시뮬레이터가 생기기 전까지 쓰는 가짜 주문 파일을 만든다 (Bedrock 호출 없음)."""
    from rsim.review.orders import run_orders_fake

    _setup_logging(verbose)
    run_orders_fake(out=out, start=start, days=days, per_day=per_day, seed=seed)


class InjectSink(str, Enum):
    lake = "lake"  # LAKE_ROOT 의 날짜 파티션에 part-manual-<입력 파일 이름>.jsonl 로 쓴다
    stdout = "stdout"  # 콘솔에만 출력 (눈으로 확인)


@app.command()
def inject(
    file: Annotated[
        str,
        typer.Option(
            "--file",
            help="직접 작성한 리뷰 파일 (.csv/.jsonl). 로컬 경로 또는 s3://버킷/키 (ECS 에서는 S3)",
        ),
    ],
    sink: Annotated[InjectSink, typer.Option(help="결과를 보낼 곳")] = InjectSink.lake,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="검사만 하고 쓰지 않는다 (형식 확인용)")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="디버그 로그 출력")] = False,
) -> None:
    """직접 작성한 테스트 리뷰를 레이크에 넣는다. 형식은 data/manual_reviews.example.csv 참고.

    매일 도는 리뷰(part-00000)와 같은 날짜 파티션에 다른 파일로 쓰므로 서로 지우지 않는다.
    같은 파일을 다시 넣으면 그 파일만 덮어쓴다. 실제 쇼핑몰 리뷰 원문은 넣지 않는다.
    """
    from rsim.review.inject import run_inject

    _setup_logging(verbose)
    run_inject(file=file, sink_kind=sink.value, dry_run=dry_run)


@app.command()
def seeds(
    analysis_dir: Annotated[
        Path, typer.Option(help="review-analysis 폴더 (합성 리뷰, AI Hub 데이터 위치)")
    ] = Path("../../review-analysis"),
    handwritten_dir: Annotated[Path, typer.Option(help="직접 작성한 리뷰 CSV 폴더")] = Path(
        ".local/handwritten"
    ),
    aihub_per_category: Annotated[
        int, typer.Option(help="AI Hub 에서 카테고리별로 뽑을 리뷰 수")
    ] = 1000,
    max_len: Annotated[int, typer.Option(help="이보다 긴 AI Hub 리뷰는 제외(글자 수)")] = 200,
    out: Annotated[Path, typer.Option(help="결과 파일 (커밋 금지 폴더 .local/)")] = Path(
        ".local/seeds.jsonl"
    ),
    seed: Annotated[int, typer.Option(help="표본 추출 난수 시드(같으면 같은 결과)")] = 42,
) -> None:
    """말투 예시(시드) 파일을 만든다. review-analysis/private 경로는 어떤 경우에도 읽지 않는다."""
    from rsim.seeds_prep import build_seeds

    build_seeds(SimpleNamespace(**locals()))


@app.command()
def bench(
    n: Annotated[int, typer.Option(help="명세(리뷰) 건수")] = 10,
    batch_size: Annotated[int, typer.Option(help="호출당 건수")] = 5,
    models: Annotated[
        list[str] | None,
        typer.Option("--models", help="생성 모델 ID (여러 번 쓰면 모델마다 생성). 기본 = .env"),
    ] = None,
    seed: Annotated[int, typer.Option(help="명세·예시 고정용 난수 시드")] = 42,
    region: Annotated[
        str | None, typer.Option(help="Bedrock 리전. 기본 = .env 의 AWS_REGION")
    ] = None,
    max_calls: Annotated[
        int, typer.Option(help="안전장치: 1차 생성 호출이 이보다 많으면 중단")
    ] = 20,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="호출하지 않고 계획만 출력")] = False,
    yes: Annotated[
        bool, typer.Option("--yes", help="실제 Bedrock 호출 허용 (없으면 호출 안 함)")
    ] = False,
    verifier_model: Annotated[
        str | None, typer.Option(help="검수 모델 ID. 기본 = 생성 모델")
    ] = None,
    aspect_retries: Annotated[int, typer.Option(help="검수 실패 리뷰 재생성 횟수")] = 1,
    examples: Annotated[
        str | None,
        typer.Option(
            help="예시 세트 버전 (data/examples/<버전>.md). 기본 = .env 의 EXAMPLES_VERSION"
        ),
    ] = None,
) -> None:
    """소량 실행으로 비용·검수 결과를 확인한다. 결과는 .local/bench/<시각>/ (Kafka 로는 안 보냄)."""
    from rsim.bench.bench import run_bench

    run_bench(SimpleNamespace(**locals()))


@app.command()
def scorecard(
    bench_dir: Annotated[Path, typer.Option(help="bench 결과 폴더")] = Path(".local/bench"),
) -> None:
    """bench 실행들을 예시 세트 점검표(마크다운 표)로 출력한다. docs/examples-scorecard.md 에 붙인다."""
    from rsim.bench.scorecard import run_scorecard

    run_scorecard(bench_dir)


@app.command("verify-eval")
def verify_eval(
    region: Annotated[str, typer.Option(help="Bedrock 리전")] = "ap-northeast-1",
    verifier_model: Annotated[str, typer.Option(help="검수 모델 ID")] = "google.gemma-3-12b-it",
    gold: Annotated[Path, typer.Option(help="사람 채점 파일")] = Path(
        ".local/bench/verify_gold.json"
    ),
    yes: Annotated[
        bool, typer.Option("--yes", help="실제 Bedrock 호출 허용 (없으면 건수만 출력)")
    ] = False,
) -> None:
    """검수 모델이 사람 채점(O/X)과 얼마나 맞는지 잰다."""
    from rsim.bench.verify_eval import run_verify_eval

    run_verify_eval(SimpleNamespace(**locals()))
