"""명령줄 진입점. 노트북의 장(章)을 하위 명령으로 나눴다.

  python run.py sample                      원본에서 샘플링 (이미 sample_raw.parquet가 있으면 건너뜀)
  python run.py check                       분할·캐시 확인 (GPU 불필요)
  python run.py translate --model NAME      후보 하나로 비교용(300건) 또는 전체(--all) 번역
  python run.py compare                     번역 후보 비교 표 생성 (캐시된 번역만 사용, 새 번역은 --translate)
  python run.py train [--only NAME]         한국어 감성 모델 학습·평가 (GPU 권장)
  python run.py report                      요약표, 예측표, 대시보드 생성 (GPU 불필요)
  python run.py overview                    전체 결과 한 화면(voc_amazon_ko/overview.html) 생성
  python run.py absa lang|rerun|synth|eval       속성 기반 감성분석(ABSA) 시험: 언어 간/실행 간 일관성, 한글 합성 리뷰 (Gemini 필요, GPU 불필요)

옵션 --limit N: 앞에서 N건만 처리하는 소량 검증용.
번역·학습은 GPU가 필요하다(없으면 Colab 사용, 또는 Gemini 후보는 API로 로컬 실행 가능)."""
import argparse
import io
import json
import sys

# Windows 콘솔(cp949)에서 한글·특수문자가 깨지거나 오류 나는 것을 막음
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

import pandas as pd

from review_analysis import config as C
from review_analysis.data import build_splits, load_en_results, sample_raw
from review_analysis.text import failure_reason


def attach_ko(df, train_df, val_df, test_df, cfg_name):
    """번역 캐시에서 ko_text 열을 붙인다 (없는 건은 빈 문자열)."""
    path = C.TRANS_DIR / f'{cfg_name}.parquet'
    cache = pd.read_parquet(path).drop_duplicates('review_id', keep='last').set_index('review_id')['ko']
    for d in (df, train_df, val_df, test_df):
        d['ko_text'] = d['review_id'].map(cache).fillna('')


def cmd_sample(a):
    raw = sample_raw()
    print(f'샘플 {len(raw):,}건')


def cmd_check(a):
    df, tr, va, te = build_splits()
    print(f'전체 {len(df):,} / 학습 {len(tr):,} / 검증 {len(va):,} / 테스트 {len(te):,}')
    print('영어 결과와 같은 테스트셋:', list(load_en_results(te)) or '없음')
    for p in sorted(C.TRANS_DIR.glob('*.parquet')):
        t = pd.read_parquet(p)
        n_empty = int((t['ko'].astype(str).str.strip() == '').sum())
        flag = '  <- 빈 번역이 많음' if n_empty > len(t) * 0.5 else ''
        print(f'  번역 캐시 {p.stem}: {len(t):,}건, 빈 번역 {n_empty}건{flag}')


def cmd_translate(a):
    from review_analysis.mt_compare import enabled_candidates, pick_eval_set
    from review_analysis.translators import get_translations
    df, tr, va, te = build_splits()
    frame = df if a.all else pick_eval_set(te)
    if a.limit:
        frame = frame.head(a.limit)
    names = a.model or [c['short'] for c in enabled_candidates()]
    for name in names:
        cfg = C.MT_BY_NAME[name]
        if a.limit:   # 소량 검증은 실제 캐시를 건드리지 않게 임시 폴더를 쓴다
            C.TRANS_DIR = C.OUT_DIR / 'translations_smoke'
            C.TRANS_DIR.mkdir(exist_ok=True)
            import review_analysis.translators as T
            T.C.TRANS_DIR = C.TRANS_DIR
        ko, n_new, secs = get_translations(cfg, frame[['review_id', 'src_en']], '(전체)' if a.all else '(비교용)')
        fails = [failure_reason(s, k) for s, k in zip(frame['src_en'], ko)]
        bad = pd.Series([f for f in fails if f]).value_counts().to_dict()
        print(f'{name}: 새로 번역 {n_new}건, {secs:.0f}초, 실패 {sum(1 for f in fails if f)}건 {bad}')


def cmd_compare(a):
    from review_analysis.mt_compare import choose_main, compare, enabled_candidates, pick_eval_set, translate_candidates
    df, tr, va, te = build_splits()
    mt_eval = pick_eval_set(te)
    if a.translate:
        mt_out, mt_speed = translate_candidates(mt_eval)
    else:   # 캐시에 비교용 리뷰가 모두 있는 후보만 사용
        mt_out, mt_speed = {}, json.loads((C.TRANS_DIR / '_speed.json').read_text()) if (C.TRANS_DIR / '_speed.json').exists() else {}
        for c in C.MT_CANDIDATES:
            p = C.TRANS_DIR / f"{c['short']}.parquet"
            if not p.exists():
                continue
            cache = pd.read_parquet(p).drop_duplicates('review_id', keep='last').set_index('review_id')['ko']
            if mt_eval['review_id'].isin(cache.index).all():
                mt_out[c['short']] = mt_eval['review_id'].map(cache).fillna('').tolist()
    print('비교 후보:', list(mt_out))
    table, samples, en_acc = compare(mt_eval, mt_out, mt_speed)
    print(f'원문(영어) 감성 정확도 {en_acc}%')
    print(table.to_string())
    print('1위(자동 선택 기준):', choose_main(table))


def cmd_train(a):
    from review_analysis.classify import fine_tune, zero_shot
    from review_analysis.mt_compare import choose_main
    df, tr, va, te = build_splits()
    main_name = a.mt or C.MAIN_MT
    if main_name == 'auto':
        main_name = choose_main(pd.read_csv(C.OUT_DIR / 'mt_compare.csv'))
    attach_ko(df, tr, va, te, main_name)
    print(f'번역 모델: {main_name}')
    if a.limit:
        tr, va, te = tr.head(a.limit), va.head(a.limit), te.head(a.limit)
    failed = {}
    for cfg in C.MODELS:
        if a.only and cfg['short'] not in a.only:
            continue
        path = C.RESULTS_DIR / f"{cfg['short']}.json"
        if C.RESUME and path.exists() and not a.limit:
            r = json.loads(path.read_text(encoding='utf-8'))
            if r.get('review_ids') == te['review_id'].tolist() and r.get('mt') == main_name:
                print(f"[건너뜀] {cfg['short']}: 저장된 결과 사용"); continue
        try:
            zs = zero_shot(cfg, te['ko_text'].tolist()) if cfg.get('zero_shot', True) else None
            ft = fine_tune(cfg, tr, va, te, 'ko_text')
            r = dict(short=cfg['short'], hf=cfg['hf'], base=cfg['base'], license=cfg['license'],
                     mt=main_name, review_ids=te['review_id'].tolist(), zs_labels=zs, **ft)
            if not a.limit:
                path.write_text(json.dumps(r, ensure_ascii=False), encoding='utf-8')
            print(f"{cfg['short']}: 완료")
        except Exception:
            import traceback
            failed[cfg['short']] = traceback.format_exc()[-1500:]
            print(f"[실패] {cfg['short']}\n{failed[cfg['short']]}")
    if not a.limit:
        (C.OUT_DIR / 'failed_models.json').write_text(json.dumps(failed, ensure_ascii=False, indent=1), encoding='utf-8')


def cmd_report(a):
    from review_analysis.mt_compare import choose_main
    from review_analysis.report import build_dashboard, build_pred_table, build_tables, load_ko_results
    df, tr, va, te = build_splits()
    mt_compare = pd.read_csv(C.OUT_DIR / 'mt_compare.csv')
    main_name = a.mt or (C.MAIN_MT if C.MAIN_MT != 'auto' else choose_main(mt_compare))
    attach_ko(df, tr, va, te, main_name)
    ko = load_ko_results(te, main_name)
    en = load_en_results(te)
    results, metrics, summary, delta = build_tables(te, ko, en)
    build_pred_table(te, results, ko, en)
    from review_analysis.mt_compare import pick_eval_set
    en_acc = None
    path = build_dashboard(tr, va, te, pick_eval_set(te), mt_compare, main_name, en_acc, results, metrics, summary)
    print(summary.to_string())
    print('대시보드:', path)


def cmd_absa(a):
    import numpy as np
    from review_analysis import absa as A
    from review_analysis.mt_compare import pick_eval_set
    df, tr, va, te = build_splits()
    ev = pick_eval_set(te)
    ids = ev['review_id']
    if a.what in ('lang', 'rerun'):
        res = {'EN': A.extract('EN', ev['src_en'].tolist())}
        if a.what == 'rerun':   # 같은 영어 입력을 한 번 더 넣어 Gemini 자체의 실행 간 흔들림을 잰다
            res['EN_rerun'] = A.extract('EN_rerun', ev['src_en'].tolist())
            print(pd.DataFrame({'EN vs EN 재실행': A.compare(res['EN'], res['EN_rerun'])}).T.to_string())
            return
        rows = {}
        for name in ('NHNDQ-NLLB-en2ko', 'Gemini-3.5-FlashLite'):
            cache = pd.read_parquet(C.TRANS_DIR / f'{name}.parquet').drop_duplicates('review_id', keep='last').set_index('review_id')['ko']
            res[name] = A.extract(name, ids.map(cache).fillna('').tolist())
            rows[f'EN vs {name}'] = A.compare(res['EN'], res[name])
        print(pd.DataFrame(rows).T.to_string())
    elif a.what == 'synth':
        data, gold, pred, clean, queue = A.validate_synth(A.synth_reviews(a.n))
        print(f'합성 {len(data)}건: 지시와 추출이 완전히 같은 항목 {len(clean)}건({100 * len(clean) / len(data):.1f}%), 다른 항목 {len(queue)}건')
        print('전체:', A.compare(gold, pred))
        print(A.per_aspect(gold, pred).to_string())
        pd.DataFrame(queue).to_csv(A.OUT / f'synth_review_queue.{A.VERSION}.csv', index=False, encoding='utf-8-sig')
        print('사람이 확인할 불일치 항목:', A.OUT / f'synth_review_queue.{A.VERSION}.csv')
        print('주의: 같은 모델(Gemini)이 쓰고 읽은 합성 리뷰라 정확도가 낙관적입니다. 직접 작성한 평가셋으로 다시 확인하세요.')
    elif a.what == 'eval':
        rep, dis = A.score_eval_csv(a.csv)
        for k, v in rep.items():
            print(f'[{k}]'); print(v if isinstance(v, dict) else v.to_string())
        out = C.ROOT / 'private' / f'human_eval_disagreements.{A.VERSION}.csv'   # 실제 후기가 들어 있어 private/에만 둔다
        out.parent.mkdir(exist_ok=True)
        dis.to_csv(out, index=False, encoding='utf-8-sig')
        print('사람과 모델이 다른 리뷰:', len(dis), '→', out)

def cmd_absa_train(a):
    """합성 한글 리뷰(검증된 항목)와 선택적으로 영어 아마존 리뷰(Gemini 라벨)로 다중 헤드 모델을 학습한다. GPU 필요, 이 PC에서는 미검증."""
    import random
    from review_analysis import absa as A
    from review_analysis.absa_train import train_absa
    data, gold, pred, clean, queue = A.validate_synth(A.synth_reviews(a.n))
    items = [(data[i]['review'], gold[i]) for i in clean]
    random.Random(C.SEED).shuffle(items)
    n_tr, n_va = int(0.7 * len(items)), int(0.15 * len(items))
    train, val, test = items[:n_tr], items[n_tr:n_tr + n_va], items[n_tr + n_va:]
    if a.en:   # 영어 아마존 학습 리뷰를 Gemini로 라벨링해 학습에만 추가 (평가는 한글 합성 test만)
        df, tr, va, te = build_splits()
        en = tr.head(a.en)
        lab = A.extract(f'train_en_{a.en}', en['src_en'].tolist())
        train += list(zip(en['src_en'].tolist(), lab))
    print(f'학습 {len(train)} / 검증 {len(val)} / 테스트(한글 합성) {len(test)}')
    rep, model, tok = train_absa(train, val, test, model_name=a.model_name, epochs=a.epochs)
    print('[한글 합성 test]')
    for k, v in rep.items():
        print(f'[{k}]'); print(v if isinstance(v, dict) else v.to_string())
    record = dict(시각=pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'), 모델=a.model_name, 합성생성=a.n, 영어추가=a.en, 에폭=a.epochs,
                  학습건수=len(train), 합성test건수=len(test), 합성test=rep['전체'],
                  합성test_속성별=json.loads(rep['속성별'].to_json(orient='index', force_ascii=False)))
    if a.human:   # 사람이 라벨한 평가셋(내부용)으로 평가. Gemini를 부르지 않고 이 PC 안에서만 계산한다
        from review_analysis.absa_train import predict
        ids, texts, hgold = A.load_eval_gold(C.ROOT / 'private' / 'absa_eval_human_real.csv')
        hpred = predict(model, tok, texts)
        print(f'[사람 평가셋 {len(ids)}건 — 작은 모델]')
        print(A.compare(hgold, hpred)); print(A.per_aspect(hgold, hpred).to_string())
        record['사람평가셋건수'] = len(ids)
        record['사람평가셋_작은모델'] = A.compare(hgold, hpred)
        record['사람평가셋_작은모델_속성별'] = json.loads(A.per_aspect(hgold, hpred).to_json(orient='index', force_ascii=False))
        try:   # 같은 평가셋에서 Gemini 결과를 비교용으로 함께 저장 (문구가 그대로면 캐시를 써서 외부 전송이 없다)
            record['사람평가셋_Gemini'] = A.score_eval_csv(C.ROOT / 'private' / 'absa_eval_human_real.csv')[0]['전체']
        except Exception as e:
            print('[Gemini 비교 생략]', repr(e)[:120])
    path = A.OUT / 'small_model_runs.json'
    runs = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    runs.append(record)
    path.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding='utf-8')
    print('결과 저장:', path)


def cmd_overview(a):
    from review_analysis.overview import build
    print('전체 결과 화면(원문 없음):', build())
    if a.internal:
        print('내부용 화면(사람 평가셋 원문 포함):', build(internal=True))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('sample').set_defaults(f=cmd_sample)
    sub.add_parser('check').set_defaults(f=cmd_check)
    p = sub.add_parser('translate'); p.set_defaults(f=cmd_translate)
    p.add_argument('--model', nargs='*'); p.add_argument('--all', action='store_true'); p.add_argument('--limit', type=int)
    p = sub.add_parser('compare'); p.set_defaults(f=cmd_compare)
    p.add_argument('--translate', action='store_true', help='캐시에 없는 후보도 새로 번역')
    p = sub.add_parser('train'); p.set_defaults(f=cmd_train)
    p.add_argument('--only', nargs='*'); p.add_argument('--mt'); p.add_argument('--limit', type=int)
    p = sub.add_parser('report'); p.set_defaults(f=cmd_report); p.add_argument('--mt')
    p = sub.add_parser('overview'); p.set_defaults(f=cmd_overview); p.add_argument('--internal', action='store_true', help='사람 평가셋 원문이 들어간 내부용 화면을 private/에 추가로 만든다')
    p = sub.add_parser('absa-train'); p.set_defaults(f=cmd_absa_train); p.add_argument('--n', type=int, default=300); p.add_argument('--en', type=int, default=0); p.add_argument('--model-name', default='klue/roberta-base'); p.add_argument('--epochs', type=int, default=10); p.add_argument('--human', action='store_true', help='private/의 사람 평가셋으로도 평가 (로컬 계산, 외부 전송 없음)')
    p = sub.add_parser('absa'); p.set_defaults(f=cmd_absa); p.add_argument('what', choices=['lang', 'rerun', 'synth', 'eval']); p.add_argument('--n', type=int, default=300); p.add_argument('--csv', default='private/absa_eval_human_real.csv')
    a = ap.parse_args()
    for d in (C.OUT_DIR, C.RESULTS_DIR, C.TRANS_DIR):   # 옛 파이프라인 폴더는 실행할 때 만든다
        d.mkdir(parents=True, exist_ok=True)
    a.f(a)


if __name__ == '__main__':
    main()
