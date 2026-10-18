"""샘플링과 학습/검증/테스트 분할. 영어 실험과 같은 코드·시드라서 같은 분할이 나온다."""
import hashlib
import json
import os
import random

import numpy as np
import pandas as pd
import requests
from sklearn.model_selection import train_test_split
from tqdm.auto import tqdm

from . import config as C
from .text import clean_source

STAR2SENT = {1: '부정', 2: '부정', 3: '중립', 4: '긍정', 5: '긍정'}
SENT_ORDER = ['부정', '중립', '긍정']
STARS = [1, 2, 3, 4, 5]
START_MS = int(pd.Timestamp(C.START_DATE, tz='UTC').timestamp() * 1000)
END_MS = int(pd.Timestamp(C.END_DATE, tz='UTC').timestamp() * 1000)


def iter_jsonl(source):
    """리뷰 파일을 한 줄씩 읽어 dict로 돌려준다. http면 스트리밍, 아니면 로컬 파일."""
    if str(source).startswith('http'):
        headers = {}
        if os.environ.get('HF_TOKEN'):
            headers['Authorization'] = f"Bearer {os.environ['HF_TOKEN']}"
        with requests.get(source, stream=True, timeout=120, headers=headers) as r:
            r.raise_for_status()
            for line in r.iter_lines(chunk_size=1 << 20):
                if line:
                    yield json.loads(line)
    else:
        with open(source, encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)


def make_review_id(cat_file, rec):
    key = f"{cat_file}|{rec.get('user_id')}|{rec.get('parent_asin')}|{rec.get('timestamp')}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def reservoir_sample(cat_name, cat_file, k, seed=C.SEED):
    """한 카테고리 파일에서 기간 안의 리뷰를 별점(1~5)별로 최대 k건씩 무작위 추출한다."""
    rng = random.Random(seed)
    buckets = {s: [] for s in range(1, 6)}
    seen = {s: 0 for s in range(1, 6)}
    scanned = 0
    max_lines = C.MAX_SCAN_LINES.get(cat_file)
    for rec in tqdm(iter_jsonl(C.DATA_SOURCES[cat_file]), desc=cat_file, unit=' 줄', mininterval=2):
        scanned += 1
        if max_lines and scanned > max_lines:
            break
        ts = rec.get('timestamp') or 0
        if not (START_MS <= ts < END_MS):
            continue
        text = (rec.get('text') or '').strip()
        if len(text) < C.MIN_CHARS:
            continue
        star = int(round(float(rec.get('rating') or 0)))
        if star not in buckets:
            continue
        seen[star] += 1
        row = dict(review_id=make_review_id(cat_file, rec), category=cat_name, star=star,
                   title=(rec.get('title') or '').strip(), text=text, timestamp=ts, asin=rec.get('asin'),
                   parent_asin=rec.get('parent_asin'), verified_purchase=rec.get('verified_purchase'),
                   helpful_vote=rec.get('helpful_vote'))
        bucket = buckets[star]
        if len(bucket) < k:
            bucket.append(row)
        else:
            j = rng.randrange(seen[star])
            if j < k:
                bucket[j] = row
    rows = [r for s in range(1, 6) for r in buckets[s]]
    stats = dict(category=cat_name, file=cat_file, scanned_lines=scanned,
                 **{f'기간내_{s}점': seen[s] for s in range(1, 6)},
                 **{f'추출_{s}점': len(buckets[s]) for s in range(1, 6)})
    return rows, stats


def sample_raw():
    """원본에서 샘플을 뽑아 SAMPLE_DIR/sample_raw.parquet에 저장한다(이미 있으면 읽기만)."""
    path, stats_path = C.SAMPLE_DIR / 'sample_raw.parquet', C.SAMPLE_DIR / 'sample_stats.csv'
    if C.RESUME and path.exists():
        return pd.read_parquet(path)
    C.SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    k = int(C.N_PER_CLASS * C.OVERSAMPLE)
    rows, stats = [], []
    for name, f in C.CATEGORIES_MAP.items():
        r, s = reservoir_sample(name, f, k)
        rows += r; stats.append(s)
    raw = pd.DataFrame(rows)
    raw.to_parquet(path, index=False)
    pd.DataFrame(stats).to_csv(stats_path, index=False)
    return raw


def build_splits(raw=None):
    """영어 실험과 같은 정제·분할. 반환: df, train_df, val_df, test_df (src_en 열 포함)."""
    if raw is None:
        path = C.SAMPLE_DIR / 'sample_raw.parquet'
        assert path.exists(), f'{path}가 없습니다. 먼저 `python run.py sample`을 실행하거나 파일을 복사하세요.'
        raw = pd.read_parquet(path)
    df = raw.copy()
    df['input_text'] = np.where(df['title'].str.len() > 0, df['title'] + '. ' + df['text'], df['text'])
    df['input_text'] = df['input_text'].str.replace(r'\s+', ' ', regex=True).str.strip()
    df = df.drop_duplicates('input_text').drop_duplicates('review_id')
    df = (df.sample(frac=1, random_state=C.SEED).groupby(['category', 'star']).head(C.N_PER_CLASS)
            .reset_index(drop=True))
    df['sentiment'] = df['star'].map(STAR2SENT)
    df['label'] = df['star'] - 1
    df['date'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%Y-%m-%d')
    df['strata'] = df['category'] + '_' + df['star'].astype(str)
    df['src_en'] = df['input_text'].map(clean_source)
    train_df, rest_df = train_test_split(df, test_size=1 - C.SPLIT[0], stratify=df['strata'], random_state=C.SEED)
    val_df, test_df = train_test_split(rest_df, test_size=C.SPLIT[2] / (C.SPLIT[1] + C.SPLIT[2]),
                                       stratify=rest_df['strata'], random_state=C.SEED)
    train_df, val_df, test_df = (d.reset_index(drop=True) for d in (train_df, val_df, test_df))
    return df, train_df, val_df, test_df


def load_en_results(test_df):
    """영어 실험 결과 중 테스트 리뷰 ID가 지금과 같은 것만 돌려준다."""
    out = {}
    for p in sorted((C.PREV_DIR / 'results').glob('*.json')):
        r = json.loads(p.read_text(encoding='utf-8'))
        if r.get('review_ids') == test_df['review_id'].tolist():
            out[r['short']] = r
        else:
            print(f'[제외] {p.name}: 테스트셋이 지금과 다름')
    return out
