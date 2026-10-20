from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime

from clothes_api.cursor import EPOCH, ChangesCursor, decode_changes, decode_key, encode_key
from clothes_api.metrics import Metrics
from clothes_api.routes import deps
from clothes_api.schemas import NewMember
from clothes_api.store import Outcome, Store

router = APIRouter(prefix="/v1")

PAGE_SIZE = 10_000
CHANGES_LIMIT = 5_000


@router.post("/members", status_code=201)
def create_member(
    member: NewMember,
    response: Response,
    store: Annotated[Store, Depends(deps.store)],
    metrics: Annotated[Metrics, Depends(deps.metrics)],
) -> dict[str, str]:
    outcome = store.insert_member(member)
    response.status_code = outcome.value
    if outcome is Outcome.CREATED:
        metrics.members.inc()
    return {"member_id": str(member.member_id)}


@router.get("/members/signup-count")
def signup_count(
    store: Annotated[Store, Depends(deps.store)],
    since: Annotated[AwareDatetime, Query(alias="from")],
) -> dict[str, int]:
    return {"count": store.signup_count(since)}


@router.get("/members/active")
def active_members(
    store: Annotated[Store, Depends(deps.store)],
    cursor: str | None = None,
) -> dict:
    # 첫 페이지를 읽기 시작한 시각을 변경분 시작점으로 준다(겹쳐 읽기로 그 사이 가입도 잡는다)
    started = datetime.now(UTC)
    ids = store.active_members(decode_key(cursor), PAGE_SIZE)
    next_cursor = encode_key(str(ids[-1])) if len(ids) == PAGE_SIZE else None
    body: dict = {"items": [str(i) for i in ids], "next_cursor": next_cursor}
    if cursor is None:
        body["changes_cursor"] = ChangesCursor(started).encode()
    return body


@router.get("/members/changes")
def member_changes(
    store: Annotated[Store, Depends(deps.store)],
    after: str | None = None,
) -> dict:
    current = decode_changes(after) if after else ChangesCursor(EPOCH)
    rows = store.member_changes(current.query_from, CHANGES_LIMIT)
    last = rows[-1].created_at if rows else current.created_at
    return {
        "added": [str(r.member_id) for r in rows],
        "removed": [],  # 탈퇴는 아직 없다 (탈퇴 작업에서 더한다)
        "next_cursor": ChangesCursor(max(last, current.created_at)).encode(),
        "has_more": len(rows) == CHANGES_LIMIT,
    }


@router.get("/catalog")
def catalog(
    store: Annotated[Store, Depends(deps.store)],
    cursor: str | None = None,
) -> dict:
    rows = store.catalog(decode_key(cursor), PAGE_SIZE)
    next_cursor = encode_key(rows[-1][0]) if len(rows) == PAGE_SIZE else None
    return {
        "items": [{"article_id": a, "price": p} for a, p in rows],
        "next_cursor": next_cursor,
    }
