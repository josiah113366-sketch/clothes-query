"""평가 전용 합성 리뷰(학습과 별개 세트)를 만들고 로컬 모델들을 채점한다. 사람 평가셋은 쓰지 않는다.
정답은 지시서. 전체와, Gemini 재추출이 지시서와 일치한 부분집합(라벨이 더 믿을 만함) 두 기준으로 보고한다.
실행: HF_HUB_OFFLINE=1 python eval_synth.py --n 500 --models prompt2.4b lora:2.4b_v0 lora:2.4b_v1 prompt7.8b"""
import argparse
import json
import time

import torch
from peft import PeftModel

import llm_probe as P
import lora_train as L
from review_analysis import absa as A, absa_synth2 as S, config as C

NAME = 'synth_eval_v2'


def score(gold, pred, idx):
    g, p = [gold[i] for i in idx], [pred[i] for i in idx]
    r = A.compare(g, p)
    r.update(리뷰수=len(idx), 완전일치=round(sum(x == y for x, y in zip(g, p)) / len(idx), 3))
    return r


def run(spec, texts):
    kind, name = spec.split(':') if ':' in spec else (spec[:6], spec[6:])
    if kind == 'prompt':
        tok, model = P.load(name.lower(), '4bit' if name.startswith('7.8') else 'bf16')
        raw = []
        for s in range(0, len(texts), 4 if name.startswith('7.8') else 8):
            raw += P.generate(tok, model, [P.PROMPT + f'리뷰: {x}' for x in texts[s:s + (4 if name.startswith("7.8") else 8)]])
            print(f'  {spec} {len(raw)}/{len(texts)}', flush=True)
    else:
        base = name.split('_')[0]
        tok, model = P.load(base, 'bf16')
        model = PeftModel.from_pretrained(model, C.ROOT / 'private' / 'lora' / name).eval()
        raw = []
        for s in range(0, len(texts), 8):
            raw += P.generate(tok, model, [L.SHORT + x for x in texts[s:s + 8]])
            print(f'  {spec} {len(raw)}/{len(texts)}', flush=True)
    del model
    torch.cuda.empty_cache()
    return [P.parse(r) or {} for r in raw], sum(P.parse(r) is None for r in raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=500)
    ap.add_argument('--models', nargs='+', default=['prompt2.4b', 'lora:2.4b_v0', 'lora:2.4b_v1'])
    a = ap.parse_args()
    d = S.synth_reviews(a.n, name=NAME, seed=C.SEED + 100)
    data, gold, gem, clean = S.validate(d, name=f'{NAME}_pred')
    # 학습 세트와 후기 문구가 같은 것은 평가에서 뺀다
    train_txt = {x['review'] for x in json.loads((A.OUT / 'synth_ko.v2.json').read_text(encoding='utf-8'))}
    train_txt |= {x['review'] for x in json.loads((A.OUT / 'synth_ko.v1.json').read_text(encoding='utf-8'))}
    keep = [i for i, x in enumerate(data) if x['review'] not in train_txt]
    cs = set(clean)
    sub = [i for i in keep if i in cs]
    print(f'평가 {len(data)}건 중 학습과 중복 제외 {len(keep)}건, Gemini 일치 부분집합 {len(sub)}건', flush=True)
    texts = [x['review'] for x in data]
    outp = A.OUT / 'llm_local' / 'synth_eval_v2.json'
    res = json.loads(outp.read_text(encoding='utf-8')) if outp.exists() else {}   # 이전 결과 보존
    res['Gemini(재추출)'] = dict(전체=score(gold, gem, keep), 일치부분집합='자기 자신과 일치 기준이라 해당 없음')
    for spec in a.models:
        t = time.time()
        pred, fail = run(spec, texts)
        res[spec] = dict(전체=score(gold, pred, keep), 일치부분집합=score(gold, pred, sub), 파싱실패=fail, 초=round(time.time() - t))
        print(spec, json.dumps(res[spec], ensure_ascii=False), flush=True)
        per = A.per_aspect([gold[i] for i in keep], [pred[i] for i in keep])
        res[spec]['속성별_전체'] = json.loads(per.to_json(orient='index', force_ascii=False))
        outp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print('완료')


if __name__ == '__main__':
    main()
