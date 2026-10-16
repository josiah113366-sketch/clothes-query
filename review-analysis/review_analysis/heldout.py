"""직접 수집한 후기(EX31~) 중 절반을 학습에 쓰고 나머지 절반 + 기존 30건은 평가에만 쓰기 위한 분할 (2026-10-14).
분할 파일: private/collected_half_split.json (train_ids). 만드는 법: python -m review_analysis.heldout"""
import json
import random
import re
from collections import defaultdict

import pandas as pd

from review_analysis import config as C

SPLIT = C.ROOT / 'private' / 'collected_half_split.json'
UPSAMPLE = 3   # 학습에서 수집 후기 1건을 몇 번 넣을지 (제안값)


def make(seed=20261014):
    mp = pd.read_csv(C.ROOT / 'private' / 'collected_to_eval_ids_20261014.csv', encoding='utf-8-sig', dtype=str)
    by = defaultdict(list)
    for _, r in mp.iterrows():
        by[r['annotator']].append(r['eval_id'])
    rng, train = random.Random(seed), []
    for who in sorted(by):   # 작성자별로 절반씩 (작성 스타일이 고르게 들어가도록)
        ids = sorted(by[who], key=lambda x: int(re.sub(r'\D', '', x)))
        rng.shuffle(ids)
        train += ids[:len(ids) // 2]
    train.sort(key=lambda x: int(re.sub(r'\D', '', x)))
    SPLIT.write_text(json.dumps(dict(seed=seed, train_ids=train, n_total=len(mp), by_annotator={k: len(v) for k, v in by.items()}), ensure_ascii=False, indent=1), encoding='utf-8')
    return train


def train_ids():
    return set(json.loads(SPLIT.read_text(encoding='utf-8'))['train_ids'])


if __name__ == '__main__':
    t = make()
    print(len(t), 'train reviews of', json.loads(SPLIT.read_text(encoding='utf-8'))['n_total'])
