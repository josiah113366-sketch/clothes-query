"""리뷰 이벤트를 내보내는 곳(sink).

- KafkaSink  : Kafka 토픽으로 전송 (운영 흐름)
- StdoutSink : 콘솔에 JSON 한 줄씩 출력 (눈으로 확인)
- JsonlSink  : 파일에 JSON Lines 로 저장 (평가셋/재현용으로 보관)
- LakeSink   : S3 레이크 경로 구조(dt 별 파티션)로 저장 (2026-10-14 결정: 리뷰는 S3 에 바로 쓴다).
               지금은 로컬 폴더(.local/lake), 나중에 s3:// 경로를 지원한다.

모든 sink 는 send(review, truth) / close() 두 메서드만 가진다.
  review : 실제 쇼핑몰 리뷰와 같은 모양의 이벤트 → 운영 흐름(리뷰 토픽)
  truth  : 정답 라벨이 든 학습·채점용 이벤트 → 별도 흐름(정답 토픽)
새 목적지(S3, Kinesis 등)가 필요하면 같은 모양의 클래스를 하나 더 만들고
run.py 의 make_sink() 에 등록하면 된다.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)


def _dumps(event: dict) -> str:
    # ensure_ascii=False: 한글을 \uXXXX 로 바꾸지 않고 그대로 보냄 (Kafka UI 에서 바로 읽힘)
    return json.dumps(event, ensure_ascii=False, default=str)


class StdoutSink:
    """콘솔 출력. 두 흐름을 구분할 수 있게 줄 앞에 [review] / [truth] 를 붙인다."""

    def send(self, review: dict, truth: dict) -> None:
        sys.stdout.write("[review] " + _dumps(review) + "\n")
        sys.stdout.write("[truth]  " + _dumps(truth) + "\n")
        sys.stdout.flush()

    def close(self) -> None:
        pass


class JsonlSink:
    """파일 저장. 리뷰와 정답을 서로 다른 파일에 쓴다."""

    def __init__(self, review_path: Path, truth_path: Path):
        review_path.parent.mkdir(parents=True, exist_ok=True)
        # 실행 내내 열어 두고 close() 에서 닫는다(배치마다 열고 닫지 않게)
        self.review_fh = open(review_path, "a", encoding="utf-8")  # noqa: SIM115
        self.truth_fh = open(truth_path, "a", encoding="utf-8")  # noqa: SIM115

    def send(self, review: dict, truth: dict) -> None:
        self.review_fh.write(_dumps(review) + "\n")
        self.truth_fh.write(_dumps(truth) + "\n")

    def close(self) -> None:
        self.review_fh.close()
        self.truth_fh.close()


class LakeSink:
    """S3 레이크 경로 구조로 저장한다. 날짜 파티션(year/month/day) 하나 = 파일 하나.

      <root>/reviews/year=2026/month=10/day=08/part-00000.jsonl              리뷰 (실제 쇼핑몰 리뷰 모양, 정답 없음)
      <truth_root>/reviews_truth/year=2026/month=10/day=08/part-00000.jsonl  정답 (학습·채점용, 운영 흐름과 분리)

    예) LAKE_ROOT=s3://<버킷>/bronze
        → s3://<버킷>/bronze/reviews/year=2026/month=10/day=08/part-00000.jsonl (버킷 이름은 .env 에만)
        파티션 이름은 Hive 형식 year=YYYY/month=MM/day=DD (2026-10-16 lemin 결정, 이전 dt=YYYY-MM-DD 대체).
        Glue 크롤러·Athena 가 year, month, day 를 파티션 컬럼으로 바로 인식한다. 월·일은 두 자리(01~12, 01~31).
        LAKE_TRUTH_ROOT 기본값은 로컬 .local/lake 다. 정답 라벨은 실제 운영 데이터에 없는 값이라
        운영 레이크(bronze)에 섞지 않는다. 정답도 S3 에 두려면 bronze 가 아닌 별도 경로를 준다.

    - root 는 로컬 폴더 또는 s3://버킷/접두사. S3 는 boto3 의 기본 자격 증명(aws configure sso, 환경변수,
      ECS 태스크 역할 등)을 쓴다. Bedrock API 키와는 별개다.
    - dt 는 리뷰 작성 시각(created_at)을 **UTC 로 바꾼 날짜**다. 팀 규칙(Bronze 는 UTC, Silver 부터 KST)에 맞춘다.
    - close() 에서 이번 실행이 만든 dt 파티션 파일을 **통째로 덮어쓴다**.
      (로컬: 임시 파일에 쓴 뒤 이름 바꾸기, S3: 같은 키로 put_object = 객체 전체 교체)
      주문 모드는 날짜 하나를 돌리므로, 같은 날짜를 다시 돌려도 주문당 리뷰가 하나만 남는다.
      무작위 모드로 같은 날짜에 다시 쓰면 그 날짜의 예전 리뷰가 지워지니 주의한다.
    - 하루 약 1,000건이라 메모리에 모았다가 한 번에 쓴다.
    """

    FILE_NAME = "part-00000.jsonl"

    def __init__(self, root: str, truth_root: str, region: str | None = None):
        self.root = root.rstrip("/")
        self.truth_root = truth_root.rstrip("/")
        self.region = region
        self._s3 = None  # S3 클라이언트는 처음 쓸 때 만든다 (로컬만 쓸 때 boto3 가 없어도 되게)
        # dt → (리뷰 줄 목록, 정답 줄 목록)
        self.parts: dict[str, tuple[list[str], list[str]]] = {}

    @staticmethod
    def dt_of(review: dict) -> str:
        """리뷰 작성 시각의 UTC 날짜 (예: 2026-10-08). 시각에 시간대가 없으면 UTC 로 본다."""
        t = datetime.fromisoformat(review["created_at"])
        if t.tzinfo is None:
            t = t.replace(tzinfo=UTC)
        return t.astimezone(UTC).date().isoformat()

    @staticmethod
    def partition(dt: str) -> str:
        """UTC 날짜(2026-10-08) → 파티션 폴더 이름(year=2026/month=10/day=08).

        파티션 모양을 바꾸려면 이 함수만 고치면 된다(경로·로그·테스트가 모두 이 함수를 쓴다).
        """
        y, m, d = dt.split("-")
        return f"year={y}/month={m}/day={d}"

    def path(self, table: str, dt: str) -> str:
        """파티션 파일 위치 (로컬 경로 또는 s3:// URI)."""
        root = self.truth_root if table == "reviews_truth" else self.root
        return f"{root}/{table}/{self.partition(dt)}/{self.FILE_NAME}"

    def send(self, review: dict, truth: dict) -> None:
        reviews, truths = self.parts.setdefault(self.dt_of(review), ([], []))
        reviews.append(_dumps(review))
        truths.append(_dumps(truth))

    def close(self) -> None:
        for dt, (reviews, truths) in sorted(self.parts.items()):
            for table, lines in (("reviews", reviews), ("reviews_truth", truths)):
                self._write(self.path(table, dt), "\n".join(lines) + "\n")
            log.info("저장: %s(UTC) 리뷰 %d건 → %s", dt, len(reviews), self.path("reviews", dt))

    def _write(self, target: str, body: str) -> None:
        if target.startswith("s3://"):
            bucket, _, key = target[len("s3://") :].partition("/")
            self._client().put_object(
                Bucket=bucket,
                Key=key,
                Body=body.encode("utf-8"),
                ContentType="application/x-ndjson",
            )
            return
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(path)  # 덮어쓰기 (쓰다가 멈춰도 예전 파일이 깨지지 않게)

    def _client(self):
        if self._s3 is None:
            try:
                import boto3
            except ImportError:
                raise SystemExit("S3 에 쓰려면 boto3 가 필요합니다: pip install -e .") from None
            # .env 에 AWS_PROFILE= 처럼 빈 값이 있으면 boto3 가 이름 없는 프로필을 찾다가
            # ProfileNotFound 로 멈춘다. 빈 값이면 지워서 기본 자격 증명(aws login/sso 의 default)을 쓰게 한다.
            for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
                if name in os.environ and not os.environ[name].strip():
                    del os.environ[name]
            self._s3 = boto3.client("s3", region_name=self.region)
        return self._s3


class KafkaSink:
    """confluent-kafka 프로듀서. 두 토픽으로 나눠 보낸다.

    리뷰 토픽 (기본 reviews.raw)
      메시지 키 = product_id
      → 같은 상품의 리뷰는 항상 같은 파티션으로 가서 순서가 지켜지고,
        컨슈머가 상품 단위로 집계(이상탐지)하기 쉬워진다.
    정답 토픽 (기본 reviews.truth, 'none' 이면 전송 안 함)
      메시지 키 = review_id
      → 학습·채점 쪽이 리뷰 토픽과 review_id 로 이어 붙이거나, 이 토픽만으로 학습 데이터를 쌓는다.
    """

    def __init__(self, bootstrap: str, topic: str, truth_topic: str, partitions: int):
        from confluent_kafka import KafkaException, Producer
        from confluent_kafka.admin import AdminClient, NewTopic

        self.topic = topic
        self.truth_topic = None if truth_topic.lower() == "none" else truth_topic
        self.sent = {"review": 0, "truth": 0}
        self.failed = 0

        # 토픽이 없으면 만든다. (브로커의 자동 생성 기능에 기대지 않고 파티션 수를 직접 정하기 위해)
        admin = AdminClient({"bootstrap.servers": bootstrap})
        try:
            existing = admin.list_topics(timeout=10).topics
        except KafkaException as e:
            raise SystemExit(
                f"Kafka({bootstrap})에 접속하지 못했습니다: {e}\n"
                "docker compose 로 kafka 가 떠 있는지, KAFKA_BOOTSTRAP 값이 맞는지 확인하세요."
            )
        wanted = [t for t in (self.topic, self.truth_topic) if t and t not in existing]
        if wanted:
            futures = admin.create_topics(
                [NewTopic(t, num_partitions=partitions, replication_factor=1) for t in wanted]
            )
            for t, f in futures.items():
                f.result()
                log.info("토픽 생성: %s (파티션 %d)", t, partitions)

        self.producer = Producer(
            {
                "bootstrap.servers": bootstrap,
                # 브로커가 받았다고 확인해야 성공으로 친다 + 재시도 시 중복 전송 방지
                "acks": "all",
                "enable.idempotence": True,
                # 최대 50ms 모아서 한 번에 보냄 (처리량↑, 지연 약간↑)
                "linger.ms": 50,
                "compression.type": "lz4",
            }
        )

    def _callback(self, kind: str):
        """브로커 전송 결과 콜백을 만든다. 실패하면 로그만 남기고 계속 진행한다."""

        def _on_delivery(err, msg) -> None:
            if err is not None:
                self.failed += 1
                log.error("Kafka 전송 실패(%s): %s", kind, err)
            else:
                self.sent[kind] += 1

        return _on_delivery

    def send(self, review: dict, truth: dict) -> None:
        self.producer.produce(
            self.topic,
            key=review["product_id"].encode("utf-8"),
            value=_dumps(review).encode("utf-8"),
            # 헤더: 컨슈머가 본문을 열지 않고도 스키마 버전을 확인할 수 있게
            headers={"schema": review["schema_version"]},
            on_delivery=self._callback("review"),
        )
        if self.truth_topic:
            self.producer.produce(
                self.truth_topic,
                key=truth["review_id"].encode("utf-8"),
                value=_dumps(truth).encode("utf-8"),
                headers={"schema": truth["schema_version"]},
                on_delivery=self._callback("truth"),
            )
        # 쌓인 전송 결과 콜백을 처리 (블로킹하지 않음)
        self.producer.poll(0)

    def close(self) -> None:
        # 남은 메시지를 모두 보낼 때까지 최대 30초 대기
        remaining = self.producer.flush(30)
        if remaining:
            log.error("전송하지 못한 메시지 %d건", remaining)
        log.info(
            "Kafka 전송 완료: 리뷰 %d건, 정답 %d건, 실패 %d건",
            self.sent["review"],
            self.sent["truth"],
            self.failed,
        )
