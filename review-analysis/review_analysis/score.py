"""점수(−2~+2) 방식 ABSA 파일럿. 3분류 파이프라인(absa.py, schema3.py)과 분리된 별도 모듈이다.
척도와 기준: docs/absa-label-guide.md 3-1. 미언급 속성은 점수를 만들지 않는다(null, 0과 구분).
AI Hub 후기는 강도 라벨이 없어서 어휘 규칙으로 임시(silver) 점수를 만든다 — 학습용 전용, 평가에는 쓰지 않는다."""
import collections
import glob
import json
import random
import re

import numpy as np

from . import config as C
from . import schema3 as S3

SCALE = [-2, -1, 0, 1, 2]
SHORT_SCORE = (f'의류 리뷰에서 리뷰가 실제로 평가한 속성과 점수를 추출하세요. 속성: {", ".join(S3.ASPECTS3)}. '
               '점수는 정수 -2~2: 2=분명한 만족·칭찬(좋아요, 마음에 들어요, 최고예요), 1=약한 만족(나쁘지 않아요, 괜찮은 것 같아요, 적당해요, 단서가 붙은 만족), 0=보통·무난 또는 장단점 혼재, '
               '-1=약한 불만·의견형 불만(별로예요, 아쉬워요, 좀 크네요, 좋진 않아요), -2=분명한 불만(작아요·줄어들어요 같은 단정적 문제, 너무 ~해요, 최악이에요, 못 입겠어요). '
               '평가 없이 사실만 적었거나 추측·조언·코디 이야기인 속성은 출력하지 마세요. '
               '{"aspects": [{"aspect": "속성", "score": 점수}]} 형식의 JSON 객체 하나만 출력하세요.\n리뷰: ')

# 사람 점수 라벨(2026-10-13)에서 읽은 기준: 일반 칭찬은 +2, 약한 단서가 붙으면 +1 / 단정적 문제·강한 표현은 -2, 의견형·완화 불만은 -1
STRONG = re.compile(r'너무|넘 |넘넘|정말|진짜|완전|엄청|최악|대박|매우|아주|극혐|절대|다시는|못 ?[쓰입신]|구림|개[가-힣]|버렸|버림|쓰레기|환불|!!|ㅠㅠㅠ')
HEDGE_NEG = re.compile(r'좀|조금|약간|살짝|다소|아쉽|아쉬|별로|좋진|좋지는|~긴|크긴|작긴|짧긴|길긴')
MILD_POS = re.compile(r'나쁘지 ?않|괜찮|무난|그럭저럭|그나마|쓸만|적당|크긴|하긴|그래도')
NEUTRAL_W = re.compile(r'보통|평범|그저그|그냥 그|쏘쏘')


def silver_score(pol, text):
    """AI Hub 구절 하나(극성 '1'/'0'/'-1', 구절 원문)에서 임시 점수. 학습용.
    긍정: 약한 단서(나쁘지 않다/괜찮다/적당하다)가 있으면 +1, 아니면 +2. 부정: 의견형·완화 표현이 있고 강조어가 없으면 -1, 아니면 -2. 중립: 기본 0."""
    if pol == '1':
        return 1 if MILD_POS.search(text) and not STRONG.search(text) else 2
    if pol == '-1':
        return -1 if HEDGE_NEG.search(text) and not STRONG.search(text) else -2
    if MILD_POS.search(text) and not HEDGE_NEG.search(text):
        return 1
    if HEDGE_NEG.search(text) and not NEUTRAL_W.search(text):
        return -1
    return 0


def _round_away(m):
    return int(np.sign(m) * np.floor(abs(m) + 0.5))


def load_aihub_scored(split, seed=C.SEED):
    """schema3.load와 같은 필터(매핑 가능, 코디 제외, 중복 제외)로 후기를 읽어 {우리 속성: 점수}를 만든다. 같은 속성 구절은 평균 후 반올림."""
    rows, stat, seen = [], collections.Counter(), set()
    for f in sorted(glob.glob(str(S3.ROOT / split / '02.라벨링데이터' / '*쇼핑몰*' / '*.json'))):
        for r in json.load(open(f, encoding='utf-8')):
            stat['전체'] += 1
            if not all(a['Aspect'] in S3.MAP3 and a['SentimentPolarity'] in S3.POL for a in r['Aspects']):
                stat['제외:매핑 안 되는 속성'] += 1
                continue
            if any(S3.CODY.search(a['SentimentText']) for a in r['Aspects']) or r['RawText'] in seen:
                stat['제외:코디 또는 중복'] += 1
                continue
            seen.add(r['RawText'])
            by = collections.defaultdict(list)
            for a in r['Aspects']:
                by[S3.MAP3[a['Aspect']]].append(silver_score(a['SentimentPolarity'], a['SentimentText']))
            rows.append(dict(text=r['RawText'], gold={k: _round_away(float(np.mean(v))) for k, v in by.items()}, cat=r['MainCategory']))
    random.Random(seed).shuffle(rows)
    stat['사용'] = len(rows)
    return rows, stat


def select_train(rows, n, weak_max=0.5, new_max=0.4):
    """약한/0 점수가 든 후기를 앞쪽에 모아 극단(±2) 쏠림을 줄이고, 활용성·사용감 후기는 new_max*n 이하로 제한."""
    mid = [r for r in rows if any(abs(v) <= 1 for v in r['gold'].values())]
    rest = [r for r in rows if all(abs(v) == 2 for v in r['gold'].values())]
    out, n_new = [], 0
    for r in mid[:int(weak_max * n)] + rest + mid[int(weak_max * n):]:
        if len(out) >= n:
            break
        has_new = S3.NEW in r['gold']
        if has_new and n_new >= new_max * n:
            continue
        out.append(r)
        n_new += has_new
    random.Random(C.SEED).shuffle(out)
    return out


def parse_score(text):
    """모델 출력 → {속성: 점수}. 형식이 깨지면 None."""
    m = re.search(r'\{.*\}', text, re.S)
    try:
        arr = json.loads(m.group(0)).get('aspects')
    except Exception:
        return None
    d = {}
    for a in (arr or []):
        if isinstance(a, dict) and a.get('aspect') in S3.ASPECTS3:
            try:
                s = int(round(float(a.get('score'))))
            except (TypeError, ValueError):
                continue
            d[a['aspect']] = max(-2, min(2, s))
    return d


def target_score(d):
    return json.dumps(dict(aspects=[dict(aspect=k, score=int(v)) for k, v in d.items()]), ensure_ascii=False)


def to_class(s, weak_neutral=False):
    """점수 → 긍정/부정/중립. 기본은 부호 기준, weak_neutral이면 |점수|<=1을 중립으로 묶는다."""
    if weak_neutral:
        return '긍정' if s >= 2 else '부정' if s <= -2 else '중립'
    return '긍정' if s > 0 else '부정' if s < 0 else '중립'


def qwk(a, b):
    """quadratic weighted kappa (−2..2 5단계)."""
    if not a:
        return None
    k = len(SCALE)
    O = np.zeros((k, k))
    for x, y in zip(a, b):
        O[x + 2, y + 2] += 1
    w = np.array([[(i - j) ** 2 for j in range(k)] for i in range(k)]) / (k - 1) ** 2
    E = np.outer(O.sum(1), O.sum(0)) / O.sum()
    den = (w * E).sum()
    return None if den == 0 else round(1 - (w * O).sum() / den, 3)


def metrics(gold, pred, keys=None):
    """gold, pred: 리뷰별 {속성: 점수}. 속성 탐지(P/R/F1) + 공통 속성의 점수 오차 + 파생 3분류 일치."""
    if keys:
        gold, pred = [{k: v for k, v in g.items() if k in keys} for g in gold], [{k: v for k, v in p.items() if k in keys} for p in pred]
    tp = fp = fn = 0
    ga, pa = [], []
    for g, p in zip(gold, pred):
        sg, sp = set(g), set(p)
        tp += len(sg & sp); fp += len(sp - sg); fn += len(sg - sp)
        for k in sg & sp:
            ga.append(g[k]); pa.append(p[k])
    pr, rc = tp / max(1, tp + fp), tp / max(1, tp + fn)
    ga_, pa_ = np.array(ga), np.array(pa)
    out = dict(탐지_정밀도=round(pr, 3), 탐지_재현율=round(rc, 3), 탐지_F1=round(2 * pr * rc / max(1e-9, pr + rc), 3), 공통속성수=len(ga))
    if ga:
        out.update(MAE=round(float(np.abs(ga_ - pa_).mean()), 3), 일치율=round(float((ga_ == pa_).mean()), 3), 이내1=round(float((np.abs(ga_ - pa_) <= 1).mean()), 3),
                   QWK=qwk(ga, pa), 부호반전율=round(float((ga_ * pa_ < 0).mean()), 3),
                   분류일치_부호=round(float(np.mean([to_class(x) == to_class(y) for x, y in zip(ga, pa)])), 3),
                   분류일치_약한중립=round(float(np.mean([to_class(x, True) == to_class(y, True) for x, y in zip(ga, pa)])), 3))
    out['완전일치'] = round(sum(g == p for g, p in zip(gold, pred)) / max(1, len(gold)), 3)
    return out


def load_score_gold(path):
    """점수 평가셋 CSV(review_id,text,aspect,sentiment[−2~2],...). 점수가 정수가 아닌 행(옛 긍정/부정 값)이 있으면 그 행의 목록과 함께 오류."""
    import pandas as pd
    df = pd.read_csv(path, encoding='utf-8-sig', dtype=str, keep_default_na=False)
    df['sentiment'] = df['sentiment'].str.strip()
    df = df[df['aspect'].str.strip() != '']
    bad = df[~df['sentiment'].isin([str(x) for x in SCALE])]
    assert bad.empty, f'점수(−2~2)가 아닌 행 {len(bad)}개: {bad[["review_id", "aspect", "sentiment"]].head(10).to_dict("records")}'
    df['score'] = df['sentiment'].astype(int)
    ids = list(dict.fromkeys(df['review_id']))
    text = df.drop_duplicates('review_id').set_index('review_id')['text']
    gold = [{r.aspect: r.score for r in df[df['review_id'] == i].itertuples()} for i in ids]
    return ids, [text[i] for i in ids], gold
