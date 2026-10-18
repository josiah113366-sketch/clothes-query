"""번역기: 번역 전용 seq2seq, 번역 LLM, Gemini, Papago. torch/transformers는 필요할 때만 불러온다
(Gemini·Papago만 쓰면 GPU 패키지가 없어도 동작)."""
import gc
import json
import re
import shutil
import time

import numpy as np
import pandas as pd
import requests
from tqdm.auto import tqdm

from . import config as C
from .text import split_chunks

LANG_CODES = {'nllb': ('eng_Latn', 'kor_Hang'), 'm2m': ('en', 'ko'), 'madlad': ('<2en>', '<2ko>'), 'marian': (None, '>>kor<<')}

LLM_INSTRUCTION = (
    'Translate the following English product review into natural Korean, the way a Korean online shopper '
    'would write a review. Preserve the sentiment exactly: keep the polarity and intensity of praise and '
    'complaints, sarcasm, hedging, and emphasis (ALL CAPS, "!!!"). Do not add, omit, soften, or explain '
    'anything. Keep brand names and sizes as they are. Output only the Korean translation.')
LABEL_PREFIX = re.compile(r'^\s*(번역|한국어|Korean|Translation)\s*[:：]\s*', re.I)


def _torch():
    import torch
    return torch


def device():
    return 'cuda' if _torch().cuda.is_available() else 'cpu'


def dtype_kw():
    """transformers 4.56부터 torch_dtype 대신 dtype을 쓴다."""
    import transformers
    v = tuple(int(x) for x in re.findall(r'\d+', transformers.__version__)[:2])
    return 'dtype' if v >= (4, 56) else 'torch_dtype'


def free_memory():
    gc.collect()
    try:
        t = _torch()
        if t.cuda.is_available():
            t.cuda.empty_cache()
    except ImportError:
        pass


def check_disk(repo_id):
    """모델을 받기 전 남은 디스크가 부족하면 경고한다 (Colab에서 디스크가 차서 모델 3개가 실패했던 문제)."""
    from huggingface_hub.constants import HF_HUB_CACHE
    free = shutil.disk_usage(HF_HUB_CACHE if __import__('os').path.exists(HF_HUB_CACHE) else '.').free / 1e9
    if free < C.MIN_FREE_GB:
        print(f'[경고] {repo_id}: 남은 디스크 {free:.1f}GB < {C.MIN_FREE_GB}GB. 받다가 실패할 수 있습니다.')
    return free


def clear_hf_cache(repo_id):
    """번역이 끝난 모델의 HF 캐시를 지워 디스크를 확보한다."""
    if not C.HF_CACHE_CLEANUP or not repo_id:
        return
    try:
        from huggingface_hub import scan_cache_dir
        info = scan_cache_dir()
        revs = [r.commit_hash for repo in info.repos if repo.repo_id == repo_id for r in repo.revisions]
        if revs:
            strat = info.delete_revisions(*revs)
            print(f'  캐시 삭제 {repo_id}: {strat.expected_freed_size_str} 확보')
            strat.execute()
    except Exception as e:
        print(f'  캐시 삭제 실패(무시): {repr(e)[:120]}')


class Seq2SeqTranslator:
    """번역 전용 모델(NLLB, M2M100, OPUS-MT, MADLAD). direction은 'en2ko' 또는 'ko2en'."""

    def __init__(self, cfg, direction='en2ko'):
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        torch = _torch()
        self.cfg, self.kind, self.dev = cfg, cfg['kind'], device()
        src, tgt = LANG_CODES[self.kind] if direction == 'en2ko' else LANG_CODES[self.kind][::-1]
        if self.kind == 'marian' and direction != 'en2ko':
            raise ValueError('OPUS-MT en-ko 모델은 영→한 전용입니다.')
        self.src, self.tgt = src, tgt
        check_disk(cfg['hf'])
        self.tok = AutoTokenizer.from_pretrained(cfg['hf'], **({'src_lang': src} if self.kind == 'nllb' else {}))
        dt = torch.float16 if (self.dev == 'cuda' and not cfg.get('fp32')) else torch.float32
        self.model = AutoModelForSeq2SeqLM.from_pretrained(cfg['hf'], **{dtype_kw(): dt}).to(self.dev).eval()
        self.gen_kwargs = {}
        if self.kind == 'nllb':
            self.gen_kwargs['forced_bos_token_id'] = self.tok.convert_tokens_to_ids(tgt)
        elif self.kind == 'm2m':
            self.tok.src_lang = src
            lid = self.tok.get_lang_id(tgt) if hasattr(self.tok, 'get_lang_id') else self.tok.convert_tokens_to_ids(f'__{tgt}__')
            self.gen_kwargs['forced_bos_token_id'] = lid

    def _prep(self, text):
        return f'{self.tgt} {text}' if self.kind in ('marian', 'madlad') else text

    def translate_texts(self, texts, desc=''):
        torch = _torch()
        order = np.argsort([len(t) for t in texts])[::-1]
        out = [''] * len(texts)
        with torch.inference_mode():
            for i in tqdm(range(0, len(texts), C.MT_BATCH), desc=desc or self.cfg['short'], leave=False):
                idx = order[i:i + C.MT_BATCH]
                enc = self.tok([self._prep(texts[j]) for j in idx], return_tensors='pt', padding=True,
                               truncation=True, max_length=512).to(self.dev)
                max_new = int(min(512, enc['input_ids'].shape[1] * 2 + 16))
                gen = self.model.generate(**enc, num_beams=C.MT_BEAMS, max_new_tokens=max_new,
                                          no_repeat_ngram_size=0, **self.gen_kwargs)
                for j, t in zip(idx, self.tok.batch_decode(gen, skip_special_tokens=True)):
                    out[j] = t.strip()
        return out

    def close(self):
        del self.model
        free_memory()
        clear_hf_cache(self.cfg['hf'])


class LLMTranslator:
    """번역 LLM (Gugugo, EXAONE, Qwen, Rosetta 등). 리뷰를 통째로 넣고 생성 결과에서 번역문만 잘라 낸다."""
    chunked = False

    def __init__(self, cfg, direction='en2ko'):
        from transformers import AutoModelForCausalLM, AutoTokenizer
        torch = _torch()
        if direction != 'en2ko':
            raise ValueError('번역 LLM은 영→한 비교에만 씁니다.')
        self.cfg, self.dev = cfg, device()
        self.n_empty_logged = 0
        trc = cfg.get('trust_remote_code', False)
        check_disk(cfg['hf'])
        self.tok = AutoTokenizer.from_pretrained(cfg['hf'], trust_remote_code=trc)
        self.tok.padding_side = 'left'
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
        kw = dict(trust_remote_code=trc)
        if cfg.get('quant') == '4bit' and self.dev == 'cuda':
            from transformers import BitsAndBytesConfig
            kw['quantization_config'] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                                                           bnb_4bit_compute_dtype=torch.float16)
            kw['device_map'] = 'auto'
            self.model = AutoModelForCausalLM.from_pretrained(cfg['hf'], **kw).eval()
        else:
            # Rosetta(Gemma 계열)는 fp16에서 값이 넘쳐 빈 출력이 나올 수 있어 bf16/fp32를 쓴다.
            if self.dev != 'cuda':
                dt = torch.float32
            else:
                dt = torch.bfloat16 if cfg.get('dtype') == 'bf16' else (torch.float32 if cfg.get('dtype') == 'fp32' else torch.float16)
            kw[dtype_kw()] = dt
            self.model = AutoModelForCausalLM.from_pretrained(cfg['hf'], **kw).to(self.dev).eval()

    def _prompt(self, text):
        if self.cfg.get('json_io'):
            text = json.dumps(text, ensure_ascii=False)
        if self.cfg.get('prompt', 'chat') == 'chat':
            system = self.cfg.get('system_prompt', LLM_INSTRUCTION)
            user = self.cfg.get('user_template', '{text}').replace('{text}', text)
            msgs = ([{'role': 'system', 'content': system}] if system else []) + [{'role': 'user', 'content': user}]
            try:
                return self.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
            except TypeError:
                return self.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        return (self.tok.bos_token or '') + self.cfg['prompt'].replace('{text}', text)

    def _clean(self, t):
        for s in self.cfg.get('stop', []):
            t = t.split(s)[0]
        t = re.sub(r'<think>.*?</think>', '', t, flags=re.S)
        t = LABEL_PREFIX.sub('', t.strip())
        if self.cfg.get('json_io'):
            try:
                v = json.loads(t)
                if isinstance(v, str):
                    return v.strip()
                if isinstance(v, dict):
                    t = ' '.join(map(str, v.values()))
            except Exception:
                pass
        return t.strip().strip('"“”').strip()

    def translate_texts(self, texts, desc=''):
        torch = _torch()
        out = [''] * len(texts)
        order = np.argsort([len(t) for t in texts])[::-1]
        dev = self.model.device
        with torch.inference_mode():
            for i in tqdm(range(0, len(texts), C.LLM_BATCH), desc=desc or self.cfg['short'], leave=False):
                idx = order[i:i + C.LLM_BATCH]
                prompts = [self._prompt(texts[j]) for j in idx]
                enc = self.tok(prompts, return_tensors='pt', padding=True, add_special_tokens=False).to(dev)
                src_len = max(len(self.tok(texts[j], add_special_tokens=False)['input_ids']) for j in idx)
                gen = self.model.generate(**enc, max_new_tokens=int(min(C.LLM_MAX_NEW_TOKENS, src_len * 3 + 32)),
                                          do_sample=False, repetition_penalty=1.05, pad_token_id=self.tok.pad_token_id)
                new_tokens = gen[:, enc['input_ids'].shape[1]:]
                for j, raw in zip(idx, self.tok.batch_decode(new_tokens, skip_special_tokens=True)):
                    out[j] = self._clean(raw)
                    if not out[j] and self.n_empty_logged < 3:     # 빈 출력 원인 추적용: 원본 생성 문자열을 남김
                        self.n_empty_logged += 1
                        print(f"  [빈 출력] {self.cfg['short']} 생성 원문: {raw!r}")
        n_empty = sum(1 for t in out if not t)
        if n_empty > len(out) * 0.5:
            print(f"  [경고] {self.cfg['short']}: {n_empty}/{len(out)}건이 빈 출력입니다. dtype/프롬프트 설정을 확인하세요.")
        return out

    def close(self):
        del self.model
        free_memory()
        clear_hf_cache(self.cfg['hf'])


class GeminiClient:
    """Gemini API를 JSON 입출력으로 부르는 공통 도우미 (번역과 별점 판정에 같이 씀)."""

    def __init__(self, model):
        from google import genai
        from google.genai import types
        key = C.secret('GEMINI_KEY')
        assert key, 'GEMINI_KEY가 없습니다. 환경변수나 .env에 설정하세요.'
        self.model, self.types = model, types
        self.client = genai.Client(api_key=key)

    def call(self, prompt, items, key, tries=5):
        for k in range(tries):
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=prompt + json.dumps(items, ensure_ascii=False),
                    config=self.types.GenerateContentConfig(response_mime_type='application/json', temperature=0))
                data = json.loads(resp.text)
                return {int(d['id']): d.get(key) for d in data if 'id' in d}
            except Exception as e:
                wait = C.GEMINI_SLEEP * (2 ** k)
                print(f'  Gemini 재시도 {k + 1}/{tries} ({type(e).__name__}): {wait:.0f}초 대기')
                time.sleep(wait)
        return {}

    def batched(self, prompt, texts, field, key, desc=''):
        out = [None] * len(texts)
        for i in tqdm(range(0, len(texts), C.GEMINI_BATCH), desc=desc, leave=False):
            items = [{'id': j, field: texts[j]} for j in range(i, min(i + C.GEMINI_BATCH, len(texts)))]
            got = self.call(prompt, items, key)
            for it in items:
                out[it['id']] = got.get(it['id'])
            time.sleep(C.GEMINI_SLEEP)
        for j in [j for j, v in enumerate(out) if v in (None, '')]:
            out[j] = self.call(prompt, [{'id': j, field: texts[j]}], key).get(j)
            time.sleep(C.GEMINI_SLEEP)
        return out


class GeminiTranslator:
    """Gemini API 번역기. 리뷰를 통째로 GEMINI_BATCH건씩 JSON으로 묶어 보낸다."""
    chunked = False
    PROMPT = (
        '다음은 아마존 패션·의류 상품 리뷰 목록입니다. 각 리뷰를 한국 온라인 쇼핑몰 리뷰처럼 자연스러운 한국어로 번역하세요.\n'
        '규칙: 의미와 감정의 세기(불만, 칭찬, 비꼼)를 그대로 유지하고, 내용을 더하거나 빼지 마세요. '
        '브랜드·모델명은 그대로 두고, 사이즈·단위는 원문 표기를 유지하세요.\n'
        '출력: [{"id": 번호, "ko": "번역문"}] 형식의 JSON 배열만 출력하세요.\n\n입력:\n')

    def __init__(self, cfg, direction='en2ko'):
        self.cfg, self.client = cfg, GeminiClient(cfg['model'])

    def translate_texts(self, texts, desc=''):
        got = self.client.batched(self.PROMPT, texts, 'en', 'ko', desc or self.cfg['short'])
        return [str(t or '').strip() for t in got]

    def close(self):
        pass


class PapagoTranslator:
    """네이버 클라우드 Papago 번역 API. PAPAGO_CLIENT_ID, PAPAGO_CLIENT_SECRET이 필요하다. 입력 글자 수만큼 요금이 나온다."""
    chunked = False
    URL = 'https://papago.apigw.ntruss.com/nmt/v1/translation'

    def __init__(self, cfg, direction='en2ko'):
        self.cfg = cfg
        self.src, self.tgt = ('en', 'ko') if direction == 'en2ko' else ('ko', 'en')
        self.headers = {'X-NCP-APIGW-API-KEY-ID': C.secret('PAPAGO_CLIENT_ID'),
                        'X-NCP-APIGW-API-KEY': C.secret('PAPAGO_CLIENT_SECRET'), 'Content-Type': 'application/json'}

    def _one(self, text, tries=5):
        for k in range(tries):
            try:
                r = requests.post(self.URL, headers=self.headers, timeout=30,
                                  json={'source': self.src, 'target': self.tgt, 'text': text[:5000]})
                r.raise_for_status()
                j = r.json()
                res = j.get('message', {}).get('result', j)
                return str(res.get('translatedText', '')).strip()
            except Exception as e:
                print(f'  Papago 재시도 {k + 1}/{tries} ({type(e).__name__}): {2 ** k}초 대기')
                time.sleep(2 ** k)
        return ''

    def translate_texts(self, texts, desc=''):
        return [self._one(t) for t in tqdm(texts, desc=desc or self.cfg['short'], leave=False)]

    def close(self):
        pass


def make_translator(cfg, direction='en2ko'):
    kind = cfg['kind']
    if kind == 'gemini':
        return GeminiTranslator(cfg, direction)
    if kind == 'papago':
        return PapagoTranslator(cfg, direction)
    if kind == 'llm':
        return LLMTranslator(cfg, direction)
    return Seq2SeqTranslator(cfg, direction)


def translate_reviews(translator, texts):
    """번역 전용 모델은 덩어리로 나눠 번역한 뒤 이어 붙이고, LLM·API는 리뷰를 통째로 번역한다."""
    if not getattr(translator, 'chunked', True):
        return translator.translate_texts(texts)
    pieces, owner = [], []
    for i, t in enumerate(texts):
        for c in split_chunks(t):
            pieces.append(c); owner.append(i)
    done = translator.translate_texts(pieces)
    out = [[] for _ in texts]
    for i, t in zip(owner, done):
        out[i].append(t)
    return [' '.join(x).strip() for x in out]


def get_translations(cfg, frame, desc=''):
    """frame(review_id, src_en)의 번역문을 캐시에서 꺼내고, 없는 것만 번역해 캐시에 더한다.
    캐시에 빈 번역만 있는 건(Rosetta 사례)은 번역된 것으로 치지 않고 다시 번역한다.
    반환: review_id 순서에 맞춘 번역문 Series, 새로 번역한 건수, 걸린 시간(초)"""
    path = C.TRANS_DIR / f"{cfg['short']}.parquet"
    cache = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=['review_id', 'ko'])
    cache = cache[cache['ko'].astype(str).str.strip() != '']
    have = set(cache['review_id'])
    todo = frame[~frame['review_id'].isin(have)]
    secs = 0.0
    if len(todo):
        print(f"[{cfg['short']}] 번역 {len(todo):,}건 {desc}")
        tr = make_translator(cfg)
        try:
            for s in range(0, len(todo), C.SAVE_EVERY):
                part = todo.iloc[s:s + C.SAVE_EVERY]
                t0 = time.time()
                ko = translate_reviews(tr, part['src_en'].tolist())
                secs += time.time() - t0
                cache = pd.concat([cache, pd.DataFrame({'review_id': part['review_id'].values, 'ko': ko})], ignore_index=True)
                cache.to_parquet(path, index=False)
                print(f'  저장 {min(s + C.SAVE_EVERY, len(todo)):,}/{len(todo):,}')
        finally:
            tr.close()
    ko = frame['review_id'].map(cache.drop_duplicates('review_id', keep='last').set_index('review_id')['ko'])
    return ko.fillna(''), len(todo), secs
