"""앱 조립. `uvicorn clothes_api.main:app`으로 띄우면 환경 변수로 DB 풀과 Kafka 프로듀서를 만든다.

테스트는 create_app(store=…, publisher=…)로 가짜를 넣는다.
요청 로그는 stdout JSON 한 줄이며 본문·쿼리 값·PII를 남기지 않는다.
"""

import json
import logging
import sys
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from clothes_api.config import load_settings
from clothes_api.errors import install_handlers
from clothes_api.kafka import ClickPublisher, KafkaClickPublisher
from clothes_api.metrics import Metrics
from clothes_api.routes import events, health, members, orders
from clothes_api.store import Store

log = logging.getLogger("clothes_api.access")


def _setup_logging(level: str) -> None:
    if not log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(handler)
    log.setLevel(level)
    log.propagate = False


def create_app(
    store: Store | None = None,
    publisher: ClickPublisher | None = None,
    metrics: Metrics | None = None,
) -> FastAPI:
    metrics = metrics or Metrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = None
        if store is None or publisher is None:
            from psycopg_pool import ConnectionPool

            from clothes_api.store import PgStore

            settings = load_settings()
            _setup_logging(settings.log_level)
            pool = ConnectionPool(
                settings.database_url,
                min_size=settings.pool_min,
                max_size=settings.pool_max,
                open=False,
                name="api",
            )
            pool.open(wait=False)  # DB가 늦게 떠도 프로세스는 뜬다(/readyz가 503)
            app.state.pool = pool
            app.state.store = store or PgStore(pool, settings.pool_timeout_seconds)
            app.state.publisher = publisher or KafkaClickPublisher(
                settings.kafka, settings.click_topic, metrics
            )
        else:
            _setup_logging("INFO")
            app.state.pool = None
            app.state.store = store
            app.state.publisher = publisher
        try:
            yield
        finally:
            app.state.publisher.close()
            if pool is not None:
                pool.close()

    app = FastAPI(title="clothes-query API", version="0.1.0", lifespan=lifespan)
    app.state.metrics = metrics
    install_handlers(app)
    for router in (health.router, members.router, orders.router, events.router):
        app.include_router(router)

    @app.middleware("http")
    async def access_log(request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        route = getattr(request.scope.get("route"), "path", "unmatched")
        metrics.requests.labels(route, request.method, str(response.status_code)).inc()
        metrics.latency.labels(route).observe(elapsed)
        response.headers["x-request-id"] = request_id
        if route not in ("/healthz", "/readyz", "/metrics"):
            log.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "method": request.method,
                        "route": route,
                        "status": response.status_code,
                        "ms": round(elapsed * 1000, 1),
                    }
                )
            )
        return response

    return app


app = create_app()
