"""한글 합성 리뷰 v2: 실제 쇼핑몰 후기에서 관찰한 특성을 '규칙'으로만 옮겨 반영한다(실제 후기 원문은 프롬프트에 넣지 않는다).
v1(absa.py)과 파일 이름이 달라 서로 덮어쓰지 않는다. 정답은 지시서이고, 같은 추출 프롬프트(VERSION)로 재검증한다.

관찰한 특성(내부 평가셋 11건 요약): 구어체·어미 늘림·띄어쓰기/문장부호 생략이 흔함, 길이 편차가 큼(한 줄 ~ 긴 사연),
상품 속성이 대부분이고 서비스 속성은 드묾, 속성 이름 대신 현상으로 표현("먼지가 많이 나온다", "지퍼가 빠졌다"),
평가와 무관한 문장(추천 문구, 코디·조합, 과거 구매, 신체·착용 정보, 사실만 적은 구매 정보)이 섞임."""
import json
import random
import time

from tqdm.auto import tqdm

from . import config as C
from .absa import ASPECTS, OUT, SENTS, SERVICE, extract
from .translators import GeminiClient

VER = 'v2'
STYLES = [
    '아주 짧은 한 줄(10자 안팎, 마침표 없음)',
    '어미를 늘리거나 바꾼 구어체(예: ~해용, ~죵, ~네유)에 띄어쓰기를 가끔 빼먹는 말투',
    'ㅠㅠ/ㅋㅋ/~가 섞이고 맞춤법이 조금 틀린 말투',
    '반말 메모체(예: "먼지 많이 나옴 비추")',
    '정중하고 자세한 후기체(3~4문장)',
    '사연이 긴 후기(구매 계기나 본인 상황을 먼저 길게 말하고 평가는 중간중간)',
    '불만을 비꼬는 반어 표현이 한 번 들어간 말투',
    '재구매 의사를 밝히거나 다른 사람에게 권하는 말투',
]
LENGTHS = ['한 문장', '한 문장', '두 문장', '두 문장', '세 문장 이상']
# 평가와 무관해서 정답에 속성을 늘리지 않는 문장들
# 평가와 무관해서 정답에 속성을 늘리지 않는 문장 종류(이름만 넘기고 뜻은 프롬프트에 설명한다. 지시문이 후기에 복사되는 것을 막기 위해)
NOISE = ['추천문구', '코디', '과거구매', '체형', '구매정보', '추측']
LEAK = ('추천문구', '과거구매', '구매정보', 'extra', 'forbidden', 'direct', '평가없이', '평가하지', '지시')
PROMPT = (
    '당신은 한국 온라인 쇼핑몰(쿠팡, 무신사, 네이버 스마트스토어 등) 의류 구매 후기를 쓰는 평범한 구매자입니다. 아래 각 항목의 지시에 맞는 후기를 한 개씩 쓰세요.\n'
    '규칙: 지시된 속성은 모두 지시된 감성으로 드러나게 쓰고, "forbidden"에 적힌 속성은 평가하지 마세요(단, "extra"에 적힌 종류의 문장은 넣으세요). extra 종류: 추천문구=끝에 "다른 거 사세요", "강추" 같은 추천을 붙임 / 코디=입을 때 코디·조합 이야기를 한 마디(어떤 속성도 평가하지 않음) / 과거구매=예전 구매 경험을 한 마디 / 체형=본인 키·체형·착용 상황을 한 마디(핏을 평가하지 않음) / 구매정보=주문한 색상이나 사이즈를 사실로만 적음(좋다/나쁘다 없이) / 추측=지시되지 않은 속성에 대해 "~할 것 같아요" 같은 추측을 한 마디. '
    '"중립"은 그 속성을 "보통이에요, 무난해요, 그냥 그래요"처럼 평가한 것이고, 중립 속성에 칭찬이나 불만을 섞지 마세요. '
    '"direct": true인 속성은 속성 이름 자체를 쓰지 말고 눈에 보이는 현상으로 표현하세요(예: 품질은 "실밥이 풀렸어요", "지퍼가 빠졌어요", 사이즈는 "소매가 길어요"). '
    '"긍정/부정/중립" 같은 단어를 직접 쓰지 마세요. 실제 후기처럼 불완전하고 구어체로 쓰되 지시한 스타일과 길이를 따르세요. 상품명이나 브랜드는 쓰지 마세요.\n'
    '출력: [{"id": 번호, "review": "후기"}] 형식의 JSON 배열만 출력하세요.\n\n입력:\n')


def make_specs(n, seed=C.SEED + 1, service_ratio=0.15, noise_ratio=0.5):
    rng = random.Random(seed)
    specs = []
    for i in range(n):
        k = rng.choices([1, 2, 3], [0.45, 0.4, 0.15])[0]
        first = rng.choice(SERVICE if rng.random() < service_ratio else [a for a in ASPECTS if a not in SERVICE])
        asps = [first] + rng.sample([a for a in ASPECTS if a != first and (a not in SERVICE or rng.random() < service_ratio)], k - 1)
        spec = dict(id=i, style=rng.choice(STYLES), length=rng.choice(LENGTHS),
                    aspects=[dict(aspect=a, sentiment=rng.choice(SENTS), direct=rng.random() < 0.5) for a in asps],
                    forbidden=[a for a in ASPECTS if a not in asps])
        if rng.random() < noise_ratio:
            spec['extra'] = rng.sample(NOISE, rng.choice([1, 1, 2]))
        specs.append(spec)
    return specs


def synth_reviews(n=1000, batch=10, name=None, seed=C.SEED + 1):
    """name을 주면 별도 세트(예: 평가 전용)로 만든다. 학습 세트와 시드가 달라 지시서가 겹치지 않는다."""
    path = OUT / f'{name or f"synth_ko.{VER}"}.json'
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if len(saved) == n:
            return saved
    specs = make_specs(n, seed=seed)
    gc = GeminiClient(C.LLM_JUDGE_MODEL)
    out = []
    for i in tqdm(range(0, n, batch), desc='합성 리뷰 v2'):
        part = specs[i:i + batch]
        got = gc.call(PROMPT, part, 'review')
        for s in part:
            out.append(dict(s, review=str(got.get(s['id']) or '').strip()))
        time.sleep(C.GEMINI_SLEEP)
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    return out


def validate(data, name=None):
    """(data, gold, pred, clean). 지시서와 재추출이 완전히 같은 항목이 clean."""
    data = [d for d in data if d['review'] and not any(w in d['review'] for w in LEAK)]   # 지시문이 후기에 복사된 항목 제외
    pred = extract(name or f'synth_pred_{VER}_{len(data)}', [d['review'] for d in data])
    gold = [{x['aspect']: x['sentiment'] for x in d['aspects']} for d in data]
    return data, gold, pred, [i for i, (g, p) in enumerate(zip(gold, pred)) if g == p]
