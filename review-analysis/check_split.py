"""분할 재현 확인: 노트북과 같은 테스트셋이 나오는지, 번역 캐시가 20k를 모두 덮는지 본다."""
import pandas as pd

from review_analysis import config as C
from review_analysis.data import build_splits, load_en_results

df, tr, va, te = build_splits()
print('전체/학습/검증/테스트:', len(df), len(tr), len(va), len(te))
print('영어 결과와 테스트셋 일치:', list(load_en_results(te)))
t = pd.read_parquet(C.TRANS_DIR / 'NHNDQ-NLLB-en2ko.parquet')
print('NHNDQ 캐시:', len(t), '/ 20k 모두 포함:', set(df.review_id) <= set(t.review_id))
