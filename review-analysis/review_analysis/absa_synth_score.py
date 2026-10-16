"""점수(−2~+2) 방식용 한글 합성 리뷰. 3분류 합성(absa_synth2.py)과 파일을 분리한다(synth_score.v1.json).
Gemini에 보내는 것은 생성 지시서와 합성 텍스트뿐이다(실제 후기 원문 없음). 정답은 지시서 점수이고, 같은 척도의 재추출로 한 번 검증한다."""
import json
import random
import time

from tqdm.auto import tqdm

from . import config as C
from . import schema3 as S3
from .absa import OUT
from .absa_synth2 import LENGTHS, NOISE, STYLES
from .translators import GeminiClient

VER = 'v2'
SCALE_GUIDE = ('점수 기준(−2~2): 2=분명한 만족·칭찬("좋아요", "마음에 들어요", "예뻐요", "최고예요", "완전 만족"), 1=약한 만족("나쁘지 않아요", "괜찮은 것 같아요", "적당해요", "단서가 붙은 만족: 크긴 했지만 좋았어요"), '
               '0=보통·무난 또는 장단점이 같은 비중("그냥 그래요", "보통이에요", "크지만 기장은 맞아요"), −1=약한 불만·의견형 불만("별로예요", "좀 아쉬워요", "좋진 않아요", "좀 크네요"), '
               '−2=분명한 불만("너무 작아요", "줄어들어요·물들어요 같은 단정적 문제", "최악이에요", "못 입겠어요", "다시는 안 사요", "핏이 구려요"). '
               '완화어(좀·조금·약간·살짝)가 붙은 불만은 −1, 강조어(너무·진짜·완전)가 붙으면 ±2, 일반적인 칭찬은 +2, 평범한 칭찬에 단서(그래도·적당히)가 붙으면 +1.')
PROMPT_GEN = (
    '당신은 한국 온라인 쇼핑몰(쿠팡, 무신사, 네이버 스마트스토어 등) 의류 구매 후기를 쓰는 평범한 구매자입니다. 아래 각 항목의 지시에 맞는 후기를 한 개씩 쓰세요.\n'
    + SCALE_GUIDE + '\n'
    '규칙: 지시된 속성은 모두 지시된 점수에 맞는 강도로 드러나게 쓰고, "forbidden"에 적힌 속성은 평가하지 마세요(단, "extra"에 적힌 종류의 문장은 넣으세요). '
    'extra 종류: 추천문구=끝에 "다른 거 사세요", "강추" 같은 추천을 붙임 / 코디=입을 때 코디·조합 이야기를 한 마디(어떤 속성도 평가하지 않음) / 과거구매=예전 구매 경험을 한 마디 / '
    '체형=본인 키·체형·착용 상황을 한 마디(핏을 평가하지 않음) / 구매정보=주문한 색상이나 사이즈를 사실로만 적음(좋다/나쁘다 없이) / 추측=지시되지 않은 속성에 대해 "~할 것 같아요" 같은 추측을 한 마디. '
    '"direct": true인 속성은 속성 이름 자체를 쓰지 말고 눈에 보이는 현상으로 표현하세요(예: 품질은 "실밥이 풀렸어요", 사이즈는 "소매가 길어요", 활용성·사용감은 "가볍고 편해요"). '
    '속성 점수 숫자나 "긍정/부정/중립" 같은 단어를 후기에 직접 쓰지 마세요. 실제 후기처럼 불완전하고 구어체로 쓰되 지시한 스타일과 길이를 따르세요. 상품명이나 브랜드는 쓰지 마세요.\n'
    '출력: [{"id": 번호, "review": "후기"}] 형식의 JSON 배열만 출력하세요.\n\n입력:\n')
PROMPT_EXTRACT = (
    '다음은 의류·패션 상품 리뷰 목록입니다. 각 리뷰에서 아래 속성 중 리뷰가 실제로 평가한 속성만 골라 속성별 점수를 매기세요.\n'
    f'속성 목록: {", ".join(S3.ASPECTS3)}\n'
    '속성 배정: 재질·촉감(두께·촉감·신축성), 사이즈·핏(길이·기장·핏·크다/작다), 색상·디자인, 품질·내구성(실밥·마감·보풀·이염), 가격·가성비, 냄새, 세탁·관리(세탁 후 변형), '
    '활용성·사용감(착용감·편안함·무게·활용도·계절 기능), 배송, 포장, 교환·환불·CS.\n'
    '미언급(출력하지 않음): 평가 없는 사실, 코디 이야기, 추측·조언, 과거 구매 경험, 추천 문구만 있는 경우.\n'
    + SCALE_GUIDE + '\n'
    '출력: [{"id": 번호, "aspects": [{"aspect": "속성", "score": 정수}]}] 형식의 JSON 배열만 출력하세요.\n\n입력:\n')


def make_specs(n, seed=C.SEED + 2, service_ratio=0.2, noise_ratio=0.5):
    rng = random.Random(seed)
    prod = [a for a in S3.ASPECTS3 if a not in ('배송', '포장', '교환·환불·CS')]
    svc = ['배송', '포장', '교환·환불·CS']
    specs = []
    for i in range(n):
        k = rng.choices([1, 2, 3], [0.45, 0.4, 0.15])[0]
        first = rng.choice(svc if rng.random() < service_ratio else prod)
        asps = [first] + rng.sample([a for a in S3.ASPECTS3 if a != first and (a in prod or rng.random() < service_ratio)], k - 1)
        # 점수 분포: 한쪽에 몰리지 않게 (±2 각 20%, ±1 각 22%, 0 약 16%)
        sc = lambda: rng.choices([-2, -1, 0, 1, 2], [0.2, 0.22, 0.16, 0.22, 0.2])[0]
        spec = dict(id=i, style=rng.choice(STYLES), length=rng.choice(LENGTHS),
                    aspects=[dict(aspect=a, score=sc(), direct=rng.random() < 0.5) for a in asps],
                    forbidden=[a for a in S3.ASPECTS3 if a not in asps])
        if rng.random() < noise_ratio:
            spec['extra'] = rng.sample(NOISE, rng.choice([1, 1, 2]))
        specs.append(spec)
    return specs


def synth_reviews(n=1000, batch=10, name=None, seed=C.SEED + 2):
    path = OUT / f'{name or f"synth_score.{VER}"}.json'
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if len(saved) == n:
            return saved
    gc = GeminiClient(C.LLM_JUDGE_MODEL)
    specs, out = make_specs(n, seed=seed), []
    for i in tqdm(range(0, n, batch), desc='합성 리뷰(점수)'):
        part = specs[i:i + batch]
        got = gc.call(PROMPT_GEN, part, 'review')
        for s in part:
            out.append(dict(s, review=str(got.get(s['id']) or '').strip()))
        time.sleep(C.GEMINI_SLEEP)
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    return out


def validate(data, name):
    """재추출(같은 척도)로 검증. clean = 속성 집합이 같고 모든 점수의 부호가 같으며 차이가 1 이하."""
    from .absa_synth2 import LEAK
    data = [d for d in data if d['review'] and not any(w in d['review'] for w in LEAK)]
    path = OUT / f'{name}.json'
    texts = [d['review'] for d in data]
    if path.exists() and len(json.loads(path.read_text(encoding='utf-8'))) == len(texts):
        got = json.loads(path.read_text(encoding='utf-8'))
    else:
        got = GeminiClient(C.LLM_JUDGE_MODEL).batched(PROMPT_EXTRACT, texts, 'review', 'aspects', desc='점수 재추출')
        path.write_text(json.dumps(got, ensure_ascii=False), encoding='utf-8')
    pred = []
    for g in got:
        d = {}
        for a in (g or []):
            try:
                if isinstance(a, dict) and a.get('aspect') in S3.ASPECTS3:
                    d[a['aspect']] = max(-2, min(2, int(round(float(a.get('score'))))))
            except (TypeError, ValueError):
                pass
        pred.append(d)
    gold = [{x['aspect']: x['score'] for x in d['aspects']} for d in data]
    clean = [i for i, (g, p) in enumerate(zip(gold, pred))
             if set(g) == set(p) and all(g[k] * p[k] >= 0 and abs(g[k] - p[k]) <= 1 for k in g)]
    return data, gold, pred, clean
