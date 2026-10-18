"""KO/EN 결과 요약표, 원래값/예측값 표, 대시보드(HTML) 생성. torch 없이 동작."""
import datetime as dt
import json

import numpy as np
import pandas as pd

from . import config as C
from .data import SENT_ORDER, STARS
from .metrics import compute_metrics, pct, zero_shot_metrics

TEMPLATE_PATH = C.ROOT / 'templates' / 'dashboard_ko.html'


def load_ko_results(test_df, main_name):
    """저장된 한국어 모델 결과 중 테스트셋·번역 모델이 지금과 같은 것만 읽는다."""
    out = {}
    for p in sorted(C.RESULTS_DIR.glob('*.json')):
        r = json.loads(p.read_text(encoding='utf-8'))
        if r.get('review_ids') == test_df['review_id'].tolist() and r.get('mt') == main_name:
            out[r['short']] = r
        else:
            print(f'[제외] {p.name}: 테스트셋 또는 번역 모델({r.get("mt")})이 다름')
    return out


def build_tables(test_df, ko_results, en_results):
    results, metrics = {}, {}
    for lang, res in (('KO', ko_results), ('EN', en_results)):
        for short, r in res.items():
            name = f'{short} [{lang}]'
            r = dict(r, lang=lang)
            m = compute_metrics(test_df['star'], r['test_pred'], test_df['category'])
            if r.get('zs_labels'):
                m.update(zero_shot_metrics(r['zs_labels'], test_df['star']))
            results[name], metrics[name] = r, m

    summary_df = pd.DataFrame([{
        '모델': name, '언어': results[name]['lang'], 'HF 모델': results[name]['hf'], '기반': results[name]['base'],
        '라이선스': results[name]['license'], '파라미터(M)': round(results[name]['n_params'] / 1e6),
        '정확도(%)': pct(m['accuracy']), 'Macro-F1(%)': pct(m['macro_f1']), '±1점 정확도(%)': pct(m['within1']),
        'MAE': round(m['mae'], 3), '감성 정확도(%)': pct(m['sent_accuracy']),
        '학습 전 감성 정확도(%)': pct(m.get('zs_sent_accuracy')), '학습 전 별점 정확도(%)': pct(m.get('zs_star_accuracy')),
        '최적 에폭': results[name]['best_epoch'], '학습 시간(분)': round(results[name]['train_minutes'], 1),
        '예측 속도(건/초)': round(results[name]['infer_per_sec']),
    } for name, m in metrics.items()]).sort_values('정확도(%)', ascending=False).reset_index(drop=True)

    per_star = pd.DataFrame({n: {f'{s}점': pct(m['per_star'].get(s)) for s in STARS} for n, m in metrics.items()}).T
    per_cat = pd.DataFrame({n: {c: pct(v) for c, v in m['per_category'].items()} for n, m in metrics.items()}).T
    per_sent = pd.DataFrame({n: {s: pct(m['per_sentiment'].get(s)) for s in SENT_ORDER} for n, m in metrics.items()}).T

    delta_rows = []
    for short in sorted(set(ko_results) & set(en_results)):
        k, e = metrics[f'{short} [KO]'], metrics[f'{short} [EN]']
        delta_rows.append({'모델': short,
                           '정확도 EN': pct(e['accuracy']), '정확도 KO': pct(k['accuracy']),
                           '정확도 변화(%p)': round(pct(k['accuracy']) - pct(e['accuracy']), 1),
                           '감성 EN': pct(e['sent_accuracy']), '감성 KO': pct(k['sent_accuracy']),
                           '감성 변화(%p)': round(pct(k['sent_accuracy']) - pct(e['sent_accuracy']), 1)})
    delta_df = pd.DataFrame(delta_rows)

    summary_df.to_csv(C.OUT_DIR / 'metrics_summary.csv', index=False, encoding='utf-8-sig')
    delta_df.to_csv(C.OUT_DIR / 'metrics_en_vs_ko.csv', index=False, encoding='utf-8-sig')
    pd.concat({'별점별': per_star, '카테고리별': per_cat, '감성별': per_sent}, axis=1).to_csv(
        C.OUT_DIR / 'metrics_by_item.csv', encoding='utf-8-sig')
    (C.OUT_DIR / 'metrics_full.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=1), encoding='utf-8')
    return results, metrics, summary_df, delta_df


def build_pred_table(test_df, results, ko_results, en_results):
    t = test_df[['review_id', 'category', 'date', 'star', 'sentiment', 'src_en', 'ko_text']].rename(
        columns={'category': '카테고리', 'date': '작성일', 'star': '원래 별점', 'sentiment': '원래 감성',
                 'src_en': '영어 원문', 'ko_text': '한국어 번역'})
    for name, r in results.items():
        pred = np.array(r['test_pred'])
        t[f'{name} 예측'] = pred
        t[f'{name} 확신도'] = r['test_conf']
        t[f'{name} 정답'] = np.where(pred == t['원래 별점'].values, 'O', 'X')
    for short in sorted(set(ko_results) & set(en_results)):
        t[f'{short} 번역 후 오답'] = (t[f'{short} [EN] 정답'] == 'O') & (t[f'{short} [KO] 정답'] == 'X')
    t.to_csv(C.OUT_DIR / 'predictions_test.csv', index=False, encoding='utf-8-sig')
    return t


def build_dashboard(train_df, val_df, test_df, mt_eval, mt_compare, main_name, en_judge_acc, results, metrics, summary_df):
    model_rows = []
    for _, s in summary_df.iterrows():
        name, m, r = s['모델'], metrics[s['모델']], results[s['모델']]
        model_rows.append(dict(
            name=name, base=r['base'], license=r['license'], params_m=r['n_params'] / 1e6,
            accuracy=pct(m['accuracy']), macro_f1=pct(m['macro_f1']), within1=pct(m['within1']), mae=m['mae'],
            sent_accuracy=pct(m['sent_accuracy']), zs_sent_accuracy=pct(m.get('zs_sent_accuracy')),
            best_epoch=r['best_epoch'], train_minutes=round(r['train_minutes'], 1), infer_per_sec=r['infer_per_sec'],
            per_star={f'{k}점': pct(v) for k, v in m['per_star'].items()},
            per_category={k: pct(v) for k, v in m['per_category'].items()}, confusion=m['confusion']))
    rows = []
    for i, t in test_df.head(C.DASHBOARD_MAX_ROWS).iterrows():
        rows.append(dict(category=t['category'], date=t['date'], star=int(t['star']),
                         text=t['ko_text'][:500], en=t['src_en'][:500],
                         pred={n: int(results[n]['test_pred'][i]) for n in results},
                         conf={n: float(results[n]['test_conf'][i]) for n in results}))
    mt_rows = json.loads(mt_compare.to_json(orient='records', force_ascii=False))
    meta = dict(period=f'{C.START_DATE} ~ {(pd.Timestamp(C.END_DATE) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")}',
                categories=list(C.CATEGORIES), n_train=len(train_df), n_val=len(val_df), n_test=len(test_df),
                generated=dt.datetime.now().strftime('%Y-%m-%d %H:%M'), main_mt=main_name,
                mt_note=f'테스트 리뷰 {len(mt_eval)}건 기준. 감성 유지 점수 = (감성 일치율 + 강도 유지율 + 분포 유사도 + LLM 별점 일치율) 평균 − 2×극성 반전율, '
                        f'종합 점수 = 0.85×감성 유지 점수 + 0.15×역번역 chrF. '
                        + (f'원문(영어) 감성 정확도는 {en_judge_acc}%입니다. ' if en_judge_acc is not None else '')
                        + f'전체 번역에는 {main_name}을(를) 썼습니다.',
                rows_note=f'테스트 {len(test_df):,}건 중 {len(rows):,}건. 위는 한국어 번역, 아래 회색은 영어 원문입니다. '
                          '[KO]는 번역문으로, [EN]은 원문으로 학습한 결과입니다. 전체는 predictions_test.csv에 있습니다.')
    payload = json.dumps(dict(meta=meta, models=model_rows, rows=rows, mt=mt_rows), ensure_ascii=False)
    payload = payload.replace('</', '<\\/')
    html = TEMPLATE_PATH.read_text(encoding='utf-8').replace('__DATA__', payload)
    (C.OUT_DIR / 'dashboard.html').write_text(html, encoding='utf-8')
    return C.OUT_DIR / 'dashboard.html'
