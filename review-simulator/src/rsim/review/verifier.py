"""검수 루프용 라벨러 (p5.3, 2026-10-14).

왜 필요한가
  p5.2 에서는 생성 모델이 스스로 "속성별 근거 문구(evidence)"를 적게 했지만,
  모델은 명세 밖에 덧붙인 속성을 절대 신고하지 않았고(1차 검사 extra 0건), 근거를 지어내기도 했다.
  그래서 **명세를 보여 주지 않고 본문만** 다른 호출(검수 모델)에 주고 속성·감성을 라벨링하게 한 뒤,
  그 라벨을 명세와 코드로 비교한다. 다르면 재생성, 재생성 후에도 다르면 버린다.

흐름 (generator.generate_checked / bench/bench.py 에서 사용)
  생성(5건) → 검수 호출 1번(5건) → compare() 로 명세와 비교 → 실패분만 문제 설명(feedback)을 붙여 재생성
  → 다시 검수 → 그래도 실패하면 버림

바꿀 만한 곳
  - VERIFIER_SYSTEM_PROMPT : 라벨 기준. review-analysis/docs/absa-label-guide.md 와 맞춘다.
  - CHECK_SENTIMENT        : False 로 바꾸면 속성 유무만 보고 감성 차이는 무시 (재생성이 너무 많을 때)
  - 검수 모델             : .env 의 VERIFIER_MODEL_ID (기본 = 생성 모델과 같은 gemma)
  2026-10-14: 생성 모델의 evidence 출력과 자체 검사(p5.2)는 뺐다. 속성 검사는 이 검수 루프 하나만 쓴다.
"""

from __future__ import annotations

import json
import logging

from .scenario import ReviewSpec
from .taxonomy import ASPECTS, SENTIMENTS

log = logging.getLogger(__name__)

# 검수 프롬프트 버전. 바꾸면 올린다(결과 파일에 같이 기록됨).
VERIFIER_PROMPT_VERSION = "v2"  # v2: 속성 11개(라벨 가이드 v3)

# 감성(긍정/중립/부정)이 명세와 달라도 실패로 볼지. p5.1 점검에서 "중립인데 긍정으로 씀"이 나와서 기본 True.
CHECK_SENTIMENT = True

_ASPECT_LINES = "\n".join(f"- {name}: {desc}" for name, (_, desc) in ASPECTS.items())

# 검수 모델에게 주는 고정 지시문. 생성 명세는 일부러 보여 주지 않는다(보여 주면 명세에 맞춰 읽어 버림).
VERIFIER_SYSTEM_PROMPT = f"""너는 한국 패션 쇼핑몰 리뷰의 속성별 감성 라벨러다.
리뷰 본문만 보고, 작성자가 평가한 속성과 그 감성을 빠짐없이 찾는다.

속성 목록 (이 11개만 쓴다)
{_ASPECT_LINES}

라벨 기준
1. 작성자가 직접 겪고 좋다/나쁘다/보통이다라고 평가한 속성만 라벨한다.
   - 사실만 말한 것("가죽 소재예요", "선물로 샀어요")은 라벨하지 않는다.
   - 가정이나 전해 들은 말("교환이 간편하다고 해서 안심")은 라벨하지 않는다.
   - 다음 구매자에게 주는 사이즈 조언("반치수 크게 사세요", "정사이즈예요")은 사이즈·핏 평가로 본다.
2. 짧게 스쳐 간 말도 평가면 라벨한다.
   예: "튼튼해 보여요" → 품질·내구성 긍정, "가격도 착해서" → 가격·가성비 긍정, "퀄리티 좋아요" → 품질·내구성 긍정,
       "색깔도 무난해요" → 색상·디자인 중립, "원단이 얇아요"/"부드러워요"/"잘 늘어나요" → 재질·촉감,
       "따뜻해요"/"가볍고 편해요"/"출근룩으로 입기 좋아요" → 활용성·사용감 긍정,
       "디자인은 예쁜데" → 색상·디자인 긍정, "재질은 좀 아쉽지만" → 재질·촉감 부정
3. "만족해요", "강추", "재구매할게요" 처럼 상품 전체에 대한 말은 어느 속성도 아니다.
4. 감성은 긍정/중립/부정 중 하나. 중립은 "보통/무난/그저 그렇다"이거나 같은 속성의 장단점을 같은 비중으로 말한 경우다.
5. 한 속성은 한 번만 적는다. 같은 속성에 여러 말이 있으면 전체적으로 판단한다."""

VERIFIER_JSON_INSTRUCTION = (
    "\n\n## 출력 형식 (반드시 지킬 것)\n"
    "설명이나 코드블록 없이 JSON 하나만 출력한다:\n"
    '{"labels": [{"id": "...", "aspects": [{"aspect": "속성 이름", "sentiment": "긍정|중립|부정", '
    '"phrase": "근거가 된 본문 문구"}]}, ...]}\n'
    "리뷰 하나당 원소 하나, id 는 입력의 값을 그대로 쓴다. 평가한 속성이 없으면 aspects 는 빈 배열."
)


def build_verify_user_prompt(items: list[tuple[str, str]]) -> str:
    """items = [(id, 본문), ...]. 명세(속성·별점)는 넣지 않는다."""
    payload = [{"id": i, "text": t} for i, t in items]
    return (
        "## 라벨링할 리뷰\n"
        + json.dumps(payload, ensure_ascii=False, indent=1)
        + VERIFIER_JSON_INSTRUCTION
    )


def parse_labels(text: str) -> dict[str, list[dict]] | None:
    """검수 응답 → {id: [{"aspect", "sentiment", "phrase"}]}. 목록에 없는 속성/감성 값은 버린다."""
    text = text.strip()
    for candidate in (text, text[text.find("{") : text.rfind("}") + 1]):
        try:
            labels = json.loads(candidate)["labels"]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        out: dict[str, list[dict]] = {}
        for item in labels if isinstance(labels, list) else []:
            if not isinstance(item, dict) or "id" not in item:
                continue
            aspects = []
            for a in item.get("aspects") or []:
                if (
                    isinstance(a, dict)
                    and a.get("aspect") in ASPECTS
                    and a.get("sentiment") in SENTIMENTS
                ):
                    aspects.append(
                        {
                            "aspect": a["aspect"],
                            "sentiment": a["sentiment"],
                            "phrase": str(a.get("phrase", "")),
                        }
                    )
            out[str(item["id"])] = aspects
        return out
    return None


def compare(spec: ReviewSpec, labels: list[dict]) -> list[str]:
    """명세 vs 검수 라벨. 반환: 문제 목록 (비어 있으면 통과)
    missing:<속성>          명세 속성인데 검수 모델이 못 찾음
    extra:<속성>            명세에 없는 속성을 평가함 (가장 흔한 문제)
    sentiment:<속성>:<명세>→<검수>   감성이 다름 (CHECK_SENTIMENT=True 일 때)
    """
    want = {a["aspect"]: a["sentiment"] for a in spec.aspects}
    got = {a["aspect"]: a["sentiment"] for a in labels}
    problems = [f"missing:{a}" for a in want if a not in got]
    problems += [f"extra:{a}" for a in got if a not in want]
    if CHECK_SENTIMENT:
        problems += [
            f"sentiment:{a}:{want[a]}→{got[a]}" for a in want if a in got and got[a] != want[a]
        ]
    return problems


# p5.4 (2026-10-14, lemin 결정): 명세 밖에 덧붙인 속성(extra)은 실패로 보지 않고 정답 라벨에 추가한다.
#   정답 라벨은 학습·분포 유도용 장치이고, 자연스러운 말투가 더 중요하다는 판단.
#   gemma 는 재생성해도 속성 덧붙이기를 거의 못 고쳐서(p5.3 100건 중 39건 버림), 막으면 데이터가 크게 줄고 편향된다.
#   그래서 재생성·버림은 "명세 속성이 빠짐(missing)" 또는 "감성이 다름(sentiment)" 일 때만 한다.
#   다시 막고 싶으면 BLOCKING_KINDS 에 "extra" 를 넣는다.
BLOCKING_KINDS = ("missing", "sentiment", "verify_failed")


def blocking(problems: list[str]) -> list[str]:
    """재생성·버림 사유가 되는 문제만 남긴다."""
    return [p for p in problems if p.split(":", 1)[0] in BLOCKING_KINDS]


def merge_truth(spec: ReviewSpec, labels: list[dict] | None) -> list[dict]:
    """정답 라벨 = 명세 속성(감성은 명세 그대로) + 검수 모델이 찾은 추가 속성(감성은 검수 모델 판단).
    labels 가 없으면(검수 꺼짐) 명세 그대로."""
    truth = [
        {"aspect": a["aspect"], "sentiment": a["sentiment"], "source": "spec"} for a in spec.aspects
    ]
    have = {a["aspect"] for a in spec.aspects}
    for a in labels or []:
        if a["aspect"] not in have:
            truth.append({"aspect": a["aspect"], "sentiment": a["sentiment"], "source": "verifier"})
            have.add(a["aspect"])
    return truth


def problems_to_feedback(problems: list[str], labels: list[dict] | None = None) -> str:
    """재생성 때 명세에 붙일 한국어 설명. 생성 모델이 같은 실수를 반복하지 않게 구체적으로 알려 준다."""
    phrase = {a["aspect"]: a.get("phrase", "") for a in labels or []}
    lines = []
    for p in problems:
        kind, _, rest = p.partition(":")
        if kind == "extra":
            hint = f' (예: "{phrase[rest]}")' if phrase.get(rest) else ""
            lines.append(
                f"명세에 없는 {rest} 평가를 썼다{hint}. 이번에는 {rest} 이야기를 아예 쓰지 않는다."
            )
        elif kind == "missing":
            lines.append(f"{rest} 평가가 드러나지 않았다. {rest} 을(를) 분명하게 평가한다.")
        elif kind == "sentiment":
            aspect, _, change = rest.partition(":")
            want, _, got = change.partition("→")
            lines.append(f"{aspect} 이(가) {got}으로 읽혔다. {want}으로 써야 한다.")
    return " ".join(lines)


def verify_batch(call, items: list[tuple[str, str]]) -> tuple[dict[str, list[dict]] | None, dict]:
    """검수 호출 1번. call(system, user, max_tokens) → (status, resp_json) 는 호출하는 쪽이 넘긴다
    (시뮬레이터는 ConverseGenerator 의 HTTP, 벤치마크는 bench.converse).
    반환: (라벨 dict 또는 실패 시 None, {"input_tokens", "output_tokens", "status"})
    """
    status, resp = call(
        VERIFIER_SYSTEM_PROMPT, build_verify_user_prompt(items), 400 + 250 * len(items)
    )
    usage = {"input_tokens": 0, "output_tokens": 0, "status": status}
    if status != 200 or not isinstance(resp, dict):
        log.error("검수 호출 실패 HTTP %s: %s", status, str(resp)[:200])
        return None, usage
    usage["input_tokens"] = resp.get("usage", {}).get("inputTokens", 0)
    usage["output_tokens"] = resp.get("usage", {}).get("outputTokens", 0)
    text = "".join(
        c.get("text", "") for c in resp.get("output", {}).get("message", {}).get("content", [])
    )
    labels = parse_labels(text)
    if labels is None:
        log.error("검수 응답 JSON 파싱 실패: %s", text[:200])
    return labels, usage
