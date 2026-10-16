"""점수(−2~+2) 방식 평가: ① 점수 합성 평가셋 500건 ② AI Hub Validation(임시 silver 점수, 참고용) ③ 사람 점수 평가셋(작성이 끝나야 함).
모두 로컬. Gemini는 쓰지 않는다. 새 속성(활용성·사용감)은 정답이 없는 평가셋(합성·사람)에서는 예측을 채점에서 뺀다.
실행: HF_HUB_OFFLINE=1 python evaluate_score.py --models 2.4b_score_s1 --sets synth aihub human"""
import argparse
import json
import time

import torch
from peft import PeftModel

import llm_probe as P
from lora_train_score import infer
from review_analysis import absa as A, absa_synth_score as SS, config as C, schema3 as S3, score as SC

OUT = C.ROOT / 'aihub_work' / 'score_eval.json'
NO_NEW = [k for k in S3.ASPECTS3 if k != S3.NEW]


def per_aspect(gold, pred, keys):
    rows = {}
    for k in keys:
        g = [{k: x[k]} for x in gold if k in x]
        n = len(g)
        both = [(x[k], p[k]) for x, p in zip(gold, pred) if k in x and k in p]
        rows[k] = dict(정답수=n, 탐지재현율=round(len(both) / n, 3) if n else None,
                       MAE=round(sum(abs(a - b) for a, b in both) / len(both), 3) if both else None)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', nargs='+', required=True)
    ap.add_argument('--sets', nargs='+', default=['synth', 'aihub', 'human'])
    ap.add_argument('--n', type=int, default=500)
    ap.add_argument('--holdout', action='store_true', help='수집 후기 중 학습에 쓴 절반(heldout.train_ids)을 사람 평가에서 뺀다')
    ap.add_argument('--tag', default='', help='결과 키 접미사')
    a = ap.parse_args()
    S3.set_aspects(True)
    res = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
    sets = {}
    if 'synth' in a.sets:
        d = json.loads((A.OUT / 'synth_score_eval.v2.json').read_text(encoding='utf-8'))
        data, gold, _, clean = SS.validate(d, 'synth_score_eval_pred.v2')
        tr = {x['review'] for x in json.loads((A.OUT / 'synth_score.v2.json').read_text(encoding='utf-8'))}
        keep = [i for i, x in enumerate(data) if x['review'] not in tr]
        sets['synth'] = ([data[i]['review'] for i in keep], [gold[i] for i in keep], [j for j, i in enumerate(keep) if i in set(clean)])
        # 정답 보정(반어=부정, 문제없음=+1, 뜯어짐=품질): 같은 예측을 보정 정답으로도 채점해 따로 저장한다
        from review_analysis import synth_relabel as RL
        fixed, _ = RL.apply(data, gold, 'score', 'synth_score_eval.v2')
        corrected = [fixed[i] for i in keep]
    if 'aihub' in a.sets:
        rows, _ = SC.load_aihub_scored('Validation')
        rows = rows[:a.n]
        sets['aihub'] = ([r['text'] for r in rows], [r['gold'] for r in rows], None)
    if 'human' in a.sets:
        try:
            ids, texts, hg = SC.load_score_gold(C.ROOT / 'private' / 'absa_score_eval_human_real.csv')
            if a.holdout:
                from review_analysis import heldout as H
                hold = H.train_ids()
                k = [j for j, i in enumerate(ids) if i not in hold]
                texts, hg = [texts[j] for j in k], [hg[j] for j in k]
            sets['human'] = (texts, hg, None)
        except AssertionError as e:
            print('[사람 점수 평가셋 생략]', str(e)[:120], flush=True)
    for name in a.models:
        tok, model = P.load('2.4b', 'bf16')
        model = PeftModel.from_pretrained(model, C.ROOT / 'private' / 'lora' / name).eval()
        r = res.setdefault(name + a.tag, {})
        for sname, (texts, gold, clean_idx) in sets.items():
            t = time.time()
            pred, fail = infer(tok, model, texts)
            keys = None if sname in ('aihub', 'human') else NO_NEW   # 사람 점수 평가셋에는 활용성·사용감 정답이 있다
            if keys:
                pred = [{k: v for k, v in p.items() if k in keys} for p in pred]
            m = SC.metrics(gold, pred, keys)
            m['파싱실패'] = fail
            r[sname] = dict(전체=m, 속성별=per_aspect(gold, pred, keys or S3.ASPECTS3))
            if clean_idx is not None:
                r[sname]['일치부분집합'] = SC.metrics([gold[j] for j in clean_idx], [pred[j] for j in clean_idx], keys)
            if sname == 'human':   # 기존 30건(EX1~EX30)과 2026-10-14에 추가한 직접 작성 후기(EX31~)를 나눠서도 본다
                r['human_기존30'] = dict(전체=SC.metrics(gold[:30], pred[:30], keys))
                r['human_신규'] = dict(전체=SC.metrics(gold[30:], pred[30:], keys))
                print(name, 'human_기존30', json.dumps(r['human_기존30']['전체'], ensure_ascii=False), flush=True)
                print(name, 'human_신규', json.dumps(r['human_신규']['전체'], ensure_ascii=False), flush=True)
            if sname == 'synth':
                r['synth_보정'] = dict(전체=SC.metrics(corrected, pred, keys), 속성별=per_aspect(corrected, pred, keys))
                print(name, 'synth_보정', json.dumps(r['synth_보정']['전체'], ensure_ascii=False), flush=True)
            print(name, sname, json.dumps(m, ensure_ascii=False), f'{time.time() - t:.0f}초', flush=True)
            if sname == 'human':
                json.dump(dict(gold=gold, pred=pred), open(C.ROOT / 'private' / f'score_human_pred_{name}{a.tag}.json', 'w', encoding='utf-8'), ensure_ascii=False)
            OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
        del model
        torch.cuda.empty_cache()
    print('완료')


if __name__ == '__main__':
    main()
