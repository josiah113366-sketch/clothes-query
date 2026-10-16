"""v3 평가: ① AI Hub Validation(v3 변환, 코디 제외) ② 합성 500건 ③ 사람 평가셋. 모두 로컬. Gemini는 쓰지 않는다.
모델 이름에 'v3'가 들어 있으면 11개 속성 프롬프트를 쓰고, 합성·사람 평가에서는 새 속성(활용성·사용감) 예측을 채점에서 뺀다.
AI Hub 평가는 이전 모델과 비교할 수 있도록 공통 6개 속성만으로도 채점한다.
실행: HF_HUB_OFFLINE=1 python eval_v3.py --models 2.4b_v3 2.4b_v3_ep1 2.4b_v2 --sets aihub human synth"""
import argparse
import json
import time

import torch
from peft import PeftModel

import llm_probe as P
import lora_train as L
from review_analysis import absa as A, absa_synth2 as S2, config as C, schema3 as S3

COMMON6 = ['재질·촉감', '사이즈·핏', '색상·디자인', '품질·내구성', '가격·가성비', '냄새']
OUT = C.ROOT / 'aihub_work' / 'eval_v3.json'
N_OLD = 30   # 기존 사람 평가셋(EX1~EX30) 건수. 이후는 2026-10-14에 추가한 직접 작성 후기


def only(d, keys):
    return {k: v for k, v in d.items() if k in keys}


def metr(gold, pred, keys=None):
    if keys:
        gold, pred = [only(g, keys) for g in gold], [only(p, keys) for p in pred]
    r = A.compare(gold, pred)
    r['완전일치'] = round(sum(g == p for g, p in zip(gold, pred)) / len(gold), 3)
    return r


def per(gold, pred, keys):
    d = A.per_aspect(gold, pred)
    return json.loads(d.loc[[k for k in keys if k in d.index]].to_json(orient='index', force_ascii=False))


def infer(tok, model, short, texts):
    raw = []
    for s in range(0, len(texts), 8):
        raw += P.generate(tok, model, [short + x for x in texts[s:s + 8]])
    return [P.parse(r) or {} for r in raw], sum(P.parse(r) is None for r in raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', nargs='+', required=True)
    ap.add_argument('--sets', nargs='+', default=['aihub', 'human', 'synth'])
    ap.add_argument('--n', type=int, default=500)
    ap.add_argument('--holdout', action='store_true', help='수집 후기 중 학습에 쓴 절반(heldout.train_ids)을 사람 평가에서 뺀다')
    ap.add_argument('--tag', default='', help='결과 키 접미사')
    a = ap.parse_args()
    # 평가셋
    vrows, vst = S3.load('Validation')
    ev = vrows[:a.n]
    S3.set_aspects(True)   # 평가셋 정답에 11번째 속성이 있어서 로드할 때는 11개를 허용한다 (모델마다 아래에서 다시 설정)
    hids, htexts, hgold = A.load_eval_gold(C.ROOT / 'private' / 'absa_eval_human_real.csv')
    if a.holdout:
        from review_analysis import heldout as H
        hold = H.train_ids()
        k = [j for j, i in enumerate(hids) if i not in hold]
        hids, htexts, hgold = [hids[j] for j in k], [htexts[j] for j in k], [hgold[j] for j in k]
    d = json.loads((A.OUT / 'synth_eval_v2.json').read_text(encoding='utf-8'))
    sdata, sgold, _, sclean = S2.validate(d, name='synth_eval_v2_pred')
    train_txt = {x['review'] for f in ('synth_ko.v1.json', 'synth_ko.v2.json') for x in json.loads((A.OUT / f).read_text(encoding='utf-8'))}
    keep = [i for i, x in enumerate(sdata) if x['review'] not in train_txt]
    print(f'AI Hub Validation(v3) {len(ev)}건 / 사용 가능 {len(vrows)}건 {dict(vst)}; 사람 {len(hids)}건; 합성 {len(keep)}건', flush=True)
    res = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
    for name in a.models:
        v3 = 'v3' in name
        S3.set_aspects(v3)
        short = S3.SHORT3 if v3 else L.SHORT
        tok, model = P.load('2.4b', 'bf16')
        model = PeftModel.from_pretrained(model, C.ROOT / 'private' / 'lora' / name).eval()
        r = res.setdefault(name + a.tag, {})
        if 'aihub' in a.sets:
            t = time.time()
            pred, fail = infer(tok, model, short, [x['text'] for x in ev])
            gold = [x['gold'] for x in ev]
            r['aihub_공통6'] = dict(전체=metr(gold, pred, COMMON6), 속성별=per([only(g, COMMON6) for g in gold], [only(p, COMMON6) for p in pred], COMMON6), 파싱실패=fail)
            if v3:
                r['aihub_전체11'] = dict(전체=metr(gold, pred), 속성별=per(gold, pred, S3.ASPECTS3))
            print(name, 'AI Hub', json.dumps(r['aihub_공통6']['전체'], ensure_ascii=False), '' if not v3 else json.dumps(r['aihub_전체11']['전체'], ensure_ascii=False), f'{time.time() - t:.0f}초', flush=True)
            json.dump(dict(gold=gold, pred=pred), open(C.ROOT / 'aihub_work' / f'preds_v3eval_{name}.json', 'w', encoding='utf-8'), ensure_ascii=False)
        if 'human' in a.sets:
            pred, fail = infer(tok, model, short, htexts)
            # 기존 30건(EX1~EX30)의 3분류 정답에는 활용성·사용감이 없어서 그 속성은 채점에서 뺀다. 2026-10-14에 추가한 후기(EX31~)는 정답에 있으므로 v3 계열은 포함한다
            no_new = [k for k in A.ASPECTS if k != S3.NEW]
            hg, pred = [], [p for p in pred]
            for i, (g0, p0) in enumerate(zip(hgold, pred)):
                keys = no_new if (not v3 or i < N_OLD) else list(S3.ASPECTS3)
                hg.append(only(g0, keys)); pred[i] = only(p0, keys)
            r['사람'] = dict(전체=metr(hg, pred), 기존30=metr(hg[:N_OLD], pred[:N_OLD]), 신규=metr(hg[N_OLD:], pred[N_OLD:]), 파싱실패=fail, 건수=len(hids))
            json_gold = hg
            print(name, '사람', json.dumps(r['사람']['전체'], ensure_ascii=False), flush=True)
            json.dump(dict(ids=hids, gold=json_gold, pred=pred), open(C.ROOT / 'private' / f'human_pred_{name}{a.tag}.json', 'w', encoding='utf-8'), ensure_ascii=False)
        if 'synth' in a.sets:
            t = time.time()
            texts = [sdata[i]['review'] for i in keep]
            pred, fail = infer(tok, model, short, texts)
            pred = [only(p, [k for k in A.ASPECTS if k != S3.NEW]) for p in pred]
            g = [sgold[i] for i in keep]
            sub = [j for j, i in enumerate(keep) if i in set(sclean)]
            r['합성500'] = dict(전체=metr(g, pred), 일치부분집합=metr([g[j] for j in sub], [pred[j] for j in sub]), 파싱실패=fail)
            from review_analysis import synth_relabel as RL   # 정답 보정(반어=부정, 문제없음=긍정, 뜯어짐=품질)을 같은 예측에 적용해 따로 저장
            fixed, _ = RL.apply(sdata, sgold, '3class', 'synth_eval_v2')
            gfix = [fixed[i] for i in keep]
            r['합성500_보정'] = dict(전체=metr(gfix, pred))
            print(name, '합성_보정', json.dumps(r['합성500_보정']['전체'], ensure_ascii=False), flush=True)
            print(name, '합성', json.dumps(r['합성500']['전체'], ensure_ascii=False), f'{time.time() - t:.0f}초', flush=True)
        OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
        del model
        torch.cuda.empty_cache()
    print('완료')


if __name__ == '__main__':
    main()
