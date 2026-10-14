"""Bedrock Converse API 호출 (API 키 방식, 표준 라이브러리만 사용).

시뮬레이터 생성기(generator.py)·검수(verifier.py)·벤치마크(bench/)가 모두 이 함수 하나로 Bedrock 을 부른다.
(2026-10-14 정리 전에는 generator.py 와 benchmark/bench.py(옛 폴더 구조) 에 같은 코드가 따로 있었다)

인증: 'Authorization: Bearer <Bedrock API 키>' (.env 의 AWS_BEARER_TOKEN_BEDROCK).
      키 값은 로그·오류 메시지에 절대 넣지 않는다.
의존성: 없음 (urllib). anthropic/boto3 같은 SDK 는 쓰지 않는다.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

# 이 HTTP 상태일 때만 재시도한다. 0 = 네트워크 오류·타임아웃, 429 = 스로틀링, 5xx = 일시적 서버 오류.
# 그 밖의 오류(403 권한 없음, 400 잘못된 모델 ID 등)는 다시 불러도 같으므로 바로 포기한다.
RETRY_STATUSES = (0, 429, 500, 502, 503)

# 한 번 호출의 최대 대기 시간(초). 리뷰 5건 생성이 보통 5~10초라 넉넉하게 잡았다.
TIMEOUT_SEC = 120


def converse_url(region: str, model_id: str) -> str:
    """모델 ID 로 Converse 엔드포인트 주소를 만든다. (jp./apac. 같은 추론 프로필 ID 도 그대로 넣으면 된다)"""
    return f"https://bedrock-runtime.{region}.amazonaws.com/model/{urllib.parse.quote(model_id, safe='')}/converse"


def _post(url: str, api_key: str, body: dict) -> tuple[int, dict | str]:
    """HTTP POST 한 번. (상태코드, JSON 응답 또는 오류 본문 앞부분)을 돌려준다."""
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:300]
    except (
        urllib.error.URLError,
        OSError,
        ValueError,
    ) as e:  # 네트워크 오류, 타임아웃, 응답 JSON 깨짐
        return 0, f"{type(e).__name__}: {e}"[:300]


def converse(
    *,
    api_key: str,
    region: str,
    model_id: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
    retries: int = 3,
) -> tuple[int, dict | str]:
    """Converse API 호출. 일시적 오류는 지수 백오프(2, 4, 8 ... 초)로 최대 retries 번 다시 시도한다.

    temperature: 생성은 BEDROCK_TEMPERATURE(기본 0.8), 검수(라벨링)는 매번 같은 답이 나오도록 0.
    반환: (HTTP 상태, 응답 JSON 또는 오류 문자열). 200 이 아니면 호출한 쪽에서 기록하고 건너뛴다.
    """
    body = {
        "system": [{"text": system}],
        "messages": [{"role": "user", "content": [{"text": user}]}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
    }
    url = converse_url(region, model_id)
    status, resp = 0, ""
    for attempt in range(retries + 1):
        status, resp = _post(url, api_key, body)
        if status == 200 or status not in RETRY_STATUSES or attempt == retries:
            break
        time.sleep(2 ** (attempt + 1))
    return status, resp


def response_text(resp: dict) -> str:
    """Converse 응답에서 모델이 쓴 글(text 블록들)만 이어 붙여 꺼낸다."""
    return "".join(
        c.get("text", "") for c in resp.get("output", {}).get("message", {}).get("content", [])
    )


def response_usage(resp: dict) -> tuple[int, int]:
    """Converse 응답의 (입력 토큰, 출력 토큰). 비용 계산용."""
    u = resp.get("usage", {})
    return u.get("inputTokens", 0), u.get("outputTokens", 0)
