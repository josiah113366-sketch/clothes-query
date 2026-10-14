"""리뷰 이벤트를 내보내는 곳(sink).

- KafkaSink  : Kafka 토픽으로 전송 (운영 흐름)
- StdoutSink : 콘솔에 JSON 한 줄씩 출력 (눈으로 확인)
- JsonlSink  : 파일에 JSON Lines 로 저장 (평가셋/재현용으로 보관)

모든 sink 는 send(review, truth) / close() 두 메서드만 가진다.
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
