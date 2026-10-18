"""실험 설정. 노트북의 '1. 실험 설정' 셀을 그대로 옮긴 파일이다.
바꾸고 싶은 값은 이 파일만 고치면 된다.
샘플·분할 값(N_PER_CLASS, SPLIT, SEED)은 영어 실험과 같아야 같은 테스트셋으로 비교된다."""
import os
from pathlib import Path

import pandas as pd

try:                                    # .env가 있으면 읽음 (GEMINI_KEY 등). 없어도 동작.
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
except ImportError:
    pass

# ===== 폴더 (노트북의 Drive 폴더와 같은 이름·구조) =====
ROOT = Path(__file__).resolve().parent.parent
PREV_DIR = ROOT / 'voc_amazon_finetune'   # (옛 파이프라인) 영어 실험 결과. 지금은 archive/에 보관
ABSA_DIR = ROOT / 'data' / 'absa_pilot'    # 속성 분석(ABSA) 합성 데이터와 Gemini 재추출 캐시. 지금 학습·평가가 읽는다
OUT_DIR = ROOT / 'voc_amazon_ko'          # (옛 파이프라인) 한국어 실험 결과. 지금은 archive/에 보관, 다시 돌리면 이 위치에 생긴다
RESULTS_DIR = OUT_DIR / 'results'         # 한국어 감성 모델별 결과(JSON)
ARCHIVE_DIR = ROOT / 'archive'            # 지난 시험 결과 보관 (archive/README.md 참고)
SAMPLE_DIR = ARCHIVE_DIR / '2026-10-08_en-star-rating'   # sample_raw.parquet, sample_stats.csv
TRANS_DIR = ARCHIVE_DIR / '2026-10-08_ko-translation-compare' / 'translations'   # 번역 후보별 번역문 캐시(parquet: review_id, ko)
MODELS_DIR = OUT_DIR / 'models'
RESUME = True                             # 이미 끝난 번역·모델 결과가 있으면 건너뜀

# ===== 데이터 범위 (영어 실험과 같아야 함) =====
CATEGORIES_MAP = {                        # 화면 이름 → 데이터셋 파일 이름
    'Fashion': 'Amazon_Fashion',
    'Clothing·Shoes': 'Clothing_Shoes_and_Jewelry',
}
CATEGORIES = list(CATEGORIES_MAP)
DATA_BASE_URL = 'https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw/review_categories'
# 파일을 직접 내려받아 두었다면 값을 로컬 경로로 바꿔도 된다.
DATA_SOURCES = {f: f'{DATA_BASE_URL}/{f}.jsonl' for f in CATEGORIES_MAP.values()}
END_DATE = '2023-10-01'                   # 이 날짜는 포함하지 않음
YEARS = 3
START_DATE = (pd.Timestamp(END_DATE) - pd.DateOffset(years=YEARS)).strftime('%Y-%m-%d')   # 2020-10-01
MAX_SCAN_LINES = {'Amazon_Fashion': None, 'Clothing_Shoes_and_Jewelry': 3_000_000}
N_PER_CLASS = 2000
OVERSAMPLE = 1.3
MIN_CHARS = 20
SPLIT = (0.70, 0.15, 0.15)
SEED = 42

# ===== 번역 후보 =====
# kind: gemini(API) / papago(API) / nllb / m2m / marian / madlad (번역 전용 seq2seq) / llm (번역 LLM)
# enabled=False인 후보는 비교에서 빠진다. dtype은 LLM 로딩 정밀도(기본 fp16). Gemma 계열은 fp16에서 불안정해 bf16을 쓴다.
_ROSETTA_SYS = ("Translate the user's text to Korean.\nTone: keep the reviewer's sentiment and its intensity exactly.\n"
                'Provide the final translation immediately without any other text.')
MT_CANDIDATES = [
    dict(short='Gemini-3.5-FlashLite', kind='gemini', model='gemini-3.5-flash-lite', license='상용 API', enabled=True),
    dict(short='Papago', kind='papago', license='상용 API(유료)', enabled=True),
    dict(short='NLLB-600M', kind='nllb', hf='facebook/nllb-200-distilled-600M', license='CC-BY-NC-4.0', enabled=True),
    dict(short='NLLB-1.3B', kind='nllb', hf='facebook/nllb-200-distilled-1.3B', license='CC-BY-NC-4.0', enabled=True),
    dict(short='NHNDQ-NLLB-en2ko', kind='nllb', hf='NHNDQ/nllb-finetuned-en2ko', license='CC-BY-4.0(기반 NC)', enabled=True),
    dict(short='M2M100-418M', kind='m2m', hf='facebook/m2m100_418M', license='MIT', enabled=True),
    dict(short='M2M100-1.2B', kind='m2m', hf='facebook/m2m100_1.2B', license='MIT', enabled=True),
    dict(short='OPUS-MT-big', kind='marian', hf='Helsinki-NLP/opus-mt-tc-big-en-ko', license='CC-BY-4.0', enabled=False),
    dict(short='NLLB-3.3B', kind='nllb', hf='facebook/nllb-200-3.3B', license='CC-BY-NC-4.0', enabled=False),
    dict(short='MADLAD-3B', kind='madlad', hf='google/madlad400-3b-mt', license='Apache-2.0', enabled=False, fp32=True),
    dict(short='Gugugo-7B', kind='llm', hf='squarelike/Gugugo-koen-7B-V1.1', license='Apache-2.0', enabled=True, quant='4bit',
         prompt='### 영어: {text}</끝>\n### 한국어:', stop=['</끝>', '###']),
    dict(short='Rosetta-4B', kind='llm', hf='yanolja/YanoljaNEXT-Rosetta-4B', license='Gemma', enabled=True, json_io=True,
         dtype='bf16', system_prompt=_ROSETTA_SYS),
    dict(short='EXAONE-3.5-7.8B', kind='llm', hf='LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct', license='EXAONE NC', enabled=True,
         quant='4bit', trust_remote_code=True),
    dict(short='Qwen2.5-7B', kind='llm', hf='Qwen/Qwen2.5-7B-Instruct', license='Apache-2.0', enabled=True, quant='4bit'),
    dict(short='iris-7B', kind='llm', hf='davidkim205/iris-7b', license='Apache-2.0', enabled=True, quant='4bit',
         prompt='[INST] 다음 문장을 한글로 번역하세요.{text} [/INST]', stop=['</s>', '[INST]']),
    dict(short='llama3-instrucTrans-8B', kind='llm', hf='nayohan/llama3-instrucTrans-enko-8b', license='Llama 3', enabled=True,
         quant='4bit', system_prompt='당신은 번역기 입니다. 영어를 한국어로 번역하세요.'),
    dict(short='EXAONE-3.5-2.4B', kind='llm', hf='LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct', license='EXAONE NC', enabled=False,
         trust_remote_code=True),
    dict(short='Qwen3-4B', kind='llm', hf='Qwen/Qwen3-4B-Instruct-2507', license='Apache-2.0', enabled=False),
    dict(short='Qwen3-8B', kind='llm', hf='Qwen/Qwen3-8B', license='Apache-2.0', enabled=False, quant='4bit'),
    dict(short='Rosetta-12B', kind='llm', hf='yanolja/YanoljaNEXT-Rosetta-12B', license='Gemma', enabled=False, quant='4bit',
         json_io=True, dtype='bf16', system_prompt=_ROSETTA_SYS),
    dict(short='TowerInstruct-7B', kind='llm', hf='Unbabel/TowerInstruct-7B-v0.2', license='CC-BY-NC-4.0', enabled=False,
         quant='4bit', system_prompt=None,
         user_template='Translate the following text from English into Korean.\nEnglish: {text}\nKorean:'),
    dict(short='Tower-Plus-9B', kind='llm', hf='Unbabel/Tower-Plus-9B', license='CC-BY-NC-SA-4.0', enabled=False, quant='4bit',
         system_prompt=None,
         user_template='Translate the following English source text to Korean:\nEnglish: {text}\nKorean: '),
]
MT_BY_NAME = {c['short']: c for c in MT_CANDIDATES}
MT_EVAL_N = 300           # 번역 후보 비교에 쓸 테스트 리뷰 수 (별점별로 고르게)
MAIN_MT = 'auto'          # 전체 번역에 쓸 후보 이름. 'auto'면 비교 점수 1위
AUTO_ALLOW_API = False    # 'auto'에서 Gemini·Papago도 고를지
BACK_MT = 'M2M100-1.2B'   # 역번역(한→영)에 쓸 모델 (오픈 모델만)
SENTI_JUDGES = [
    dict(short='tabularisai', hf='tabularisai/multilingual-sentiment-analysis'),
    dict(short='clapAI', hf='clapAI/roberta-base-multilingual-sentiment'),
]
USE_LLM_JUDGE = True
LLM_JUDGE_MODEL = 'gemini-3.5-flash-lite'
USE_COMETKIWI = False

MT_BATCH = 32
LLM_BATCH = 8
LLM_MAX_NEW_TOKENS = 768
MT_BEAMS = 2
MAX_SRC_CHARS = 1200
MAX_CHUNK_CHARS = 400
GEMINI_BATCH = 20
GEMINI_SLEEP = 4.0
SAVE_EVERY = 1000

# ===== 한국어 감성 모델 =====
MODELS = [
    dict(short='KcELECTRA', hf='beomi/KcELECTRA-base', base='ELECTRA(한국어)', license='MIT', zero_shot=False),
    dict(short='KLUE-RoBERTa', hf='klue/roberta-base', base='RoBERTa(한국어)', license='카드 미표기', zero_shot=False),
    dict(short='nlptown-mBERT', hf='nlptown/bert-base-multilingual-uncased-sentiment', base='mBERT', license='MIT'),
    dict(short='tabularisai-DistilBERT', hf='tabularisai/multilingual-sentiment-analysis', base='DistilBERT',
         license='CC-BY-NC-4.0'),
    dict(short='clapAI-XLMR', hf='clapAI/roberta-base-multilingual-sentiment', base='XLM-R', license='Apache-2.0'),
]

# ===== 학습 하이퍼파라미터 (영어 실험과 같게) =====
MAX_LEN, BATCH_SIZE, EVAL_BATCH_SIZE = 160, 32, 128
EPOCHS, LR, WEIGHT_DECAY, WARMUP_RATIO, PATIENCE = 3, 2e-5, 0.01, 0.1, 1
SAVE_MODELS = False
DASHBOARD_MAX_ROWS = 3000

# ===== 디스크 관리 (Colab에서 'No space left on device'로 모델 3개가 실패한 문제 대응) =====
HF_CACHE_CLEANUP = True   # 번역 모델 하나가 끝날 때마다 그 모델의 HF 캐시를 지움
MIN_FREE_GB = 3.0         # 모델을 받기 전 남은 디스크가 이보다 적으면 경고

# ===== 비밀값: 환경변수 또는 .env =====
def secret(name):
    return os.environ.get(name) or None

ABSA_DIR.mkdir(parents=True, exist_ok=True)   # 옛 파이프라인 폴더(OUT_DIR 등)는 run.py가 실행할 때 만든다
