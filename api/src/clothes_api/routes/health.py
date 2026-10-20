from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from clothes_api.errors import ApiError
from clothes_api.kafka import ClickPublisher
from clothes_api.metrics import Metrics
from clothes_api.routes import deps
from clothes_api.store import Store

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(
    store: Annotated[Store, Depends(deps.store)],
    publisher: Annotated[ClickPublisher, Depends(deps.publisher)],
) -> dict[str, str]:
    try:
        store.ping()
    except ApiError:
        raise ApiError(503, "NOT_READY", "DB") from None
    if not publisher.ready():
        raise ApiError(503, "NOT_READY", "Kafka")
    return {"status": "ready"}


@router.get("/metrics")
def metrics(request: Request, metrics: Annotated[Metrics, Depends(deps.metrics)]) -> Response:
    pool = getattr(request.app.state, "pool", None)
    if pool is not None:
        stats = pool.get_stats()
        metrics.db_pool_size.set(stats.get("pool_size", 0))
        metrics.db_pool_available.set(stats.get("pool_available", 0))
        metrics.db_pool_waiting.set(stats.get("requests_waiting", 0))
    return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)
