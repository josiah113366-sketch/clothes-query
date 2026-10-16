"""리뷰 문장 생성기.

- ConverseGenerator : Amazon Bedrock 공통 대화 API(Converse)로 리뷰 문장을 만든다. (운영 기본값)
                      Bedrock API 키(AWS_BEARER_TOKEN_BEDROCK)로 인증한다. 실제 HTTP 호출은 bedrock.py.
                      2026-10-13 벤치마크로 google.gemma-3-12b-it 를 기본 모델로 확정.
- FakeGenerator     : LLM 없이 규칙으로 가짜 문장을 만든다. (Kafka 배관 테스트, 비용 0원)

두 생성기 모두 generate(specs) → {spec_id: {"text": ...}} 형태로 돌려준다.
명세(spec)에 없는 속성을 LLM 이 섞어 쓰면 정답 라벨이 틀어지므로, 프롬프트에서 강하게 금지하고
검수 루프(verifier.py)로 다시 확인한다.

2026-10-14 정리: Claude 전용 생성기(BedrockGenerator, anthropic SDK)와 evidence(근거 문구) 출력·자체 검사를
뺐다. API 키 없이 AWS 프로필로 부르는 경로는 이제 없다.
"""

from __future__ import annotations

import json
import logging
import random
import unicodedata
from typing import ClassVar, Protocol

from .bedrock import converse, response_text, response_usage
from .catalog import PRODUCT_INFO_FIELDS
from .scenario import ReviewSpec
from .seeds import SeedPool
from .taxonomy import ASPECTS
from .verifier import blocking, compare, merge_truth, problems_to_feedback, verify_batch

log = logging.getLogger(__name__)

# 프롬프트를 바꾸면 이 값을 올린다. 이벤트의 generator.prompt_version 으로 기록되므로
# 나중에 "어떤 프롬프트로 만든 리뷰인지" 구분해서 품질을 비교할 수 있다.
# p2: 제목(title) 제거 (국내 쇼핑몰 리뷰에는 보통 제목 칸이 없음)
# p3: 작성자 연령대(age_group)를 명세에 추가
# p4: (클라우드 초안에만 있음) 리뷰 수정 이벤트 규칙. PC 에 반영할 때 p5 규칙과 합친다.
# p5: 2026-10-13 모델 벤치마크 사람 평가 메모 반영 (규칙 8~12: 존댓말 기본, 이모티콘,
#     영어·업무 용어 금지, 앞뒤 문맥 일관성, 길이 지키기) + 말투 목록(taxonomy.STYLES) 수정
# p5.1: 2026-10-14 p5 10건 점검 결과 반영
#     - "한 문장, 40자 이내" 명세 4건이 모두 2~4문장으로 나옴 → 명세마다 max_sentences/max_chars 숫자를 주고
#       규칙 12 를 "가장 먼저 지킬 조건"으로 강화, 짧은 리뷰 예시 추가
#     - 명세에 없는 속성(가격, 재질 등)을 덧붙임 → 명세마다 do_not_mention 목록을 주고 규칙 1 강화
#     - 모델이 "ㅜㅜ" 대신 조합용 자모(U+116E)를 출력 → normalize_jamo() 후처리 추가 (프롬프트 변경 아님)
# p5.2: 2026-10-14 p5.1 100건 중 1~20번 사람 점검(속성 위반 8건, 애매 3건) 반영
#     - 속성마다 "본문 속 근거 문구(evidence)"를 함께 출력 → check_aspects() 로 누락·추가를 코드가 검사,
#       실패한 명세만 1번 다시 생성하고 그래도 실패하면 버린다(정답 라벨 오염 방지)
#     - 중립 표현 예시 추가(규칙 2), 실제 경험만 평가로 인정(규칙 1, "간편하다고 해서" 같은 가정·전해 들은 말 제외)
#     - 짧은 리뷰는 속성 최대 2개 (scenario.py MAX_ASPECTS_SHORT)
# p5.3: 2026-10-14 검수 루프. 생성 모델은 명세 밖 속성을 스스로 신고하지 않아서(p5.2 extra 0건),
#     명세를 가린 채 본문만 검수 모델(review/verifier.py)에 라벨링시키고 명세와 비교한다.
#     실패하면 무엇이 틀렸는지(fix_previous)를 명세에 붙여 다시 생성. 생성 프롬프트 규칙 자체는 p5.2 와 같다.
# p5.4: 2026-10-14 lemin 결정. 덧붙인 속성은 버리지 않고 정답 라벨에 추가(verifier.merge_truth).
#     재생성·버림은 명세 속성 누락·감성 차이일 때만. 재생성 feedback 도 그 문제만 알려 준다.
# p5.5: 2026-10-14 속성 11개(라벨 가이드 v3, 활용성·사용감 추가)
# p5.6: 2026-10-14 evidence(근거 문구) 출력 제거(규칙 13, JSON 형식). 검수 루프가 본문만 보고 판단하므로
#       근거 문구는 쓰이지 않았고 출력 토큰만 늘렸다.
# p5.7: 2026-10-16 lemin 결정. 상품 정보(소재·색상·핏·설명 등, catalog.PRODUCT_INFO_FIELDS)가 있는 상품은
#       명세에 product_info 를 붙여 그 상품에 어울리는 리뷰를 쓰게 한다(규칙 13). 상품 정보가 없으면 명세는 예전과 같다.
#       product_info 는 상품을 떠올리는 참고일 뿐 평가 대상이 아니다(aspects 밖 속성은 계속 금지 → 정답 라벨 보호).
PROMPT_VERSION = "p5.7"

LENGTH_GUIDE = {
    "short": "한 문장, 40자 이내",
    "medium": "2~3문장, 50~120자",
    "long": "4~6문장, 120~250자",
}

# p5.1: 길이를 말로만 주면 작은 모델이 무시해서, 명세마다 숫자로도 준다. (LENGTH_GUIDE 문구와 같은 기준)
LENGTH_LIMITS_FOR_PROMPT = {
    "short": {"max_sentences": 1, "max_chars": 40},
    "medium": {"max_sentences": 3, "max_chars": 120},
    "long": {"max_sentences": 6, "max_chars": 250},
}


class Generator(Protocol):
    model_id: str

    def generate(self, specs: list[ReviewSpec]) -> dict[str, dict]: ...


# ---------------------------------------------------------------- 시스템 프롬프트
# 매 호출마다 똑같이 들어가는 고정 지시문. (자주 바꾸지 않는 내용만 둔다)
# 속성 설명은 taxonomy.ASPECTS 에서 자동으로 만들어서 라벨 가이드와 어긋나지 않게 한다.
_ASPECT_LINES = "\n".join(f"- {name}: {desc}" for name, (_, desc) in ASPECTS.items())

SYSTEM_PROMPT = f"""너는 한국 온라인 패션 쇼핑몰의 상품 리뷰를 쓰는 다양한 실제 구매자들을 흉내 낸다.
요청마다 리뷰 명세 목록이 주어지고, 명세 하나당 리뷰 하나를 쓴다.

반드시 지킬 것
1. 명세의 aspects 에 있는 속성만, 지정된 감성(긍정/중립/부정)으로 평가한다.
   aspects 에 없는 속성(아래 목록)은 칭찬이든 불만이든 평가하는 말을 넣지 않는다.
   명세의 do_not_mention 에 있는 속성은 아예 언급하지 않는다. 특히 가격, 재질·촉감(부드러움), 활용성·사용감(편해요, 가벼워요), 색상은
   습관적으로 덧붙이기 쉬우니 aspects 에 없으면 쓰지 않는다. ("예뻐요", "편해요", "재구매" 같은 말도 평가다)
   평가는 작성자가 직접 겪은 내용이어야 한다. "교환이 간편하다고 해서" 같은 가정이나 전해 들은 말은 평가로 치지 않는다.
2. 중립은 "보통이다/무난하다/그저 그렇다" 같은 평가이거나, 같은 속성의 장단점을 같은 비중으로 말하는 것이다.
   중립 속성에 "예뻐요", "좋아요", "만족" 같은 긍정 표현을 쓰지 않는다. 중립 예시:
   색상·디자인 "색은 무난해요" / 배송 "배송은 보통이었어요" / 사이즈·핏 "사이즈는 그냥 정사이즈예요"
   재질·촉감 "원단은 평범해요" / 가격·가성비 "가격은 적당한 편이에요" / 포장 "포장은 그냥 기본이에요"
3. 별점(rating)과 전체 분위기가 어울려야 한다. (예: 1점인데 전체적으로 만족하는 글은 안 된다)
4. 지정된 말투(style)와 길이(length)를 따르고, 작성자 연령대(age_group)에 자연스러운 표현을 쓴다(연령대를 본문에 직접 밝히지는 않는다). 예시 리뷰들의 실제 말투(줄임말, 맞춤법 실수, 이모티콘 등)를 참고하되 문장을 베끼지 않는다.
5. 상품명은 본문에 그대로 쓰지 않는다. 실제 리뷰처럼 "이 옷", "니트", "신발" 정도로 부른다.
6. 실제 인물 이름, 연락처, 주소 같은 개인정보는 쓰지 않는다.
7. 명세마다 서로 다른 사람이 쓴 것처럼 시작 문구와 표현을 다양하게 한다.
8. 존댓말(해요체)을 기본으로 쓴다. 반말은 말투(style)가 "짧은 음슴체"일 때만 "배송 빠름 근데 좀 작음"처럼 명사형으로 끝낸다.
   "~했다", "~이다", "~네" 처럼 혼잣말(독백체)로 끝나는 문장은 쓰지 않는다.
9. 이모티콘은 실제 리뷰에서 흔한 "ㅎㅎ", "ㅠㅠ", "ㅜㅜ", "^^" 를 쓴다. "ㅋㅋ"는 드물게만, "흑흑" 같은 의성어는 쓰지 않는다.
10. 한국어로만 쓴다. 영어 알파벳, 일본어, 한자를 섞지 않고, "CS" 같은 업무 용어도 쓰지 않는다("고객센터", "문의"처럼 쓴다).
    "핏", "사이즈"처럼 한국 리뷰에서 한글로 굳어진 외래어만 쓴다. 번역투 대신 한국 쇼핑몰 리뷰에서 흔히 보는 표현을 쓴다.
11. 한 사람이 자기가 산 상품 하나를 받아 보고 쓴 글이다. 앞뒤가 맞아야 한다.
    처음 꺼낸 상황(선물, 출근용 등)과 등장인물을 끝까지 유지하고, 갑자기 다른 사람이나 상황을 끌어오지 않는다.
    사이즈 조언("한 치수 크게 사세요")은 aspects 에 사이즈·핏이 있을 때만 쓰고, 그 감성과 맞게 쓴다.
12. 길이가 가장 먼저 지킬 조건이다. 명세의 max_sentences 문장 이하, max_chars 글자(공백 포함) 이하로 쓴다.
    max_sentences 가 1 이면 aspects 가 여러 개여도 문장 하나에 짧게 이어 쓴다.
    (예: "배송 빠르고 핏도 딱 맞아요 ㅎㅎ", "색은 예쁜데 사이즈가 좀 작아요ㅠㅠ")
    쓰고 나서 문장 수와 글자수를 세어 보고, 넘치면 덜 중요한 말을 지운다.
13. 명세에 product_info(상품 정보)가 있으면 그 상품을 실제로 받아 본 사람처럼 쓴다.
    aspects 의 속성을 평가할 때 상품 정보와 맞는 구체적인 내용을 쓴다. (예: 소재가 얇은 린넨이고 재질·촉감이 부정이면 "생각보다 많이 비쳐요")
    상품 정보는 참고일 뿐 평가 대상이 아니다. aspects 에 없는 속성은 상품 정보에 있어도 평가하지 않는다(규칙 1 이 우선).
    상품 정보가 영어여도 본문은 한국어로 쓰고, 상품 설명 문장을 그대로 옮기거나 번역해 넣지 않는다.


속성 목록 (라벨 기준, 11개)
{_ASPECT_LINES}

출력: reviews 배열에 명세마다 {{spec_id, text}} 를 넣는다. 제목 없이 본문만 쓴다."""

# 출력 형식 지시. Converse API 에는 모델 공통 structured output 이 없어서 프롬프트로 JSON 을 요구하고
# parse_reviews() 로 직접 꺼낸다. (bench/bench.py 도 같은 문구를 쓴다)
JSON_INSTRUCTION = (
    "\n\n## 출력 형식 (반드시 지킬 것)\n"
    "설명이나 코드블록 없이 JSON 하나만 출력한다:\n"
    '{"reviews": [{"spec_id": "...", "text": "..."}, ...]}\n'
    "명세 하나당 원소 하나, spec_id 는 명세의 값을 그대로 쓴다."
)


# 조합용 한글 자모(U+1100~, 글자를 조립할 때 쓰는 부품) → 호환용 자모(U+3131~, 키보드로 치는 ㄱ ㅜ).
# gemma 가 "ㅜㅜ" 를 조합용 중성(U+116E)으로 출력해서 화면에 "ᅮᅮ" 처럼 이상하게 보인 문제(p5 점검 5번) 대응.
_CHOSEONG_TO_COMPAT = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"  # U+1100~U+1112 순서
_JAMO_MAP = {0x1100 + i: c for i, c in enumerate(_CHOSEONG_TO_COMPAT)}
_JAMO_MAP.update(
    {0x1161 + i: chr(0x314F + i) for i in range(21)}
)  # 중성 ㅏ~ㅣ (U+1161~U+1175 → U+314F~U+3163)


def normalize_jamo(text: str) -> str:
    """완성형으로 합칠 수 있는 건 먼저 합치고(NFC), 남은 낱자 조합용 자모만 호환용 자모로 바꾼다."""
    return unicodedata.normalize("NFC", text).translate(_JAMO_MAP)


def parse_reviews(text: str) -> list[dict] | None:
    """모델 응답에서 JSON 을 꺼낸다. 코드블록(```json)이나 앞뒤 설명이 붙어도 첫 { ~ 마지막 } 을 시도한다."""
    text = text.strip()
    for candidate in (text, text[text.find("{") : text.rfind("}") + 1]):
        try:
            reviews = json.loads(candidate)["reviews"]
            if isinstance(reviews, list):
                return [
                    r for r in reviews if isinstance(r, dict) and "spec_id" in r and "text" in r
                ]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return None


def _find_problems(
    gen, specs: list[ReviewSpec], out: dict[str, dict]
) -> dict[str, tuple[list[str], list | None]]:
    """생성 결과마다 (문제 목록, 검수 라벨)을 돌려준다.

    본문만 검수 모델(gen.verifier_call)에 주고 라벨을 받아 명세와 비교한다 (p5.3).
    """
    present = [s for s in specs if s.spec_id in out]
    result: dict[str, tuple[list[str], list | None]] = {}
    if not present:
        return result
    labels, usage = verify_batch(
        gen.verifier_call, [(s.spec_id, out[s.spec_id]["text"]) for s in present]
    )
    gen.usage["verify_calls"] += 1
    gen.usage["verify_input_tokens"] += usage["input_tokens"]
    gen.usage["verify_output_tokens"] += usage["output_tokens"]
    for s in present:
        if labels is None or s.spec_id not in labels:
            # 검수 호출 자체가 실패하면 통과시키지 않는다(검사 안 된 라벨이 정답으로 들어가는 것 방지)
            result[s.spec_id] = (["verify_failed"], None)
        else:
            result[s.spec_id] = (compare(s, labels[s.spec_id]), labels[s.spec_id])
    return result


def generate_checked(gen, specs: list[ReviewSpec]) -> dict[str, dict]:
    """검수 루프: 생성 → 검수 → 실패분만 문제 설명을 붙여 다시 생성(최대 ASPECT_RETRIES 번) → 그래도 실패하면 버린다.

    gen._generate_once(specs, feedback) 는 {spec_id: {"text"}} 를 돌려주는 실제 호출 함수.
    결과 dict 에는 aspect_retry(몇 번째 시도에서 통과했는지, 0 = 첫 시도)와 verify_labels 를 붙인다.
    통계는 gen.aspect_stats 에 쌓이고 run.py 가 마지막에 출력한다.
    """
    out = gen._generate_once(specs)
    checks = _find_problems(gen, specs, out)
    gen.aspect_stats["checked"] += len(checks)
    gen.aspect_stats["failed_first"] += sum(bool(blocking(p)) for p, _ in checks.values())
    gen.aspect_stats["extra_added"] = gen.aspect_stats.get("extra_added", 0)
    final: dict[str, dict] = {}
    pending: list[ReviewSpec] = []
    for s in specs:
        if s.spec_id not in checks:
            continue
        problems, labels = checks[s.spec_id]
        if blocking(problems):
            pending.append(s)
        else:
            final[s.spec_id] = {
                **out[s.spec_id],
                "aspect_retry": 0,
                "verify_labels": labels,
                "truth_aspects": merge_truth(s, labels),
            }
    for attempt in range(1, gen.aspect_retries + 1):
        if not pending:
            break
        # 무엇이 틀렸는지 구체적으로 알려 주면 같은 실수를 덜 반복한다 (예: "명세에 없는 가격·가성비 평가를 썼다")
        feedback = {
            s.spec_id: problems_to_feedback(blocking(checks[s.spec_id][0]), checks[s.spec_id][1])
            for s in pending
        }
        retry = gen._generate_once(pending, feedback)
        checks.update(_find_problems(gen, pending, retry))
        still = []
        for s in pending:
            problems, labels = checks.get(s.spec_id, (["no_output"], None))
            if s.spec_id in retry and not blocking(problems):
                final[s.spec_id] = {
                    **retry[s.spec_id],
                    "aspect_retry": attempt,
                    "verify_labels": labels,
                    "truth_aspects": merge_truth(s, labels),
                }
            else:
                still.append(s)
        pending = still
    gen.aspect_stats["extra_added"] += sum(
        any(a["source"] == "verifier" for a in v["truth_aspects"]) for v in final.values()
    )
    for s in pending:
        gen.aspect_stats["dropped"] += 1
        log.info("검수 실패로 버림 %s: %s", s.spec_id, checks.get(s.spec_id, (["no_output"],))[0])
    return final


def product_info(spec: ReviewSpec) -> dict[str, str]:
    """명세에 붙일 상품 정보. 키는 프롬프트용 한국어 이름(catalog.PRODUCT_INFO_FIELDS), 값이 있는 칸만."""
    return {
        label: spec.product.info[key]
        for key, label in PRODUCT_INFO_FIELDS.items()
        if spec.product.info.get(key)
    }


def build_user_prompt(
    specs: list[ReviewSpec], examples: list[dict], feedback: dict[str, str] | None = None
) -> str:
    """사용자 메시지 = 말투 예시 + 이번에 쓸 명세 목록.

    feedback = {spec_id: "지난번에 틀린 점"} 이 있으면 그 명세에 fix_previous 로 붙인다 (검수 루프 재생성용).
    """
    feedback = feedback or {}
    example_lines = []
    for e in examples:
        rating = f"{e['rating']}점" if e.get("rating") else "별점 없음"
        example_lines.append(f"- ({rating}) {e['text']}")
    spec_payload = [
        {
            "spec_id": s.spec_id,
            # category 가 없는 상품(실제 상품 데이터)은 빼고 product_info 로 상품을 알려 준다(2026-10-16)
            **({"category": s.product.category} if s.product.category else {}),
            "product_name": s.product.product_name,
            "rating": s.rating,
            "aspects": s.aspects,
            "age_group": s.age_group,
            "style": s.style,
            "length": LENGTH_GUIDE[s.length],
            # p5.1: 길이를 숫자로도 준다
            **LENGTH_LIMITS_FOR_PROMPT[s.length],
            # p5.1: 명세에 없는 속성 = 언급 금지 목록 (덧붙이면 정답 라벨이 틀어짐)
            "do_not_mention": [a for a in ASPECTS if a not in {x["aspect"] for x in s.aspects}],
            # p5.7: 상품 정보가 있는 상품만 들어감 (프롬프트용, 리뷰 이벤트 컬럼에는 넣지 않음)
            **({"product_info": product_info(s)} if s.product.info else {}),
            # p5.3: 재생성일 때만 들어감. 지난 시도에서 검수 모델이 찾은 문제
            **({"fix_previous": feedback[s.spec_id]} if s.spec_id in feedback else {}),
        }
        for s in specs
    ]
    return (
        "## 실제 말투 예시 (참고만, 베끼지 말 것)\n"
        + "\n".join(example_lines)
        + "\n\n## 이번에 쓸 리뷰 명세\n"
        + json.dumps(spec_payload, ensure_ascii=False, indent=1)
    )


def make_generator(settings, seeds: SeedPool):
    """Bedrock 생성기를 만든다. Bedrock API 키(AWS_BEARER_TOKEN_BEDROCK)가 없으면 바로 멈춘다.

    ECS 로 옮길 때 API 키 대신 태스크 역할만 쓰려면 Converse 를 SigV4 서명으로 부르는 작업이 따로 필요하다.
    """
    if not settings.bedrock_api_key:
        raise SystemExit(
            ".env 또는 환경변수에 AWS_BEARER_TOKEN_BEDROCK(Bedrock API 키)를 넣어 주세요. "
            "비용 없이 흐름만 보려면 --llm fake"
        )
    return ConverseGenerator(settings, seeds)


class ConverseGenerator:
    """Bedrock Converse API 생성기.

    생성 → 검수 → 실패분 재생성 루프는 generate_checked() 가 맡고, 이 클래스는 실제 호출만 한다.
    """

    def __init__(self, settings, seeds: SeedPool):
        self.api_key = settings.bedrock_api_key
        self.region = settings.aws_region
        self.model_id = settings.bedrock_model_id
        self.temperature = settings.bedrock_temperature
        self.max_retries = settings.bedrock_max_retries
        self.few_shot_k = settings.few_shot_k
        self.seeds = seeds
        # 누적 토큰 사용량 (비용 확인용, run.py 가 마지막에 출력). 검수 호출은 따로 센다.
        self.usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "calls": 0,
            "verify_calls": 0,
            "verify_input_tokens": 0,
            "verify_output_tokens": 0,
        }
        # 검수 루프 통계와 재생성 횟수 (ASPECT_RETRIES, 기본 1)
        self.aspect_stats = {"checked": 0, "failed_first": 0, "dropped": 0}
        self.aspect_retries = settings.aspect_retries
        # 검수 모델. VERIFIER_MODEL_ID 를 비우면 생성 모델과 같은 모델
        self.verifier_model_id = settings.verifier_model_id or settings.bedrock_model_id
        self.verifier_call = self._verify_call

    def _verify_call(self, system: str, user: str, max_tokens: int) -> tuple[int, dict | str]:
        """검수 모델 호출. 라벨링은 매번 같은 답이 나와야 하므로 temperature 0."""
        return converse(
            api_key=self.api_key,
            region=self.region,
            model_id=self.verifier_model_id,
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=0,
            retries=self.max_retries,
        )

    def generate(self, specs: list[ReviewSpec]) -> dict[str, dict]:
        """생성 + 검수 + 실패분 재생성 (실제 호출은 _generate_once, 루프는 generate_checked)"""
        return generate_checked(self, specs)

    def _generate_once(
        self, specs: list[ReviewSpec], feedback: dict[str, str] | None = None
    ) -> dict[str, dict]:
        # 배치의 첫 명세 카테고리 기준으로 말투 예시를 뽑는다 (배치 안 카테고리가 섞여도 큰 문제 없음)
        examples = self.seeds.sample(self.few_shot_k, specs[0].product.category)
        status, resp = converse(
            api_key=self.api_key,
            region=self.region,
            model_id=self.model_id,
            system=SYSTEM_PROMPT,
            user=build_user_prompt(specs, examples, feedback) + JSON_INSTRUCTION,
            # 리뷰 1건 ≈ 최대 300 토큰. 배치 크기에 여유를 두고 잡는다(모자라면 응답이 잘림)
            max_tokens=1000 + 500 * len(specs),
            temperature=self.temperature,
            retries=self.max_retries,
        )
        if status != 200:
            log.error("Bedrock 오류 HTTP %s: %s (배치 %d건 건너뜀)", status, resp, len(specs))
            return {}

        in_tok, out_tok = response_usage(resp)
        self.usage["calls"] += 1
        self.usage["input_tokens"] += in_tok
        self.usage["output_tokens"] += out_tok
        if resp.get("stopReason") == "max_tokens":
            log.warning("응답이 maxTokens 에서 잘림: BATCH_SIZE 를 줄여 보세요")
            return {}
        text = response_text(resp)
        reviews = parse_reviews(text)
        if reviews is None:
            log.error("응답 JSON 파싱 실패: %s", text[:200])
            return {}
        return {
            str(r["spec_id"]): {"text": normalize_jamo(str(r["text"]).strip())} for r in reviews
        }


class FakeGenerator:
    """LLM 없이 문장을 조립하는 가짜 생성기. Kafka 까지의 흐름을 비용 없이 확인할 때 쓴다.

    문장 품질은 의미 없고, 명세(속성·감성)를 그대로 문장으로 옮겨 적기만 한다.
    """

    model_id = "fake"

    PHRASES: ClassVar[dict[str, list[str]]] = {
        "긍정": ["{a} 진짜 맘에 들어요", "{a} 좋네요", "{a} 만족합니다"],
        "중립": ["{a}은 그냥 보통이에요", "{a} 무난해요", "{a} 그럭저럭"],
        "부정": ["{a} 별로예요ㅠ", "{a} 때문에 실망", "{a} 아쉬워요"],
    }

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def generate(self, specs: list[ReviewSpec]) -> dict[str, dict]:
        self.usage["calls"] += 1
        out = {}
        for s in specs:
            parts = [
                self.rng.choice(self.PHRASES[a["sentiment"]]).format(a=a["aspect"].split("·")[0])
                for a in s.aspects
            ]
            out[s.spec_id] = {"text": ". ".join(parts) + "."}
        return out
