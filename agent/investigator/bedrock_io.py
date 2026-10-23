"""Bedrock Converse 호출: 조사 루프의 `converse(system, messages, tool_specs)` 자리에 꽂는 진짜 모델 연결.

두 가지 방식으로 부른다 (같은 요청·응답 모양이라 결과는 같다)
  1. AWS 권한(SigV4): 서버(EKS Pod)에서. ServiceAccount에 연결된 역할이 권한을 준다. boto3 `bedrock-runtime` 클라이언트를 쓴다.
  2. Bedrock API 키: 내 컴퓨터에서 먼저 시험할 때. 환경변수 AWS_BEARER_TOKEN_BEDROCK을 `Authorization: Bearer`로 보낸다 (표준 라이브러리만 사용).
     리뷰 시뮬레이터(review-simulator/src/rsim/review/bedrock.py)와 같은 방식이다. 키 값은 로그·오류 메시지에 절대 넣지 않는다.

모델은 환경변수 BEDROCK_MODEL_ID로 고른다 (예: amazon.nova-lite-v1:0, jp.anthropic.claude-haiku-4-5). 코드에는 모델 이름을 박아 두지 않는다.
리전 기본값은 도쿄(ap-northeast-1). 처리 리전, 도구 호출 지원, 단가는 모델마다 달라서 쓰기 전에 확인한다(README의 확인 목록).
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_REGION = "ap-northeast-1"
RETRY_STATUSES = (0, 429, 500, 502, 503)     # 0 = 네트워크 오류·시간 초과, 429 = 스로틀링, 5xx = 일시적 서버 오류. 그 밖의 오류는 다시 불러도 같아서 바로 포기한다
RETRY_ERRORS = ("ThrottlingException", "ServiceUnavailableException", "InternalServerException", "ModelTimeoutException")
MAX_ATTEMPTS = 3
TIMEOUT_SEC = 120
# 도구 결과의 status("success"/"error") 필드를 지원하는 모델 (AWS 문서: Amazon Nova, Anthropic Claude 3·4). 그 밖의 모델에는 이 필드를 빼고 보낸다.
STATUS_PREFIXES = ("amazon.nova", "apac.amazon.nova", "us.amazon.nova", "eu.amazon.nova", "anthropic.claude",
                   "jp.anthropic.claude", "apac.anthropic.claude", "us.anthropic.claude", "eu.anthropic.claude", "global.anthropic.claude")


class BedrockError(RuntimeError):
    """모델 호출이 실패했다. 키와 요청 내용은 메시지에 싣지 않는다."""


def supports_tool_status(model_id: str) -> bool:
    return str(model_id).startswith(STATUS_PREFIXES)


def _clean(messages, tool_status):
    """보낼 메시지를 JSON으로 바꿀 수 있는 모양으로 정리한다. 모델이 지원하지 않으면 도구 결과의 status를 뺀다. 빈 응답에는 글 한 줄을 채운다."""
    out = []
    for m in json.loads(json.dumps(messages, default=str)):
        blocks = []
        for b in m.get("content", []):
            if "toolResult" in b and not tool_status:
                b = {"toolResult": {k: v for k, v in b["toolResult"].items() if k != "status"}}
            blocks.append(b)
        out.append({"role": m["role"], "content": blocks or [{"text": "(내용 없음)"}]})
    return out


class BedrockConverse:
    """호출하면 모델의 다음 메시지(dict)를 돌려준다. 호출 횟수와 토큰 수는 usage에 쌓는다."""

    def __init__(self, model_id, region=DEFAULT_REGION, client=None, api_key=None, max_tokens=2048, temperature=0.0,
                 tool_status=None, sleep=time.sleep, http_post=None):
        if not model_id:
            raise ValueError("모델 ID가 필요합니다 (환경변수 BEDROCK_MODEL_ID)")
        self.model_id, self.region = model_id, region
        self._client, self._api_key = client, api_key
        self.max_tokens, self.temperature = max_tokens, temperature
        self.tool_status = supports_tool_status(model_id) if tool_status is None else tool_status
        self._sleep, self._post = sleep, http_post or self._http_post
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    @classmethod
    def from_env(cls, env):
        return cls(env.get("BEDROCK_MODEL_ID"), env.get("AWS_REGION") or DEFAULT_REGION, api_key=env.get("AWS_BEARER_TOKEN_BEDROCK") or None)

    def _body(self, system, messages, tool_specs):
        body = {"messages": _clean(messages, self.tool_status), "system": [{"text": system}],
                "inferenceConfig": {"maxTokens": self.max_tokens, "temperature": self.temperature}}
        if tool_specs:
            body["toolConfig"] = {"tools": tool_specs}
        return body

    def __call__(self, system, messages, tool_specs):
        body = self._body(system, messages, tool_specs)
        last = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            status, resp = self._send(body)
            if status == 200:
                return self._parse(resp)
            last = resp if isinstance(resp, str) else str(status)
            if status not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                break
            self._sleep(2 ** attempt)
        raise BedrockError(f"Bedrock 호출이 실패했습니다 (모델 {self.model_id}, 상태 {status}): {last[:200]}")

    # ---- 보내기 ----
    def _send(self, body):
        if self._api_key:
            url = f"https://bedrock-runtime.{self.region}.amazonaws.com/model/{urllib.parse.quote(self.model_id, safe='')}/converse"
            return self._post(url, body)
        if self._client is None:
            import boto3     # 서버에서만 필요하다. 시험은 가짜 클라이언트를 넣는다

            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        try:
            return 200, self._client.converse(modelId=self.model_id, **body)
        except Exception as e:      # boto3 오류 종류를 가리지 않고 이름과 짧은 메시지만 남긴다
            name = type(e).__name__
            code = getattr(e, "response", {}).get("Error", {}).get("Code", name) if hasattr(e, "response") else name
            return (429 if code in RETRY_ERRORS[:1] else 503 if code in RETRY_ERRORS[1:] else 400), f"{code}: {str(e)[:150]}"

    def _http_post(self, url, body):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")[:300]
        except (urllib.error.URLError, OSError, ValueError) as e:
            return 0, f"{type(e).__name__}"

    # ---- 받기 ----
    def _parse(self, resp):
        msg = resp["output"]["message"]
        u = resp.get("usage", {})
        self.usage["calls"] += 1
        self.usage["input_tokens"] += int(u.get("inputTokens", 0))
        self.usage["output_tokens"] += int(u.get("outputTokens", 0))
        content = msg.get("content") or [{"text": "(응답 없음)"}]
        return {"role": "assistant", "content": content}
