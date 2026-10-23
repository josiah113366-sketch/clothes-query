"""Bedrock 연결 시험. 가짜 클라이언트와 가짜 HTTP로 요청 모양, 응답 처리, 재시도, 오류, 모델별 status 처리를 본다 (진짜 Bedrock은 아직 안 불렀다).

실행: python3 test_bedrock_io.py
"""
import json

from bedrock_io import BedrockConverse, BedrockError, supports_tool_status

ok = True


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


REPLY = {"output": {"message": {"role": "assistant", "content": [{"toolUse": {"toolUseId": "t1", "name": "payment_summary", "input": {}}}]}},
         "usage": {"inputTokens": 120, "outputTokens": 30}, "stopReason": "tool_use"}
MSGS = [{"role": "user", "content": [{"text": "조사해 줘"}]},
        {"role": "assistant", "content": [{"toolUse": {"toolUseId": "t1", "name": "x", "input": {}}}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": "t1", "status": "success", "content": [{"json": {"n": 1}}]}}]}]
SPECS = [{"toolSpec": {"name": "payment_summary", "description": "d", "inputSchema": {"json": {"type": "object"}}}}]


class FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def converse(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class Throttle(Exception):
    response = {"Error": {"Code": "ThrottlingException"}}


no_sleep = lambda s: None

# --- 서버 방식(boto3 클라이언트) ---
c = FakeClient([REPLY])
m = BedrockConverse("amazon.nova-lite-v1:0", client=c, sleep=no_sleep)
out = m("지시문", MSGS, SPECS)
check("응답에서 모델의 다음 메시지(assistant)를 돌려줌", (out["role"], "toolUse" in out["content"][0]), ("assistant", True))
req = c.calls[0]
check("요청: 모델 ID, 지시문, 도구 목록, 온도 0", (req["modelId"], req["system"], req["toolConfig"]["tools"] == SPECS, req["inferenceConfig"]["temperature"]), ("amazon.nova-lite-v1:0", [{"text": "지시문"}], True, 0.0))
check("호출 횟수와 토큰 수를 쌓음", m.usage, {"calls": 1, "input_tokens": 120, "output_tokens": 30})
check("Nova는 도구 결과의 status를 그대로 보냄", req["messages"][2]["content"][0]["toolResult"].get("status"), "success")

# --- 모델별 status ---
check("status 지원 모델 판단: Nova와 Claude(jp. 프로필 포함)는 지원, gpt-oss·deepseek는 미지원",
      [supports_tool_status(x) for x in ("amazon.nova-lite-v1:0", "apac.amazon.nova-lite-v1:0", "jp.anthropic.claude-haiku-4-5", "openai.gpt-oss-120b", "deepseek.v3.2")], [True, True, True, False, False])
c2 = FakeClient([REPLY])
BedrockConverse("openai.gpt-oss-120b", client=c2, sleep=no_sleep)("s", MSGS, SPECS)
check("지원하지 않는 모델에는 status를 빼고 보냄 (원본 메시지는 그대로)", ("status" in c2.calls[0]["messages"][2]["content"][0]["toolResult"], MSGS[2]["content"][0]["toolResult"]["status"]), (False, "success"))
c3 = FakeClient([REPLY])
BedrockConverse("openai.gpt-oss-120b", client=c3, sleep=no_sleep, tool_status=True)("s", MSGS, SPECS)
check("tool_status를 직접 켤 수도 있음", "status" in c3.calls[0]["messages"][2]["content"][0]["toolResult"], True)

# --- 재시도와 오류 ---
c4 = FakeClient([Throttle("slow down"), Throttle("slow down"), REPLY])
slept = []
m4 = BedrockConverse("amazon.nova-lite-v1:0", client=c4, sleep=slept.append)
m4("s", MSGS, SPECS)
check("스로틀링이면 기다렸다가 다시 부름 (2번 실패 뒤 성공, 1초·2초가 아니라 늘어나는 대기)", (len(c4.calls), len(slept), slept == sorted(slept)), (3, 2, True))
c5 = FakeClient([Throttle("x")] * 3)
try:
    BedrockConverse("amazon.nova-lite-v1:0", client=c5, sleep=no_sleep)("s", MSGS, SPECS)
    check("계속 실패하면 오류", "통과됨", "오류")
except BedrockError as e:
    check("계속 실패하면 3번 시도 뒤 오류, 모델 이름이 메시지에 들어감", (len(c5.calls), "amazon.nova-lite-v1:0" in str(e)), (3, True))
c6 = FakeClient([ValueError("bad model id")])
try:
    BedrockConverse("x", client=c6, sleep=no_sleep)("s", MSGS, SPECS)
    check("재시도해도 소용없는 오류는 바로 포기", "통과됨", "오류")
except BedrockError:
    check("재시도해도 소용없는 오류(잘못된 요청)는 한 번만 부르고 포기", len(c6.calls), 1)

# --- 빈 응답, 메시지 정리 ---
empty = {"output": {"message": {"role": "assistant", "content": []}}, "usage": {}}
out = BedrockConverse("amazon.nova-lite-v1:0", client=FakeClient([empty]), sleep=no_sleep)("s", MSGS, SPECS)
check("빈 응답에는 글 한 줄을 채움(다음 요청에서 빈 내용으로 거절되지 않게)", out["content"], [{"text": "(응답 없음)"}])
import datetime
c7 = FakeClient([REPLY])
BedrockConverse("amazon.nova-lite-v1:0", client=c7, sleep=no_sleep)("s", [{"role": "user", "content": [{"toolResult": {"toolUseId": "t", "content": [{"json": {"at": datetime.datetime(2026, 10, 21, 9, 0)}}]}}]}], None)
check("시각 같은 값이 섞여 있어도 JSON으로 바꿔 보냄, 도구 목록이 없으면 toolConfig를 안 보냄", ("2026-10-21 09:00:00" in json.dumps(c7.calls[0]["messages"]), "toolConfig" in c7.calls[0]), (True, False))

# --- API 키 방식(HTTP) ---
posts = []


def fake_post(url, body):
    posts.append((url, body))
    return 200, REPLY


m8 = BedrockConverse("jp.anthropic.claude-haiku-4-5", region="ap-northeast-1", api_key="SECRET-KEY", http_post=fake_post, sleep=no_sleep)
m8("s", MSGS, SPECS)
check("API 키가 있으면 HTTP로 부름, 주소에 모델 ID가 들어감", (posts[0][0], "converse" in posts[0][0]), ("https://bedrock-runtime.ap-northeast-1.amazonaws.com/model/jp.anthropic.claude-haiku-4-5/converse", True))
m9 = BedrockConverse("amazon.nova-lite-v1:0", api_key="SECRET-KEY", http_post=lambda u, b: (403, "AccessDenied"), sleep=no_sleep)
try:
    m9("s", MSGS, SPECS)
    check("권한 오류는 오류", "통과됨", "오류")
except BedrockError as e:
    check("권한 오류(403)는 바로 포기하고, 메시지에 키 값이 없음", ("SECRET-KEY" not in str(e), "403" in str(e)), (True, True))
env_model = BedrockConverse.from_env({"BEDROCK_MODEL_ID": "amazon.nova-lite-v1:0", "AWS_BEARER_TOKEN_BEDROCK": "k"})
check("환경변수로 만들기: 모델 ID, 기본 리전(도쿄), 키 방식", (env_model.model_id, env_model.region, bool(env_model._api_key)), ("amazon.nova-lite-v1:0", "ap-northeast-1", True))
try:
    BedrockConverse.from_env({})
    check("모델 ID가 없으면 오류", "통과됨", "오류")
except ValueError:
    check("모델 ID가 없으면 오류", "오류", "오류")
print("전체:", "모두 통과" if ok else "실패 있음")
raise SystemExit(0 if ok else 1)
