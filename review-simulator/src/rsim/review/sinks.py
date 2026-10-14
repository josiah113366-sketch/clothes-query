"""리뷰 이벤트를 내보내는 곳(sink).

- KafkaSink  : Kafka 토픽으로 전송 (운영 흐름)
- StdoutSink : 콘솔에 JSON 한 줄씩 출력 (눈으로 확인)
- JsonlSink  : 파일에 JSON Lines 로 저장 (평가셋/재현용으로 보관)
- PostgresSink : PostgreSQL reviews 테이블에 저장 (2026-10-14 구상: RDS → CDC → Kafka → S3).
                 지금은 로컬 Postgres(simulator/docker-compose.yml), 나중에 DATABASE_URL 만 RDS 로 바꾼다.

모든 sink 는 send(review, truth) / close() / reviewed_order_ids() 세 메서드를 가진다.
  reviewed_order_ids : 이미 리뷰를 보낸 order_id 모음. 주문 모드(--source orders)가
                       같은 주문에 리뷰를 두 번 달지 않으려고 쓴다. 알 수 없는 전송처는 빈 집합.
  review : 실제 쇼핑몰 리뷰와 같은 모양의 이벤트 → 운영 흐름(리뷰 토픽)
  truth  : 정답 라벨이 든 학습·채점용 이벤트 → 별도 흐름(정답 토픽)
새 목적지(S3, Kinesis 등)가 필요하면 같은 모양의 클래스를 하나 더 만들고
run.py 의 make_sink() 에 등록하면 된다.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def _dumps(event: dict) -> str:
    # ensure_ascii=False: 한글을 \uXXXX 로 바꾸지 않고 그대로 보냄 (Kafka UI 에서 바로 읽힘)
    return json.dumps(event, ensure_ascii=False, default=str)


class StdoutSink:
    """콘솔 출력. 두 흐름을 구분할 수 있게 줄 앞에 [review] / [truth] 를 붙인다."""

    def reviewed_order_ids(self) -> set[str]:
        # 콘솔은 보낸 기록이 남지 않으므로, 주문 모드에서는 매번 차례가 된 주문 전부를 다시 출력한다
        return set()

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
        self.review_path = review_path
        # 실행 내내 열어 두고 close() 에서 닫는다(배치마다 열고 닫지 않게)
        self.review_fh = open(review_path, "a", encoding="utf-8")  # noqa: SIM115
        self.truth_fh = open(truth_path, "a", encoding="utf-8")  # noqa: SIM115

    def reviewed_order_ids(self) -> set[str]:
        """리뷰 파일에 이미 있는 order_id. 파일을 이어 쓰므로(append) 지난 실행 결과도 포함된다.

        로컬 단계의 "아직 리뷰가 없는 주문" 판단 기준이다. 나중에 RDS 로 가면 reviews 테이블 조회로 바뀐다.
        """
        self.review_fh.flush()
        ids = set()
        for line in self.review_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                order_id = json.loads(line).get("order_id")
                if order_id:
                    ids.add(order_id)
        return ids

    def send(self, review: dict, truth: dict) -> None:
        self.review_fh.write(_dumps(review) + "\n")
        self.truth_fh.write(_dumps(truth) + "\n")

    def close(self) -> None:
        self.review_fh.close()
        self.truth_fh.close()


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

    def reviewed_order_ids(self) -> set[str]:
        # 토픽을 처음부터 다시 읽지 않는 한 알 수 없다. 주문 모드에서는 jsonl 전송처를 쓴다
        log.warning("Kafka 전송처는 이미 보낸 주문을 알 수 없어서, 차례가 된 주문을 전부 보냅니다")
        return set()

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


class PostgresSink:
    """PostgreSQL reviews 테이블(db/schema/003_review.sql)에 리뷰를 넣는다.

    - 리뷰 이벤트만 DB 에 넣는다. 정답 이벤트는 실제 쇼핑몰에 없는 값이라 truth_path 파일(JSONL)에 따로 쓴다.
    - 이벤트 칸 → 테이블 칸: created_at → written_at(리뷰 작성 시각), text → body.
      테이블의 created_at 은 DB 기본값(now())이 채운다. schema_version·event_id·event_type 은 이벤트 전송용이라 넣지 않는다
      (CDC 가 변경 이벤트를 따로 만든다).
    - 같은 review_id 나 같은 order_id 가 이미 있으면 넣지 않는다(ON CONFLICT DO NOTHING). 이때 정답도 쓰지 않는다.
    - 한 건마다 커밋한다(하루 약 1,000건이라 충분). 중간에 멈춰도 넣은 리뷰는 남고, 남은 주문은 다음 실행에서 골라진다.
    - DB 오류 메시지에는 행 내용이 들어갈 수 있어서 오류 종류·sqlstate·제약 이름만 남긴다(simulator/ 와 같은 방식).
    """

    INSERT_SQL = """
        INSERT INTO reviews (
            review_id, order_id, member_id, product_id, product_name, category,
            age_group, rating, body, source, written_at
        ) VALUES (
            %(review_id)s, %(order_id)s, %(member_id)s, %(product_id)s, %(product_name)s,
            %(category)s, %(age_group)s, %(rating)s, %(text)s, %(source)s, %(created_at)s
        )
        ON CONFLICT DO NOTHING
        RETURNING review_id
    """

    def __init__(self, database_url: str, truth_path: Path | None):
        import psycopg

        self._psycopg = psycopg
        if not database_url:
            raise SystemExit(
                "DATABASE_URL 이 비어 있습니다. .env 에 로컬 Postgres 주소를 넣으세요 "
                "(예는 .env.example)."
            )
        try:
            # autocommit: INSERT 한 건마다 바로 반영 (위 설명의 "한 건마다 커밋")
            self.conn = psycopg.connect(database_url, autocommit=True)
        except psycopg.Error as e:
            raise SystemExit(
                f"Postgres 에 접속하지 못했습니다 ({_describe_db_error(e)}). "
                "simulator/ 폴더에서 docker compose up -d 로 postgres 가 떠 있는지 확인하세요."
            ) from None
        self.truth_fh = None
        if truth_path is not None:
            truth_path.parent.mkdir(parents=True, exist_ok=True)
            self.truth_fh = open(truth_path, "a", encoding="utf-8")  # noqa: SIM115
        self.inserted = self.duplicated = 0

    def reviewed_order_ids(self) -> set[str]:
        """이미 리뷰가 있는 주문. RDS 로 옮겨도 같은 조회를 쓴다."""
        with self._safe():
            rows = self.conn.execute(
                "SELECT order_id FROM reviews WHERE order_id IS NOT NULL"
            ).fetchall()
        return {r[0] for r in rows}

    def send(self, review: dict, truth: dict) -> None:
        with self._safe():
            row = self.conn.execute(self.INSERT_SQL, review).fetchone()
        if row is None:
            # 같은 review_id 또는 같은 order_id 가 이미 있음 → 넣지 않음
            self.duplicated += 1
            return
        self.inserted += 1
        if self.truth_fh:
            self.truth_fh.write(_dumps(truth) + "\n")

    def close(self) -> None:
        self.conn.close()
        if self.truth_fh:
            self.truth_fh.close()
        log.info(
            "Postgres 저장 완료: 리뷰 %d건, 중복으로 건너뜀 %d건", self.inserted, self.duplicated
        )

    def _safe(self):
        """psycopg 오류를 행 내용 없는 메시지로 바꿔서 다시 던진다."""
        from contextlib import contextmanager

        psycopg = self._psycopg

        @contextmanager
        def _cm():
            try:
                yield
            except psycopg.Error as e:
                raise RuntimeError(f"Postgres 오류: {_describe_db_error(e)}") from None

        return _cm()


def _describe_db_error(error) -> str:
    """오류 종류, sqlstate, 제약 이름만 돌려준다. str(error) 에는 행 내용이 들어갈 수 있어서 쓰지 않는다."""
    parts = [type(error).__name__, f"sqlstate={getattr(error, 'sqlstate', None)}"]
    diag = getattr(error, "diag", None)
    constraint = getattr(diag, "constraint_name", None) if diag else None
    if constraint:
        parts.append(f"constraint={constraint}")
    return " ".join(parts)
