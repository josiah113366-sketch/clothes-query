"""EXAONE-3.5 LoRA 파인튜닝(ABSA 속성·감성 추출). 이 PC의 GPU에서 로컬로만 학습한다(외부 전송 없음).
학습 데이터: 한글 합성 리뷰(검증 통과분, absa-train과 같은 70/15/15 분할) + 선택적으로 영어 아마존(Gemini 라벨, 캐시).
평가: 같은 합성 test + 사람 평가셋(private/, 평가 전용·학습에 쓰지 않음).
어댑터는 private/lora/ 에 저장한다(커밋·업로드 금지).
실행: HF_HUB_OFFLINE=1 python lora_train.py --model 2.4b --en 1000 --epochs 2 --tag v0"""
import argparse
import json
import random
import time

import torch
from peft import LoraConfig, get_peft_model

import llm_probe as P
from review_analysis import absa as A, config as C
from review_analysis.data import build_splits

# 학습·추론 공통의 짧은 프롬프트(LoRA가 규칙을 데이터로 배운다)
SHORT = (f'의류 리뷰에서 리뷰가 실제로 평가한 속성과 감성을 추출하세요. 속성: {", ".join(A.ASPECTS)}. '
         '감성: 긍정, 부정, 중립. 평가 없이 사실만 적었거나 추측·조언인 속성은 출력하지 마세요. '
         '{"aspects": [{"aspect": "속성", "sentiment": "감성"}]} 형식의 JSON 객체 하나만 출력하세요.\n리뷰: ')


def target(d):
    return json.dumps(dict(aspects=[dict(aspect=k, sentiment=v) for k, v in d.items()]), ensure_ascii=False)


def encode(tok, text, gold, maxlen=640):
    p = tok.apply_chat_template([{'role': 'user', 'content': SHORT + text}], add_generation_prompt=True, tokenize=False)
    pi = tok(p, add_special_tokens=False).input_ids
    ti = tok(target(gold), add_special_tokens=False).input_ids + [tok.eos_token_id]
    pi = pi[-(maxlen - len(ti)):] if len(pi) + len(ti) > maxlen else pi
    return pi + ti, [-100] * len(pi) + ti


def evaluate(tok, model, texts, gold, bs=8, drop=None):
    raw = []
    for s in range(0, len(texts), bs):
        raw += P.generate(tok, model, [SHORT + x for x in texts[s:s + bs]])
    pred = [P.parse(r) or {} for r in raw]
    if drop:   # v3 모델의 새 속성은 정답이 없는 평가셋(합성·사람)에서는 채점에서 뺀다
        pred = [{k: v for k, v in p.items() if k != drop} for p in pred]
    res = A.compare(gold, pred)
    res.update(리뷰수=len(texts), 파싱실패=sum(P.parse(r) is None for r in raw),
               완전일치=round(sum(g == p for g, p in zip(gold, pred)) / len(texts), 3))
    return res, A.per_aspect(gold, pred), pred


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='2.4b')
    ap.add_argument('--n', type=int, default=1000, help='합성 리뷰 수(캐시와 같아야 함)')
    ap.add_argument('--en', type=int, default=0)
    ap.add_argument('--epochs', type=int, default=2)
    ap.add_argument('--lr', type=float, default=2e-4)
    ap.add_argument('--bs', type=int, default=4)
    ap.add_argument('--r', type=int, default=16)
    ap.add_argument('--tag', default='v0')
    ap.add_argument('--aihub', type=int, default=0, help='AI Hub 쇼핑몰 후기(Training, 매핑 가능분) 학습 추가 건수. 로컬 학습만, 어댑터는 private/에 둔다')
    ap.add_argument('--synth2', action='store_true', help='합성 v2(absa_synth2)를 학습에 더하고 합성 test도 v2로 평가')
    ap.add_argument('--schema3', action='store_true', help='속성 11개(활용성·사용감 추가) + AI Hub 변환(schema3). --aihub는 schema3.select_train 건수')
    ap.add_argument('--relabel', action='store_true', help='합성 학습 데이터에 정답 보정(synth_relabel) 적용')
    ap.add_argument('--collected-train', action='store_true', help='직접 수집한 후기 중 절반(heldout.train_ids)을 학습에 추가(×UPSAMPLE). 나머지는 평가 전용')
    a = ap.parse_args()
    global SHORT
    drop = None
    if a.schema3:
        from review_analysis import schema3 as S3
        S3.set_aspects(True)
        SHORT, drop = S3.SHORT3, S3.NEW

    def split(data, gold, clean):
        items = [(data[i]['review'], gold[i]) for i in clean]
        random.Random(C.SEED).shuffle(items)
        n_tr, n_va = int(0.7 * len(items)), int(0.15 * len(items))
        return items[:n_tr], items[n_tr + n_va:]

    data, gold, pred, clean, _ = A.validate_synth(A.synth_reviews(a.n))
    if a.relabel:   # 정답 보정(반어=부정, 문제없음=긍정, 뜯어짐=품질) — 원본 파일은 그대로 두고 학습에서만 적용
        from review_analysis import synth_relabel as RL
        gold, clean = RL.train_view(data, gold, pred, clean, '3class', 'synth_ko.v1')
    train, test = split(data, gold, clean)   # v1 (기존 분할 그대로)
    if a.synth2:   # v2: 실제 후기 특성을 규칙으로 반영한 합성. 학습에는 v1 학습분에 v2 학습분을 더하고, 합성 test는 v2 기준으로 바꾼다
        from review_analysis import absa_synth2 as S2
        d2, g2, p2, c2 = S2.validate(S2.synth_reviews(a.n))
        if a.relabel:
            g2, c2 = RL.train_view(d2, g2, p2, c2, '3class', 'synth_ko.v2')
        tr2, test2 = split(d2, g2, c2)
        train, test = train + tr2, test2
    if a.en:
        df, tr, va, te = build_splits()
        en = tr.head(a.en)
        train += list(zip(en['src_en'].tolist(), A.extract(f'train_en_{a.en}', en['src_en'].tolist())))
    if a.aihub and a.schema3:
        rows3, st3 = S3.load('Training')
        ah = S3.select_train(rows3, a.aihub)
        train += [(r['text'], r['gold']) for r in ah]
        print(f'AI Hub(v3 변환) 추가 {len(ah)}건 / 사용 가능 {len(rows3)}건, 제외 {dict(st3)}')
    elif a.aihub:
        from review_analysis import aihub
        ah, usable, _ = aihub.load('Training', a.aihub)
        train += [(r['text'], r['gold']) for r in ah]
        print(f'AI Hub 추가 {len(ah)}건 (사용 가능 {usable}건)')
    hold = set()
    if a.collected_train:
        from review_analysis import heldout as H
        hold = H.train_ids()
        hi, ht, hg = A.load_eval_gold(C.ROOT / 'private' / 'absa_eval_human_real.csv')
        ct = [(t, g) for i, t, g in zip(hi, ht, hg) if i in hold]
        train += ct * H.UPSAMPLE
        print(f'수집 후기 학습 {len(ct)}건 ×{H.UPSAMPLE}')
    print(f'학습 {len(train)} / 합성 test {len(test)}', flush=True)

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
    t0, step = time.time(), 0
    rng = random.Random(C.SEED)
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
        if a.schema3 and ep + 1 < a.epochs:   # 에폭 중간 체크포인트 (비교용)
            ck = C.ROOT / 'private' / 'lora' / f'{a.model}_{a.tag}_ep{ep + 1}'
            ck.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(ck)
    model.eval()
    model.config.use_cache = True
    out = C.ROOT / 'private' / 'lora' / f'{a.model}_{a.tag}'
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out)

    record = dict(tag=a.tag, 모델=a.model, 학습건수=len(train), 영어추가=a.en, synth2=a.synth2, aihub=a.aihub, schema3=a.schema3, collected_train=a.collected_train, 에폭=a.epochs, lr=a.lr, r=a.r, 학습초=round(time.time() - t0))
    res, pa, _ = evaluate(tok, model, [t for t, _ in test], [g for _, g in test], drop=drop)
    print('[합성 test]', json.dumps(res, ensure_ascii=False)); print(pa.to_string())
    record['합성test'] = res
    ids, texts, hgold = A.load_eval_gold(C.ROOT / 'private' / 'absa_eval_human_real.csv')
    if hold:   # 학습에 쓴 수집 후기는 평가에서 뺀다
        k = [j for j, i in enumerate(ids) if i not in hold]
        ids, texts, hgold = [ids[j] for j in k], [texts[j] for j in k], [hgold[j] for j in k]
    res, pa, hpred = evaluate(tok, model, texts, hgold, drop=drop)
    print('[사람 평가셋]', json.dumps(res, ensure_ascii=False)); print(pa.to_string())
    record['사람평가셋'] = res
    record['사람평가셋_속성별'] = json.loads(pa.to_json(orient='index', force_ascii=False))
    path = A.OUT / 'llm_local' / 'lora_runs.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    runs = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    path.write_text(json.dumps(runs + [record], ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'human_pred.json').write_text(json.dumps(hpred, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
