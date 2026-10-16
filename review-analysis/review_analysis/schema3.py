"""속성 체계 v3(11개) + AI Hub 후기 변환. 기준: docs/absa-label-guide.md v3, 비교: docs/aihub-label-comparison.md.
AI Hub 원문은 로컬에서만 읽고 어디에도 저장·전송하지 않는다(aihub_dataset/ 는 git 제외)."""
import collections
import glob
import json
import random
import re

from . import absa as A
from . import config as C

NEW = '활용성·사용감'
ASPECTS_V2 = list(A.ASPECTS)   # 10개 (가져온 시점의 absa.ASPECTS)
ASPECTS3 = ASPECTS_V2[:-3] + [NEW] + ASPECTS_V2[-3:]   # 상품 속성 뒤, 서비스 속성 앞에 새 속성
ROOT = C.ROOT / 'aihub_dataset'
MAP3 = {'소재': '재질·촉감', '촉감': '재질·촉감', '두께': '재질·촉감', '신축성': '재질·촉감',
        '사이즈': '사이즈·핏', '치수/사이즈': '사이즈·핏', '사이즈/폭/길이/두께': '사이즈·핏', '핏': '사이즈·핏', '길이': '사이즈·핏',
        '디자인': '색상·디자인', '색상': '색상·디자인',
        '품질': '품질·내구성', '내구성': '품질·내구성', '마감': '품질·내구성',
        '가격': '가격·가성비', '냄새': '냄새',
        '착용감': NEW, '착화감': NEW, '무게': NEW, '활용성': NEW, '기능': NEW}
# 매핑하지 않는 속성(기능성, 사용성, 사용성/편의성, 굽, 수납, 제품구성)이 든 후기는 쓰지 않는다
POL = {'1': '긍정', '-1': '부정', '0': '중립'}
CODY = re.compile(r'코디|매치|조합')   # 코디·조합 구절이 든 후기는 후기째 제외 (R9)

SHORT3 = (f'의류 리뷰에서 리뷰가 실제로 평가한 속성과 감성을 추출하세요. 속성: {", ".join(ASPECTS3)}. '
          '감성: 긍정, 부정, 중립(보통·무난, 장단점 혼재, 완화어가 든 약한 불만). 평가 없이 사실만 적었거나 추측·조언·코디 이야기인 속성은 출력하지 마세요. '
          '{"aspects": [{"aspect": "속성", "sentiment": "감성"}]} 형식의 JSON 객체 하나만 출력하세요.\n리뷰: ')


def set_aspects(v3):
    """absa.ASPECTS는 파서가 검증에 쓴다. v3 모델을 파싱할 때만 11개로 바꾼다."""
    A.ASPECTS[:] = ASPECTS3 if v3 else ASPECTS_V2


def _merge(entries):
    """같은 우리 속성에 해당하는 AI Hub 구절들의 극성을 다수결로 합친다. 동률이면 중립(R16)."""
    by = collections.defaultdict(list)
    for asp, pol in entries:
        by[MAP3[asp]].append(POL[pol])
    gold = {}
    for k, v in by.items():
        c = collections.Counter(v).most_common()
        gold[k] = c[0][0] if len(c) == 1 or c[0][1] > c[1][1] else '중립'
    return gold


def load(split, seed=C.SEED):
    """쇼핑몰 후기 중 모든 속성이 매핑되고 코디 구절이 없는 것. 반환: rows(섞인 순서), 통계."""
    rows, stat, seen = [], collections.Counter(), set()
    for f in sorted(glob.glob(str(ROOT / split / '02.라벨링데이터' / '*쇼핑몰*' / '*.json'))):
        for r in json.load(open(f, encoding='utf-8')):
            stat['전체'] += 1
            if not all(a['Aspect'] in MAP3 and a['SentimentPolarity'] in POL for a in r['Aspects']):
                stat['제외:매핑 안 되는 속성'] += 1
                continue
            if any(CODY.search(a['SentimentText']) for a in r['Aspects']):
                stat['제외:코디 구절'] += 1
                continue
            if r['RawText'] in seen:
                stat['제외:중복'] += 1
                continue
            seen.add(r['RawText'])
            rows.append(dict(text=r['RawText'], gold=_merge([(a['Aspect'], a['SentimentPolarity']) for a in r['Aspects']]), cat=r['MainCategory']))
    random.Random(seed).shuffle(rows)
    stat['사용'] = len(rows)
    return rows, stat


def select_train(rows, n, neutral_max=0.3, new_max=0.4):
    """학습용 n건. 중립이 든 후기를 먼저 담아(최대 neutral_max*n) 중립 비중을 키우고, 활용성·사용감이 든 후기는 new_max*n 이하로 제한한다."""
    neu = [r for r in rows if '중립' in r['gold'].values()]
    rest = [r for r in rows if '중립' not in r['gold'].values()]
    out, n_new = [], 0
    for r in neu[:int(neutral_max * n)] + rest + neu[int(neutral_max * n):]:
        if len(out) >= n:
            break
        has_new = NEW in r['gold']
        if has_new and n_new >= new_max * n:
            continue
        out.append(r)
        n_new += has_new
    random.Random(C.SEED).shuffle(out)
    return out
