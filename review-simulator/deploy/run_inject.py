"""직접 쓴 리뷰 파일(CSV/JSONL)을 ECS 에서 레이크에 넣는다 = ECS 판 `rsim inject` (2026-10-18 sim/review-ecs).

    python deploy/run_inject.py --file .local/manual/size_spike_1008.csv --dry-run   # 검사만
    python deploy/run_inject.py --file .local/manual/size_spike_1008.csv             # 검사 → S3 업로드 → 실행

하는 일
  1. 이 PC 에서 rsim inject --dry-run 과 같은 검사 (한 줄이라도 틀리면 멈춤, LLM 호출 없음)
  2. 파일을 S3 sim-input/review-simulator/manual/<파일 이름> 에 올림
  3. 태스크를 한 번 실행: rsim inject --file s3://…  → 그 날짜 파티션에 part-manual-<파일 이름>.jsonl
같은 파일 이름으로 다시 넣으면 그 파일만 덮어쓴다. 형식은 data/manual_reviews.example.csv, review/inject.py 참고.
실제 쇼핑몰 리뷰를 옮겨 적은 파일은 넣지 않는다(경로에 private 가 들어가면 멈춘다).
"""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath

from aws_common import load_config, log_tail_hint, run_task, session, upload_input


def check_file(file: str) -> None:
    """로컬 검사 (rsim inject --dry-run 과 같은 코드)."""
    from rsim.review.inject import run_inject

    run_inject(file=file, sink_kind="stdout", dry_run=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--file", required=True, help="직접 쓴 리뷰 파일 (.csv/.jsonl, 이 PC 경로)")
    ap.add_argument("--dry-run", action="store_true", help="검사만 하고 올리지 않음")
    ap.add_argument("--region", default=None)
    args = ap.parse_args(argv)

    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = Path(args.file)
    if "private" in PurePosixPath(args.file.replace("\\", "/").lower()).parts:
        raise SystemExit("private 폴더의 파일은 넣을 수 없습니다 (실제 리뷰 원문 보호)")
    if not path.exists():
        raise SystemExit(f"파일이 없습니다: {path}")
    check_file(str(path))
    if args.dry_run:
        print("--dry-run: 올리거나 실행하지 않았습니다")
        return

    sess = session(args.region)
    cfg = load_config(sess)
    uri = upload_input(sess, cfg, "manual", path.name, path.read_bytes())
    arn = run_task(sess.client("ecs"), cfg, command=["inject", "--file", uri], started_by="inject")
    print(f"올림: {uri}")
    print(f"태스크 시작: {arn.rsplit('/', 1)[-1]}")
    print("로그 보기:", log_tail_hint(cfg, arn))


if __name__ == "__main__":
    main()
