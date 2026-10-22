from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from clothes_api.metrics import Metrics
from clothes_api.routes import deps
from clothes_api.schemas import NewOrder, NewPayment, StatusUpdate
from clothes_api.store import Outcome, Store

router = APIRouter(prefix="/v1")


@router.post("/orders", status_code=201)
def create_order(
    order: NewOrder,
    response: Response,
    store: Annotated[Store, Depends(deps.store)],
    metrics: Annotated[Metrics, Depends(deps.metrics)],
) -> dict[str, str]:
    outcome = store.create_order(order)
    response.status_code = outcome.value
    if outcome is Outcome.CREATED:
        metrics.orders.inc()
    return {"order_id": str(order.order_id)}


@router.post("/orders/{order_id}/payments", status_code=201)
def add_payment(
    order_id: UUID,
    payment: NewPayment,
    response: Response,
    store: Annotated[Store, Depends(deps.store)],
    metrics: Annotated[Metrics, Depends(deps.metrics)],
) -> dict[str, str]:
    outcome = store.add_payment(order_id, payment)
    response.status_code = outcome.value
    if outcome is Outcome.CREATED:
        metrics.payments.labels(payment.status, payment.pg).inc()
    return {"payment_id": str(payment.payment_id)}


@router.patch("/orders/{order_id}")
def update_order(
    order_id: UUID,
    update: StatusUpdate,
    store: Annotated[Store, Depends(deps.store)],
    metrics: Annotated[Metrics, Depends(deps.metrics)],
) -> dict[str, str]:
    outcome = store.update_status(order_id, update)
    if outcome is Outcome.CREATED:  # 실제로 바뀐 경우만 센다
        metrics.transitions.labels(update.status).inc()
    return {"order_id": str(order_id), "status": update.status}
