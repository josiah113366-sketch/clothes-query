"""AI Hub 패션 속성 기반 감성분석 데이터(aihub_dataset/, git 제외)를 우리 속성 체계로 옮기는 도우미. 원문은 로컬에서만 쓴다."""
import collections
import glob
import json
import random

from . import config as C

ROOT = C.ROOT / 'aihub_dataset'
# 대응되는 속성만 옮긴다. 착용감·착화감·기능·무게 등 애매한 속성이 든 후기는 쓰지 않는다
MAP = {'소재': '재질·촉감', '촉감': '재질·촉감', '두께': '재질·촉감',
       '사이즈': '사이즈·핏', '치수/사이즈': '사이즈·핏', '사이즈/폭/길이/두께': '사이즈·핏', '핏': '사이즈·핏', '길이': '사이즈·핏',
       '디자인': '색상·디자인', '색상': '색상·디자인', '품질': '품질·내구성', '내구성': '품질·내구성', '마감': '품질·내구성',
       '가격': '가격·가성비', '냄새': '냄새'}
POL = {'1': '긍정', '-1': '부정', '0': '중립'}
COVERED = ['재질·촉감', '사이즈·핏', '색상·디자인', '품질·내구성', '가격·가성비', '냄새']


def load(split, n=None, seed=C.SEED):
    """split: 'Training' | 'Validation'. 쇼핑몰 후기 중 모든 속성이 매핑되는 것만. 반환: (rows[:n], 사용가능 건수, 제외 건수)"""
    rows, skipped = [], collections.Counter()
    for f in sorted(glob.glob(str(ROOT / split / '02.라벨링데이터' / '*쇼핑몰*' / '*.json'))):
        for r in json.load(open(f, encoding='utf-8')):
            if not all(a['Aspect'] in MAP and a['SentimentPolarity'] in POL for a in r['Aspects']):
                skipped['애매한 속성 포함'] += 1
                continue
            by = collections.defaultdict(set)
            for a in r['Aspects']:
                by[MAP[a['Aspect']]].add(POL[a['SentimentPolarity']])
            gold = {k: (next(iter(v)) if len(v) == 1 else '중립') for k, v in by.items()}   # 같은 속성에 서로 다른 감성이면 중립(가이드)
            rows.append(dict(text=r['RawText'], gold=gold, cat=r['MainCategory']))
    random.Random(seed).shuffle(rows)
    return (rows[:n] if n else rows), len(rows), skipped
