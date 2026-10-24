"""분리된 거래·퍼널·재처리 DAG가 같은 Silver 최신 참조를 동시에 바꾸지 않게 한다."""
from contextlib import contextmanager
from uuid import uuid4

from pipelines.r6_publication import S3Store, encode


@contextmanager
def trade_lease(root, s3, stopped_owner=None):
    store = S3Store(root, s3)
    key = "silver/runtime/trade/control/processing.json"
    import json
    body, etag = store.get(key)
    state = json.loads(body) if body else {}
    if state.get("owner"):
        if stopped_owner != state["owner"]:
            raise RuntimeError("거래·퍼널·재처리가 실행 중이거나 중단됐습니다. 이전 프로세스 종료 확인이 필요합니다")
    elif stopped_owner:
        raise ValueError("복구할 실행 소유자가 일치하지 않습니다")
    state["owner"] = uuid4().hex
    etag = store.put(key, encode(state), etag)
    try:
        yield
    finally:
        store.put(key, encode({"owner": None}), etag)
