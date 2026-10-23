"""Prometheus 지표. 라벨에 PII·ID를 넣지 않는다(경로는 템플릿, 예: /v1/orders/{order_id})."""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class Metrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        r = self.registry
        self.requests = Counter(
            "api_requests_total", "요청 수", ["route", "method", "status"], registry=r
        )
        self.latency = Histogram(
            "api_request_seconds",
            "응답 시간(초)",
            ["route"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
            registry=r,
        )
        self.errors = Counter("api_errors_total", "오류 응답 수", ["code"], registry=r)
        self.db_pool_size = Gauge("api_db_pool_size", "DB 풀 연결 수", registry=r)
        self.db_pool_available = Gauge("api_db_pool_available", "쉬고 있는 DB 연결", registry=r)
        self.db_pool_waiting = Gauge("api_db_pool_waiting", "연결을 기다리는 요청", registry=r)
        self.kafka_produced = Counter(
            "api_kafka_produced_total", "clickstream 발행 결과", ["result"], registry=r
        )
        self.payments = Counter(
            "api_payments_total", "저장한 결제 시도", ["status", "pg"], registry=r
        )
        self.orders = Counter("api_orders_total", "새로 만든 주문", registry=r)
        self.members = Counter("api_members_total", "새로 가입한 회원", registry=r)
        self.transitions = Counter(
            "api_order_transitions_total", "주문 상태 전이", ["status"], registry=r
        )
