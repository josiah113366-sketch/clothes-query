from typing import Annotated

from fastapi import APIRouter, Depends

from clothes_api.errors import ApiError
from clothes_api.kafka import ClickPublisher
from clothes_api.routes import deps
from clothes_api.schemas import MAX_CLICKS_PER_REQUEST, ClickBatch

router = APIRouter(prefix="/v1")


@router.post("/events/clicks", status_code=202)
def publish_clicks(
    batch: ClickBatch,
    publisher: Annotated[ClickPublisher, Depends(deps.publisher)],
) -> dict[str, int]:
    if len(batch.events) > MAX_CLICKS_PER_REQUEST:
        raise ApiError(413, "TOO_MANY_EVENTS", f"한 요청에 최대 {MAX_CLICKS_PER_REQUEST}건")
    accepted, failed = publisher.publish(batch.events)
    return {"accepted": accepted, "failed": failed}
