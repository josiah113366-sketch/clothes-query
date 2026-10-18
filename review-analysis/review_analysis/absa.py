"""속성 기반 감성분석(ABSA): 의류 리뷰에서 속성별 감성(긍정/부정/중립)을 Gemini로 추출하고,
언어·번역·실행 간 일관성과 합성 리뷰 정답 대비 정확도를 잰다. 라벨 기준은 docs/absa-label-guide.md."""
import json
import random
import time

import numpy as np
import pandas as pd
from tqdm.auto import tqdm

from . import config as C
from .translators import GeminiClient

# (속성, 구분). 구분: 상품 / 서비스
ASPECT_DEFS = [
    ('재질·촉감', '상품'), ('사이즈·핏', '상품'), ('색상·디자인', '상품'), ('품질·내구성', '상품'),
    ('가격·가성비', '상품'), ('냄새', '상품'), ('세탁·관리', '상품'),
    ('배송', '서비스'), ('포장', '서비스'), ('교환·환불·CS', '서비스'),
]
ASPECTS = [a for a, _ in ASPECT_DEFS]
SERVICE = [a for a, k in ASPECT_DEFS if k == '서비스']
SENTS = ('긍정', '부정', '중립')
OUT = C.ABSA_DIR
SYNTH_VERSION = 'v1'   # 합성 리뷰 생성 프롬프트 버전 (추출 프롬프트 VERSION과 별개. 생성 프롬프트가 바뀔 때만 올린다)
VERSION = 'v2'   # 프롬프트/가이드가 바뀌면 올려서 캐시를 분리한다 (v0 = 가이드 확정 전, v1 = 1차 확정, v2 = 번호 규칙 R1~R21)

_PROMPT_LINES = [
    '다음은 의류·패션 상품 리뷰 목록입니다(영어 또는 한국어). 각 리뷰에서 아래 속성 중 리뷰가 실제로 평가한 속성만 골라 속성별 감성을 판단하세요.',
    f'속성 목록: {", ".join(ASPECTS)}',
    '속성 배정 규칙:',
    '- 재질·촉감: 두께감, 도톰/얇음, 비침, 보온, 까끌/부드러움',
    '- 사이즈·핏: 길이, 기장, 총장, 소매, 품, 핏, 크롭, 오버핏, 크다/작다/끼다',
    '- 색상·디자인: 색상, 워싱, 디자인, 스타일, 사진과 색 차이',
    '- 품질·내구성: 실밥, 먼지·보풀, 올 풀림, 지퍼·단추·바느질·마감, 튼튼함, 이염·물빠짐·물듦',
    '- 세탁·관리: 세탁 후 줄어듦·늘어남·구김·변형, 세탁·건조 관리 편의 (이염·물빠짐은 품질·내구성)',
    '- 가격·가성비: 가격 대비 만족/불만. "가격 대비 품질이 좋다"처럼 품질도 평가했으면 가격·가성비와 품질·내구성 둘 다',
    '- 배송: 택배 속도·배송 중 문제 / 포장: 박스·비닐·구김·오염 / 교환·환불·CS: 문의·응대·반품·교환 처리',
    '미언급 규칙(해당하면 그 속성을 출력하지 마세요):',
    '- 평가 표현 없이 사실만 적은 경우(예: "택배 박스에 담겨 왔다")',
    '- 코디·조합 이야기(예: "이 옷이랑 맞춰 입을 게 없다")는 어떤 속성도 아닙니다',
    '- 추측·가정·조언("~할 것 같아요", "~일 수도 있어요", "~하세요")은 실제 경험이 아니므로 그 속성을 출력하지 마세요. 실제 경험이 함께 있으면 그 경험으로 판단하세요',
    '- 과거나 다른 구매 경험은 제외하고 이번 구매 평가만 보세요',
    '- "다른 거 사세요", "강추" 같은 추천 문구는 속성이 아닙니다. 리뷰가 말하지 않은 속성을 추론하지 마세요',
    '감성 규칙: "긍정"(분명한 만족), "부정"(분명한 불만), "중립"(보통/무난/그저 그렇다고 평가했거나, 같은 속성 안에 불만과 만족이 모두 있음). '
    '한쪽만 있으면 그쪽(예: "크긴 해요"만 있으면 부정, 의도한 오버핏이라 만족하면 긍정). 기대와 달라도 최종적으로 마음에 든다고 하면 긍정입니다. '
    '반어는 실제 뜻으로, "나쁘지 않아요"는 약한 긍정(확실하지 않으면 중립)으로 판단하세요. 한 속성은 한 번만 출력하세요.',
    '출력: [{"id": 번호, "aspects": [{"aspect": "속성", "sentiment": "감성"}]}] 형식의 JSON 배열만 출력하세요.',
    '',
    '입력:',
]
PROMPT = chr(10).join(_PROMPT_LINES) + chr(10)


def _parse(got):
    res = []
    for g in got:
        d = {}
        for a in (g or []):
            if isinstance(a, dict) and a.get('aspect') in ASPECTS and a.get('sentiment') in SENTS:
                d[a['aspect']] = a['sentiment']
        res.append(d)
    return res


def extract(name, texts, out_dir=OUT):
    """texts의 속성별 감성을 Gemini로 추출. 같은 name의 저장본이 있으면 재사용한다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f'{name}.{VERSION}.json'
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if len(saved) == len(texts):
            return saved
    got = GeminiClient(C.LLM_JUDGE_MODEL).batched(PROMPT, texts, 'review', 'aspects', desc=f'ABSA {name}')
    res = _parse(got)
    path.write_text(json.dumps(res, ensure_ascii=False), encoding='utf-8')
    return res


def compare(a, b):
    """a, b: 리뷰별 {속성: 감성}. 속성 탐지 정밀도/재현율/F1, 공통 속성의 감성 일치율, 극성 반전율."""
    tp = fp = fn = agree = flip = both = 0
    for x, y in zip(a, b):
        sx, sy = set(x), set(y)
        tp += len(sx & sy); fp += len(sy - sx); fn += len(sx - sy)
        for k in sx & sy:
            both += 1
            agree += x[k] == y[k]
            flip += {x[k], y[k]} == {'긍정', '부정'}
    p, r = tp / max(1, tp + fp), tp / max(1, tp + fn)
    return dict(탐지_정밀도=round(p, 3), 탐지_재현율=round(r, 3), 탐지_F1=round(2 * p * r / max(1e-9, p + r), 3),
                공통속성수=both, 감성일치율=round(agree / max(1, both), 3), 극성반전율=round(flip / max(1, both), 3))


def per_aspect(gold, pred):
    """속성별 탐지 정밀도/재현율/F1과 감성 정확도 (gold 기준)."""
    rows = {}
    for asp in ASPECTS:
        tp = sum(asp in g and asp in p for g, p in zip(gold, pred))
        fp = sum(asp not in g and asp in p for g, p in zip(gold, pred))
        fn = sum(asp in g and asp not in p for g, p in zip(gold, pred))
        sacc = [g[asp] == p[asp] for g, p in zip(gold, pred) if asp in g and asp in p]
        pr, rc = tp / max(1, tp + fp), tp / max(1, tp + fn)
        rows[asp] = dict(정답수=tp + fn, 정밀도=round(pr, 3), 재현율=round(rc, 3),
                         F1=round(2 * pr * rc / max(1e-9, pr + rc), 3), 감성정확도=round(float(np.mean(sacc)), 3) if sacc else None)
    return pd.DataFrame(rows).T


# ---------- 한글 합성 리뷰 (정답이 생성 시점에 정해짐) ----------
STYLES = ['짧은 반말체(예: "배송 빠름 근데 좀 작음")', 'ㅋㅋ/ㅠㅠ 같은 표현과 오타가 조금 섞인 말투', '정중하고 자세한 후기체',
          '불만을 비꼬는 반어 표현이 한 번 들어간 말투', '이모지 없이 간결한 두세 문장', '구매 의도를 설명하는 긴 후기(4~5문장)',
          '재구매 의사를 밝히는 말투', '사진 후기 느낌의 짧은 코멘트']

SYNTH_PROMPT = (
    '당신은 한국 온라인 쇼핑몰(쿠팡, 네이버 스마트스토어 등)의 의류 구매 후기를 쓰는 사람입니다. 아래 각 항목의 지시에 맞는 후기를 한 개씩 쓰세요.\n'
    '규칙: 지시된 속성은 모두 지시된 감성으로 드러나게 쓰고, 항목의 "forbidden"에 적힌 속성은 단어와 암시 모두 절대 언급하지 마세요 '
    '(예: 배송이 forbidden이면 택배, 도착, 배달도 쓰지 말고, 품질이 forbidden이면 튼튼함, 올 풀림, 마감도 쓰지 마세요). '
    '"중립"은 그 속성을 "보통이에요, 무난해요, 그냥 그래요"처럼 평가한 것이지 사실만 적는 것이 아닙니다. 중립 속성에 칭찬이나 불만을 섞지 마세요. '
    '"긍정/부정/중립" 같은 단어를 직접 쓰지 말고 실제 후기처럼 자연스럽게 쓰세요. 말투는 지시한 스타일을 따르세요. 상품명이나 브랜드는 쓰지 마세요.\n'
    '출력: [{"id": 번호, "review": "후기"}] 형식의 JSON 배열만 출력하세요.\n\n입력:\n')


def make_specs(n, seed=C.SEED, service_ratio=0.45):
    """합성 리뷰 지시서. 서비스 속성이 들어간 항목을 service_ratio만큼 넣어 아마존 데이터의 약점을 보완한다."""
    rng = random.Random(seed)
    specs = []
    for i in range(n):
        k = rng.choices([1, 2, 3], [0.4, 0.4, 0.2])[0]
        pool_service = rng.random() < service_ratio
        first = rng.choice(SERVICE if pool_service else ASPECTS)
        asps = [first] + rng.sample([a for a in ASPECTS if a != first], k - 1)
        specs.append(dict(id=i, style=rng.choice(STYLES),
                          aspects=[dict(aspect=a, sentiment=rng.choice(SENTS)) for a in asps],
                          forbidden=[a for a in ASPECTS if a not in asps]))
    return specs


def synth_reviews(n=200, batch=10):
    """Gemini로 한글 합성 리뷰를 만들고 정답과 함께 저장한다. (같은 모델이 쓰고 읽으므로 정확도는 낙관적이다)"""
    path = OUT / f'synth_ko.{SYNTH_VERSION}.json'
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if len(saved) == n:
            return saved
    specs = make_specs(n)
    gc = GeminiClient(C.LLM_JUDGE_MODEL)
    out = []
    for i in tqdm(range(0, n, batch), desc='합성 리뷰'):
        part = specs[i:i + batch]
        got = gc.call(SYNTH_PROMPT, part, 'review')
        for s in part:
            out.append(dict(s, review=str(got.get(s['id']) or '').strip()))
        time.sleep(C.GEMINI_SLEEP)
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    return out


def validate_synth(data):
    """합성 리뷰를 읽기 전용 추출로 다시 검증한다. 정답(지시서)과 추출이 완전히 같은 항목만 clean으로 분류하고,
    다른 항목은 사람이 확인할 수 있게 review_queue로 돌려준다."""
    data = [d for d in data if d['review']]
    pred = extract(f'synth_pred_{len(data)}', [d['review'] for d in data])
    gold = [{x['aspect']: x['sentiment'] for x in d['aspects']} for d in data]
    clean = [i for i, (g, p) in enumerate(zip(gold, pred)) if g == p]
    queue = [dict(idx=i, review=data[i]['review'], 지시=json.dumps(gold[i], ensure_ascii=False),
                  추출=json.dumps(pred[i], ensure_ascii=False)) for i in range(len(data)) if i not in set(clean)]
    return data, gold, pred, clean, queue


def score_eval_csv(path, return_rows=False):
    """사람이 작성한 평가셋 CSV(긴 형식: review_id,text,aspect,sentiment,annotator,note)를 Gemini 추출과 비교한다.
    annotator가 둘 이상이면 첫 번째를 정답으로 쓰고 둘 사이 일치도도 보고한다. 예시 행(annotator=예시)은 제외한다."""
    df = pd.read_csv(path, encoding='utf-8-sig')
    # annotator 칸을 비워 둔 경우도 허용한다 (pandas 3에서는 빈 칸이 'nan' 문자열이 아니라 결측값이라 따로 채워야 한다)
    df['annotator'] = df['annotator'].fillna('라벨러1').astype(str).str.strip().replace('', '라벨러1')
    df['review_id'] = df['review_id'].astype(str).str.strip()
    df['aspect'] = df['aspect'].astype('string').str.strip()
    df['sentiment'] = df['sentiment'].astype('string').str.strip()
    df = df[df['annotator'] != '예시'].dropna(subset=['aspect', 'sentiment'])
    assert len(df), '평가 행이 없습니다. 템플릿의 예시 행은 제외됩니다.'
    bad = df[~df['aspect'].isin(ASPECTS) | ~df['sentiment'].isin(SENTS)]
    assert bad.empty, f'속성/감성 값이 목록에 없는 행이 있습니다: {bad.head().to_dict("records")}'
    annotators = list(dict.fromkeys(df['annotator'].astype(str)))
    ids = list(dict.fromkeys(df['review_id'].astype(str)))
    text = df.drop_duplicates('review_id').set_index(df.drop_duplicates('review_id')['review_id'].astype(str))['text']

    def gold_of(ann):
        sub = df[df['annotator'].astype(str) == ann]
        return [{r.aspect: r.sentiment for r in sub[sub['review_id'].astype(str) == i].itertuples()} for i in ids]

    gold = gold_of(annotators[0])
    import hashlib   # 같은 건수라도 리뷰 문구를 고치면 캐시를 쓰지 않도록 문구의 해시를 이름에 넣는다
    texts = [text[i] for i in ids]
    h = hashlib.sha1('|'.join(texts).encode('utf-8')).hexdigest()[:8]
    pred = extract(f'human_eval_{len(ids)}_{h}', texts)
    rep = dict(전체=compare(gold, pred), 속성별=per_aspect(gold, pred))
    if len(annotators) > 1:
        rep['라벨러간_일치'] = compare(gold, gold_of(annotators[1]))
    dis = [dict(review_id=i, text=text[i], 사람=json.dumps(g, ensure_ascii=False), 모델=json.dumps(p, ensure_ascii=False))
           for i, g, p in zip(ids, gold, pred) if g != p]
    if return_rows:   # 화면 표시용: 리뷰별 원문·사람 라벨·모델 라벨 (원문이 들어 있으니 내부용으로만 쓴다)
        rows = [dict(review_id=i, text=text[i], gold=g, pred=p) for i, g, p in zip(ids, gold, pred)]
        return rep, pd.DataFrame(dis), rows
    return rep, pd.DataFrame(dis)


def load_eval_gold(path):
    """평가셋 CSV에서 (리뷰 ID 목록, 원문 목록, 사람 라벨 목록)만 읽는다. Gemini를 부르지 않는다(외부 전송 없음).
    annotator가 여럿이면 첫 번째 라벨러를 정답으로 쓴다."""
    df = pd.read_csv(path, encoding='utf-8-sig')
    df['annotator'] = df['annotator'].fillna('라벨러1').astype(str).str.strip().replace('', '라벨러1')
    df['review_id'] = df['review_id'].astype(str).str.strip()
    df['aspect'] = df['aspect'].astype('string').str.strip()
    df['sentiment'] = df['sentiment'].astype('string').str.strip()
    df = df[df['annotator'] != '예시'].dropna(subset=['aspect', 'sentiment'])
    assert len(df), '평가 행이 없습니다.'
    bad = df[~df['aspect'].isin(ASPECTS) | ~df['sentiment'].isin(SENTS)]
    assert bad.empty, f'속성/감성 값이 목록에 없는 행이 있습니다: {bad.head().to_dict("records")}'
    first = df[df['annotator'] == df['annotator'].iloc[0]]
    ids = list(dict.fromkeys(df['review_id']))
    text = df.drop_duplicates('review_id').set_index('review_id')['text']
    gold = [{r.aspect: r.sentiment for r in first[first['review_id'] == i].itertuples()} for i in ids]
    return ids, [text[i] for i in ids], gold
