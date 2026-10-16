"""AI Hub 패션 속성 기반 감성분석 데이터(aihub_dataset/, git 제외)로 로컬 LoRA 모델을 채점한다. 외부 전송 없음.
AI Hub 속성은 상품 속성뿐이라 우리 10개 속성 중 6개만 대응한다. 매핑이 애매한 속성(착용감·기능·무게 등)이 있는 리뷰는 제외하고,
정답이 없는 속성(세탁·배송·포장·CS)에 대한 모델 예측은 채점에서 뺀다.
실행: HF_HUB_OFFLINE=1 python eval_aihub.py --n 500 --models lora:2.4b_v0 lora:2.4b_v1"""
import argparse
import json
import time

import torch
from peft import PeftModel

import llm_probe as P
import lora_train as L
from review_analysis import absa as A, config as C

from review_analysis.aihub import COVERED, load


def load_eval(n, seed=C.SEED):
    return load('Validation', n, seed)


def score(gold, pred):
    pred = [{k: v for k, v in p.items() if k in COVERED} for p in pred]
    r = A.compare(gold, pred)
    r['완전일치'] = round(sum(g == p for g, p in zip(gold, pred)) / len(gold), 3)
    return r, A.per_aspect(gold, pred).loc[COVERED]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=500)
    ap.add_argument('--models', nargs='+', default=['lora:2.4b_v0', 'lora:2.4b_v1'])
    a = ap.parse_args()
    rows, usable, skipped = load_eval(a.n)
    print(f'사용 가능 {usable}건 중 {len(rows)}건 평가, 제외 {dict(skipped)}', flush=True)
    texts, gold = [r['text'] for r in rows], [r['gold'] for r in rows]
    out = C.ROOT / 'aihub_work' / 'eval_aihub.json'
    res = json.loads(out.read_text(encoding='utf-8')) if out.exists() else {}   # 이전 결과 보존
    res.update({'평가건수': len(rows), '사용가능': usable})
    for spec in a.models:
        name = spec.split(':')[1]
        tok, model = P.load(name.split('_')[0], 'bf16')
        model = PeftModel.from_pretrained(model, C.ROOT / 'private' / 'lora' / name).eval()
        raw, t = [], time.time()
        for s in range(0, len(texts), 8):
            raw += P.generate(tok, model, [L.SHORT + x for x in texts[s:s + 8]])
            if (s // 8) % 10 == 0:
                print(f'  {spec} {len(raw)}/{len(texts)}', flush=True)
        pred = [P.parse(r) or {} for r in raw]
        m, per = score(gold, pred)
        res[spec] = dict(전체=m, 속성별=json.loads(per.to_json(orient='index', force_ascii=False)), 파싱실패=sum(P.parse(r) is None for r in raw), 초=round(time.time() - t))
        print(spec, json.dumps(m, ensure_ascii=False), flush=True)
        print(per.to_string(), flush=True)
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
        del model
        torch.cuda.empty_cache()
    print('완료')


if __name__ == '__main__':
    main()
