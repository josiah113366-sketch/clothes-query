"""로컬 LLM(EXAONE 3.5) 시험: 로드 확인(load)과 ABSA 속성 추출 평가(absa).
평가 데이터는 합성 한글 리뷰(data/absa_pilot)만 쓴다. private/ 의 실제 후기는 읽지 않는다.
실행: python llm_probe.py load --model 2.4b
      python llm_probe.py absa --model 7.8b --quant 4bit --n 200"""
import argparse
import json
import re
import sys
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from review_analysis import absa, config as C

# 2026-02 이후 원격 코드는 Transformers v5용이라 4.53에서 import 오류가 난다. 2024-12 리비전으로 고정한다.
MODELS = {
    '2.4b': ('LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct', 'e949c91dec'),
    '7.8b': ('LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct', '0ff6b5ec7c'),
}
# 한 리뷰씩 넣는 프롬프트: 배열 대신 {"aspects": [...]} 객체 하나만 출력하게 한다
PROMPT = absa.PROMPT.replace(
    '[{"id": 번호, "aspects": [{"aspect": "속성", "sentiment": "감성"}]}] 형식의 JSON 배열만',
    '{"aspects": [{"aspect": "속성", "sentiment": "감성"}]} 형식의 JSON 객체 하나만').replace('리뷰 목록', '리뷰')


def load(key, quant):
    name, rev = MODELS[key]
    kw = dict(trust_remote_code=True, revision=rev, device_map='cuda')
    if quant == '4bit':
        kw['quantization_config'] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                                                       bnb_4bit_compute_dtype=torch.bfloat16)
    else:
        kw['torch_dtype'] = torch.bfloat16
    t = time.time()
    tok = AutoTokenizer.from_pretrained(name, trust_remote_code=True, revision=rev, padding_side='left')
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(name, **kw).eval()
    print(f'로드 성공 {name}@{rev} {quant} {time.time() - t:.0f}초, VRAM {torch.cuda.memory_allocated() / 1e9:.2f}GB', flush=True)
    return tok, model


def generate(tok, model, prompts, max_new=160):
    msgs = [tok.apply_chat_template([{'role': 'user', 'content': p}], add_generation_prompt=True, tokenize=False) for p in prompts]
    enc = tok(msgs, return_tensors='pt', padding=True, add_special_tokens=False).to('cuda')
    with torch.no_grad():
        out = model.generate(**enc, max_new_tokens=max_new, do_sample=False, pad_token_id=tok.pad_token_id)
    return [tok.decode(o[enc.input_ids.shape[1]:], skip_special_tokens=True) for o in out]


def parse(text):
    m = re.search(r'\{.*\}', text, re.S)
    try:
        return absa._parse([json.loads(m.group(0)).get('aspects')]) [0]
    except Exception:
        return None


def cmd_load(a):
    tok, model = load(a.model, a.quant)
    torch.cuda.reset_peak_memory_stats()
    generate(tok, model, ['안녕'], 4)
    t = time.time()
    ids = tok(['배송은 빨랐는데 포장이 엉망이었어요.'], return_tensors='pt').to('cuda')
    out = model.generate(**ids, max_new_tokens=64, min_new_tokens=64, do_sample=False)
    n = out.shape[1] - ids.input_ids.shape[1]
    print(f'{n}토큰 {n / (time.time() - t):.1f} tok/s, 피크 VRAM {torch.cuda.max_memory_allocated() / 1e9:.2f}GB')


def cmd_absa(a):
    # 정답 = 합성 리뷰 지시서, 대상 = Gemini 재추출이 지시와 일치한 항목(라벨이 믿을 만한 것)만
    synth = [d for d in json.loads((absa.OUT / f'synth_ko.{absa.SYNTH_VERSION}.json').read_text(encoding='utf-8')) if d['review']]
    pred_g = json.loads((absa.OUT / f'synth_pred_{len(synth)}.{absa.VERSION}.json').read_text(encoding='utf-8'))
    gold_all = [{x['aspect']: x['sentiment'] for x in d['aspects']} for d in synth]
    idx = [i for i in range(len(synth)) if gold_all[i] == pred_g[i]][:a.n]
    texts, gold = [synth[i]['review'] for i in idx], [gold_all[i] for i in idx]
    tok, model = load(a.model, a.quant)
    torch.cuda.reset_peak_memory_stats()
    raw, t = [], time.time()
    for s in range(0, len(texts), a.batch):
        raw += generate(tok, model, [PROMPT + f'리뷰: {x}' for x in texts[s:s + a.batch]])
        print(f'{len(raw)}/{len(texts)} {time.time() - t:.0f}초', flush=True)
    pred = [parse(r) or {} for r in raw]
    fail = sum(parse(r) is None for r in raw)
    res = absa.compare(gold, pred)
    res.update(리뷰수=len(texts), 파싱실패=fail, 초=round(time.time() - t), 피크VRAM_GB=round(torch.cuda.max_memory_allocated() / 1e9, 2),
               완전일치=round(sum(g == p for g, p in zip(gold, pred)) / len(texts), 3))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    print(absa.per_aspect(gold, pred).to_string())
    out = absa.OUT / 'llm_local'
    out.mkdir(parents=True, exist_ok=True)
    (out / f'{a.model}_{a.quant}.json').write_text(json.dumps(dict(result=res, pred=pred, raw=raw), ensure_ascii=False), encoding='utf-8')


def cmd_human(a):
    """사람 평가셋(private/, 실제 후기 원문)을 로컬 GPU에서만 평가한다. 외부 전송 없음. 결과는 private/에 저장하고 출력은 지표만."""
    ids, texts, gold = absa.load_eval_gold(a.csv)
    tok, model = load(a.model, a.quant)
    raw = generate(tok, model, [PROMPT + f'리뷰: {x}' for x in texts])
    pred = [parse(r) or {} for r in raw]
    res = absa.compare(gold, pred)
    res.update(리뷰수=len(texts), 파싱실패=sum(parse(r) is None for r in raw),
               완전일치=round(sum(g == p for g, p in zip(gold, pred)) / len(texts), 3))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    print(absa.per_aspect(gold, pred).to_string())
    out = C.ROOT / 'private' if hasattr(C, 'ROOT') else absa.OUT.parents[1] / 'private'
    (out / f'llm_local_human_{a.model}_{a.quant}.json').write_text(
        json.dumps(dict(result=res, ids=ids, gold=gold, pred=pred, raw=raw), ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['load', 'absa', 'human'])
    ap.add_argument('--csv', default='private/absa_eval_human_real.csv')
    ap.add_argument('--model', choices=list(MODELS), default='2.4b')
    ap.add_argument('--quant', choices=['bf16', '4bit'], default='bf16')
    ap.add_argument('--n', type=int, default=200)
    ap.add_argument('--batch', type=int, default=8)
    a = ap.parse_args()
    {'load': cmd_load, 'absa': cmd_absa, 'human': cmd_human}[a.cmd](a)
