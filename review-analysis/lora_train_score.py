"""EXAONE-3.5 LoRA — 점수(−2~+2) 방식 파일럿. 3분류 학습(lora_train.py)과 분리된 별도 스크립트·어댑터(private/lora/2.4b_score_*).
학습: 점수가 달린 한글 합성(검증 통과분 70%) + AI Hub 임시(silver) 점수 후기. 평가: 합성 test + (있으면) 사람 점수 평가셋.
실행: HF_HUB_OFFLINE=1 python lora_train_score.py --aihub 3000 --tag s1"""
import argparse
import json
import random
import time

import torch
from peft import LoraConfig, get_peft_model

import llm_probe as P
from review_analysis import absa as A, absa_synth_score as SS, config as C, schema3 as S3, score as SC


def encode(tok, text, gold, maxlen=640):
    p = tok.apply_chat_template([{'role': 'user', 'content': SC.SHORT_SCORE + text}], add_generation_prompt=True, tokenize=False)
    pi = tok(p, add_special_tokens=False).input_ids
    ti = tok(SC.target_score(gold), add_special_tokens=False).input_ids + [tok.eos_token_id]
    pi = pi[-(maxlen - len(ti)):] if len(pi) + len(ti) > maxlen else pi
    return pi + ti, [-100] * len(pi) + ti


def infer(tok, model, texts, bs=8):
    raw = []
    for s in range(0, len(texts), bs):
        raw += P.generate(tok, model, [SC.SHORT_SCORE + x for x in texts[s:s + bs]])
    parsed = [SC.parse_score(r) for r in raw]
    return [p or {} for p in parsed], sum(p is None for p in parsed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='2.4b')
    ap.add_argument('--aihub', type=int, default=3000)
    ap.add_argument('--epochs', type=int, default=2)
    ap.add_argument('--lr', type=float, default=1e-4)
    ap.add_argument('--bs', type=int, default=4)
    ap.add_argument('--r', type=int, default=32)
    ap.add_argument('--tag', default='s1')
    ap.add_argument('--relabel', action='store_true', help='합성 학습 데이터에 정답 보정(synth_relabel) 적용')
    ap.add_argument('--collected-train', action='store_true', help='직접 수집한 후기 중 절반(heldout.train_ids)을 학습에 추가(×UPSAMPLE). 나머지는 평가 전용')
    a = ap.parse_args()
    S3.set_aspects(True)

    d = json.loads((A.OUT / 'synth_score.v2.json').read_text(encoding='utf-8'))
    data, gold, pred, clean = SS.validate(d, 'synth_score_pred.v2')
    if a.relabel:   # 정답 보정(반어=−2, 문제없음=+1, 뜯어짐=품질) — 원본 파일은 그대로 두고 학습에서만 적용
        from review_analysis import synth_relabel as RL
        gold, clean = RL.train_view(data, gold, pred, clean, 'score', 'synth_score.v2')
    items = [(data[i]['review'], gold[i]) for i in clean]
    random.Random(C.SEED).shuffle(items)
    n_tr, n_va = int(0.7 * len(items)), int(0.15 * len(items))
    train, test = items[:n_tr], items[n_tr + n_va:]
    rows, st = SC.load_aihub_scored('Training')
    ah = SC.select_train(rows, a.aihub)
    train += [(r['text'], r['gold']) for r in ah]
    hold = set()
    if a.collected_train:
        from review_analysis import heldout as H
        hold = H.train_ids()
        hi, ht, hg = SC.load_score_gold(C.ROOT / 'private' / 'absa_score_eval_human_real.csv')
        ct = [(t, g) for i, t, g in zip(hi, ht, hg) if i in hold]
        train += ct * H.UPSAMPLE
        print(f'수집 후기 학습 {len(ct)}건 ×{H.UPSAMPLE}')
    print(f'학습 {len(train)} (합성 {n_tr} + AI Hub silver {len(ah)}) / 합성 test {len(test)} / AI Hub 사용 가능 {len(rows)}', flush=True)

    tok, model = P.load(a.model, 'bf16')
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(r=a.r, lora_alpha=2 * a.r, lora_dropout=0.05, task_type='CAUSAL_LM',
                                             target_modules=['q_proj', 'k_proj', 'v_proj', 'out_proj', 'c_fc_0', 'c_fc_1', 'c_proj']))
    model.print_trainable_parameters()
    enc = [encode(tok, t, g) for t, g in train]
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)
    steps = a.epochs * ((len(enc) + a.bs - 1) // a.bs)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / 20) * max(0.05, 1 - s / steps))
    model.train()
    t0, step, rng = time.time(), 0, random.Random(C.SEED)
    out = C.ROOT / 'private' / 'lora' / f'{a.model}_score_{a.tag}'
    for ep in range(a.epochs):
        rng.shuffle(enc)
        for s in range(0, len(enc), a.bs):
            b = enc[s:s + a.bs]
            L = max(len(x[0]) for x in b)
            ids = torch.tensor([x[0] + [tok.pad_token_id] * (L - len(x[0])) for x in b]).cuda()
            lab = torch.tensor([x[1] + [-100] * (L - len(x[1])) for x in b]).cuda()
            att = torch.tensor([[1] * len(x[0]) + [0] * (L - len(x[0])) for x in b]).cuda()
            loss = model(input_ids=ids, attention_mask=att, labels=lab).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); opt.zero_grad()
            step += 1
            if step % 20 == 0:
                print(f'ep{ep} step {step}/{steps} loss {loss.item():.3f} {time.time() - t0:.0f}초', flush=True)
        if ep + 1 < a.epochs:
            ck = out.with_name(out.name + f'_ep{ep + 1}')
            ck.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(ck)
    model.eval()
    model.config.use_cache = True
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out)

    record = dict(tag=a.tag, 학습건수=len(train), aihub_silver=len(ah), collected_train=a.collected_train, 에폭=a.epochs, lr=a.lr, r=a.r, 학습초=round(time.time() - t0))
    pr, fail = infer(tok, model, [t for t, _ in test])
    record['합성test'] = SC.metrics([g for _, g in test], [{k: v for k, v in p.items() if k != S3.NEW} for p in pr], keys=[k for k in S3.ASPECTS3 if k != S3.NEW])
    record['합성test']['파싱실패'] = fail
    print('[합성 test]', json.dumps(record['합성test'], ensure_ascii=False), flush=True)
    try:
        ids, texts, hgold = SC.load_score_gold(C.ROOT / 'private' / 'absa_score_eval_human_real.csv')
        if hold:
            k = [j for j, i in enumerate(ids) if i not in hold]
            texts, hgold = [texts[j] for j in k], [hgold[j] for j in k]
        hp, hfail = infer(tok, model, texts)
        record['사람'] = SC.metrics(hgold, hp)
        print('[사람 점수 평가셋]', json.dumps(record['사람'], ensure_ascii=False), flush=True)
    except AssertionError as e:
        print('[사람 점수 평가셋 생략] 아직 작성 중:', str(e)[:80], flush=True)
    path = A.OUT / 'llm_local' / 'score_runs.json'
    runs = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    path.write_text(json.dumps(runs + [record], ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
