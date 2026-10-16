"""전체 결과 한 화면(overview.html): 번역 모델 비교, 감성 모델 결과(별점·긍/부정 점수), ABSA 시험, 추후 진행사항.
저장된 결과 파일만 읽어 만들므로 GPU와 API 호출이 필요 없다. 실행: python run.py overview"""
import glob
import html
import json
import os
import datetime as dt

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

from . import config as C
from .data import build_splits

NEXT_STEPS = [
    ('데이터·평가', [
        '한글 평가셋 200~300건 직접 작성·검수 (docs/absa-label-guide.md, 템플릿 docs/absa_eval_template.csv) — 사람이 해야 함',
        '합성 리뷰 불일치 항목(synth_review_queue.v1.csv) 중 정답이 틀린 것 확인',
        '평가셋이 모이면 python run.py absa eval --csv 로 실제 말투 성능 확인 (지금 ABSA 수치는 잠정치)',
        'AI Hub 한국어 감성·속성 기반 데이터 이용 조건 확인, 네이버/쇼핑몰/코퍼스 제공자 문의 (docs/korean-review-crawling-legal-notes.md의 문의 표)']),
    ('모델 학습 (GPU/Colab 필요)', [
        'absa-train을 Colab에서 소량(--n 100 --epochs 2)으로 먼저 실행해 코드 동작 확인 (이 PC에서는 미검증)',
        '영어 아마존 2,000건 라벨링을 더해 영어+한글 합본으로 학습, 언어별 성능 비교',
        'Rosetta-4B(bf16), EXAONE(transformers 상한), iris/llama3(디스크 정리) 번역 후보 다시 비교, 역번역 chrF 계산',
        'clapAI-XLMR 영어 결과 재실행해 영어-한글 비교에 포함']),
    ('번역·운영 결정', [
        '서비스용 번역 모델 결정 (NLLB 계열은 비상업 라이선스): M2M100-1.2B, Gugugo-7B, Gemini 중 선택',
        'Gemini API를 일 1회/시간 단위 배치로 운영할지 결정 (물량, 요금제, 모델 이름 고정, 외부 전송 검토). 증분 배치 명령은 필요해지면 추가',
        '오픈 LLM 2단계 번역(극성·강도 추출 후 번역)과 후보 번역 중 감성 판정기로 고르기 실험']),
]


def esc(x):
    return html.escape('' if x is None or (isinstance(x, float) and np.isnan(x)) else str(x))


def table(df, bold_max=(), bold_min=(), index=False):
    df = df.reset_index() if index else df
    best = {}
    for c in df.columns:
        v = pd.to_numeric(df[c], errors='coerce')
        if c in bold_max and v.notna().any():
            best[c] = v.max()
        if c in bold_min and v.notna().any():
            best[c] = v.min()
    h = '<div class="tw"><table><thead><tr>' + ''.join(
        f'<th class="{"l" if df[c].dtype == object else ""}">{esc(c)}</th>' for c in df.columns) + '</tr></thead><tbody>'
    for _, r in df.iterrows():
        h += '<tr>'
        for c in df.columns:
            v = r[c]
            num = pd.to_numeric(pd.Series([v]), errors='coerce').iloc[0]
            cls = 'l' if df[c].dtype == object else ''
            if c in best and not np.isnan(num) and num == best[c]:
                cls += ' best'
            h += f'<td class="{cls}">{esc(round(v, 3) if isinstance(v, float) else v)}</td>'
        h += '</tr>'
    return h + '</tbody></table></div>'


def binary_table(test_df):
    """저장된 확률로 계산한 긍/부정 점수 지표 (3점 제외). 한글 모델은 번역문으로 학습·평가한 결과다."""
    star = test_df['star'].values
    m = star != 3
    rows = []
    for lang, d in (('KO(번역문)', C.RESULTS_DIR), ('EN(원문)', C.PREV_DIR / 'results')):
        for p in sorted(glob.glob(str(d / '*.json'))):
            r = json.load(open(p, encoding='utf-8'))
            if r['review_ids'] != test_df['review_id'].tolist():
                continue
            P = np.array(r['test_probs'])
            score = P[:, 3:].sum(1) - P[:, :2].sum(1)
            full = (P * np.array([-1, -.5, 0, .5, 1])).sum(1)
            rows.append({'모델': r['short'], '입력': lang,
                         '긍/부정 정확도(%)': round(100 * np.mean((score[m] > 0) == (star[m] > 3)), 1),
                         'AUC': round(roc_auc_score(star[m] > 3, score[m]), 3),
                         'Spearman(점수,별점)': round(spearmanr(full, star).correlation, 3)})
    return pd.DataFrame(rows).sort_values('AUC', ascending=False)


def absa_section():
    from . import absa as A
    d = A.OUT
    out = ''
    names = ('EN', 'EN_rerun', 'NHNDQ-NLLB-en2ko', 'Gemini-3.5-FlashLite')
    # 가이드/프롬프트 버전이 올라갔어도 시험 결과가 다 있는 가장 최신 버전을 보여 준다
    v = next((ver for ver in (A.VERSION, 'v1') if all((d / f'{n}.{ver}.json').exists() for n in names)), A.VERSION)
    files = {n: d / f'{n}.{v}.json' for n in names}
    if not all(p.exists() for p in files.values()):
        return '<p class="note">ABSA 시험 결과가 없습니다. <code>python run.py absa lang</code>, <code>rerun</code>을 먼저 실행하세요.</p>'
    res = {n: json.loads(p.read_text(encoding='utf-8')) for n, p in files.items()}
    rows = {'EN vs EN 재실행 (Gemini 자체 흔들림)': A.compare(res['EN'], res['EN_rerun']),
            'EN vs 한글(Gemini 번역)': A.compare(res['EN'], res['Gemini-3.5-FlashLite']),
            'EN vs 한글(NHNDQ 번역)': A.compare(res['EN'], res['NHNDQ-NLLB-en2ko'])}
    out += f'<h3>언어·번역 간 일관성 (300건, 가이드 {v})</h3>' + table(pd.DataFrame(rows).T.reset_index().rename(columns={'index': '비교'}),
                                                              bold_max=('탐지_F1', '감성일치율'), bold_min=('극성반전율',))
    cnt = pd.DataFrame({k: pd.Series([a for r in v_ for a in r]).value_counts() for k, v_ in
                        {'영어': res['EN'], '한글(Gemini 번역)': res['Gemini-3.5-FlashLite'], '한글(NHNDQ 번역)': res['NHNDQ-NLLB-en2ko']}.items()}
                       ).reindex(A.ASPECTS).fillna(0).astype(int)
    out += '<h3>속성별 언급 수 (아마존 영어 리뷰에는 서비스 속성이 거의 없음)</h3>' + table(cnt.rename_axis('속성'), index=True)
    sp = d / f'synth_ko.{A.SYNTH_VERSION}.json'
    pp = None
    if sp.exists():   # 합성 리뷰 건수와 같은 건수로 만든 재추출 결과만 짝지어 쓴다 (건수가 다르면 문구와 어긋난다)
        n_syn = len([x for x in json.loads(sp.read_text(encoding='utf-8')) if x['review']])
        pp = next((q for q in (d / f'synth_pred_{n_syn}.{ver}.json' for ver in (A.VERSION, 'v1')) if q.exists()), None)
    if sp.exists() and pp is not None:
        data = [x for x in json.loads(sp.read_text(encoding='utf-8')) if x['review']]
        pred = json.loads(pp.read_text(encoding='utf-8'))
        gold = [{x['aspect']: x['sentiment'] for x in r['aspects']} for r in data]
        n_clean = sum(g == p for g, p in zip(gold, pred))
        tot = A.compare(gold, pred)
        out += (f'<h3>한글 합성 리뷰 {len(data)}건 (지시 정답 대비, 낙관적 수치)</h3>'
                f'<p class="note">지시와 재추출이 완전히 같은 항목 {n_clean}건({100 * n_clean / len(data):.1f}%). '
                f'탐지 F1 {tot["탐지_F1"]}, 감성 일치율 {tot["감성일치율"]}, 극성 반전율 {tot["극성반전율"]}. '
                f'같은 모델이 쓰고 읽은 합성 리뷰이므로 실제 한국인 리뷰 성능이 아닙니다.</p>'
                + table(A.per_aspect(gold, pred).astype({'정답수': int}).reset_index().rename(columns={'index': '속성'}), bold_max=('F1', '감성정확도')))
        q = [(r['review'], g, p) for r, g, p in zip(data, gold, pred) if g != p][:12]
        out += '<h3>사람이 확인할 불일치 예시 (전체는 synth_review_queue.csv)</h3>' + table(pd.DataFrame(
            [{'리뷰': r[:110], '지시': json.dumps(g, ensure_ascii=False), '추출': json.dumps(p, ensure_ascii=False)} for r, g, p in q]))
    return out


CSS = """
:root{--bg:#f9f9f7;--sf:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--grid:#e1e0d9;--hl:#cde2fb;--ac:#2a78d6}
@media (prefers-color-scheme:dark){:root{--bg:#0d0d0d;--sf:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;--hl:#184f95;--ac:#3987e5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Segoe UI","Malgun Gothic",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 56px}h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:0 0 6px}h3{font-size:14px;margin:18px 0 6px}
.sub,.note{color:var(--ink2);font-size:13px;margin:2px 0 10px}.card{background:var(--sf);border:1px solid var(--grid);border-radius:10px;padding:16px;margin:16px 0}
.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:5px 8px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}
th{color:var(--ink2);font-weight:600}th.l,td.l{text-align:left;white-space:normal}td.best{font-weight:700;background:var(--hl)}
nav a{margin-right:14px;color:var(--ac);text-decoration:none}li{margin:3px 0}.ok{color:#0a7f3f;font-weight:600}.ng{color:#c0392b;font-weight:600}.chip{display:inline-block;margin:1px 6px 1px 0;white-space:nowrap}.txt{max-width:520px;white-space:normal;text-align:left}.int{border-left:3px solid #c0392b;padding:6px 10px;background:var(--bg);margin:10px 0}.warn{border-left:3px solid #d97706;padding:6px 10px;background:var(--bg);margin:10px 0}
"""


def small_model_section():
    """작은 모델(증류) 실행 기록. 지표만 담겨 있어 공유용 화면에도 넣는다."""
    from . import absa as A
    path = A.OUT / 'small_model_runs.json'
    if not path.exists():
        return '<p class="note">아직 작은 모델 실행 기록이 없습니다. <code>python run.py absa-train --n 1000 --en 1000 --epochs 6 --human</code></p>'
    rows = []
    for r in json.loads(path.read_text(encoding='utf-8')):
        h = r.get('사람평가셋_작은모델') or {}
        g = r.get('사람평가셋_Gemini') or {}
        rows.append({'실행 시각': r['시각'], '합성 생성': r['합성생성'], '영어 추가': r['영어추가'], '에폭': r['에폭'], '학습 건수': r['학습건수'],
                     '합성 test F1': r['합성test']['탐지_F1'], '합성 test 감성일치': r['합성test']['감성일치율'],
                     '사람평가셋 F1(작은모델)': h.get('탐지_F1'), '사람평가셋 감성일치(작은모델)': h.get('감성일치율'), '극성반전(작은모델)': h.get('극성반전율'),
                     '사람평가셋 F1(Gemini)': g.get('탐지_F1'), '사람평가셋 감성일치(Gemini)': g.get('감성일치율')})
    return ('<p class="note">KLUE-RoBERTa를 Gemini 라벨(한글 합성 + 선택적으로 영어 아마존)로 학습한 작은 모델. 사람 평가셋은 이 PC에서만 계산했고, 11건처럼 건수가 적으면 변동이 큽니다. 마지막 행이 가장 최근 실행입니다.</p>'
            + table(pd.DataFrame(rows), bold_max=('사람평가셋 F1(작은모델)', '사람평가셋 감성일치(작은모델)'), bold_min=('극성반전(작은모델)',)))


HUMAN_CSV = C.ROOT / 'private' / 'absa_eval_human_real.csv'


def human_eval_section():
    """사람이 직접 라벨한 평가셋 채점 결과. 실제 후기 원문이 들어가므로 내부용 화면(private/)에서만 쓴다."""
    from . import absa as A
    if not HUMAN_CSV.exists():
        return '<p class="note">평가셋 파일(private/absa_eval_human_real.csv)이 없습니다.</p>'
    rep, dis, rows = A.score_eval_csv(HUMAN_CSV, return_rows=True)
    tot = rep['전체']
    out = ('<div class="int"><b>내부용.</b> 실제 후기를 받아 적은 원문이 포함되어 있습니다. 이 파일을 외부에 올리거나 공유하지 마세요.</div>'
           f'<p class="note">{len(rows)}건. 탐지 F1 {tot["탐지_F1"]}, 감성 일치율 {tot["감성일치율"]}, 극성 반전율 {tot["극성반전율"]} '
           f'(가이드 {A.VERSION}). 소표본이라 통계적 해석은 어렵습니다. 같은 입력도 Gemini가 실행마다 조금씩 달라질 수 있습니다.</p>')
    out += '<h3>속성별</h3>' + table(rep['속성별'].astype({'정답수': int}).reset_index().rename(columns={'index': '속성'}), bold_max=('F1', '감성정확도'))
    h = '<div class="tw"><table><thead><tr><th class="l">ID</th><th class="l">리뷰 원문</th><th class="l">사람 vs 모델 (속성별 감성)</th><th>일치</th></tr></thead><tbody>'
    for r in rows:
        keys = [a for a in A.ASPECTS if a in r['gold'] or a in r['pred']]
        chips = ''
        for a in keys:
            g, p = r['gold'].get(a), r['pred'].get(a)
            cls = 'ok' if g == p else 'ng'
            chips += f'<span class="chip {cls}">{esc(a)}: 사람 {esc(g or "없음")} / 모델 {esc(p or "없음")}</span><br>'
        same = r['gold'] == r['pred']
        h += (f'<tr><td class="l">{esc(r["review_id"])}</td><td class="l txt">{esc(r["text"])}</td><td class="l">{chips}</td>'
              f'<td class="{"ok" if same else "ng"}">{"✓" if same else "✗"}</td></tr>')
    return out + '<h3>리뷰별 (원문 포함)</h3>' + h + '</tbody></table></div>'


def build(internal=False):
    df, tr, va, te = build_splits()
    mt = pd.read_csv(C.OUT_DIR / 'mt_compare.csv', encoding='utf-8-sig')
    keep = [c for c in ['번역 모델', '라이선스', '감성 유지 점수', '감성 일치율(%)', '극성 반전율(%)', 'LLM 별점 일치율(%)', '실패율(%)', '실패 유형', '속도(건/초)', '종합 점수'] if c in mt.columns]
    summ = pd.read_csv(C.OUT_DIR / 'metrics_summary.csv', encoding='utf-8-sig')
    keep2 = ['모델', '언어', '정확도(%)', 'Macro-F1(%)', '±1점 정확도(%)', '감성 정확도(%)', '학습 시간(분)']
    main_mt = '미확인'
    for p in glob.glob(str(C.RESULTS_DIR / '*.json')):
        main_mt = json.load(open(p, encoding='utf-8')).get('mt', main_mt)
        break
    nav = '<nav><a href="#mt">번역 모델</a><a href="#senti">감성 모델</a><a href="#absa">속성 분석(ABSA)</a>' + ('<a href="#human">사람 평가셋(내부용)</a>' if internal else '') + '<a href="#next">추후 진행사항</a><a href="dashboard.html">상세 대시보드(별점 모델)</a></nav>'
    h = f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>리뷰 감성·번역 결과 한눈에 보기</title><style>{CSS}</style></head><body><main>'
    h += f'<h1>아마존 리뷰 한국어 감성 실험 — 전체 결과</h1><p class="sub">생성 {dt.datetime.now():%Y-%m-%d %H:%M} · 샘플 {len(df):,}건(학습 {len(tr):,} / 검증 {len(va):,} / 테스트 {len(te):,}) · 번역 모델(한국어 감성 학습용): {esc(main_mt)} · 기간 {C.START_DATE} ~ {C.END_DATE} 전</p>{nav}'
    h += '<div class="warn">모든 한국어 수치는 <b>영어 리뷰를 번역한 문장</b> 기준입니다. 실제 한국인이 쓴 리뷰에서의 성능은 아직 확인하지 못했습니다(평가셋 필요).</div>'
    h += '<section class="card" id="mt"><h2>1. 번역 모델 비교 (테스트 리뷰 300건)</h2><p class="note">감성 유지 점수 = (감성 일치율 + 강도 유지율 + 분포 유사도 + LLM 별점 일치율) 평균 − 2×극성 반전율. 역번역 chrF가 없어 종합 점수는 0.85×감성 유지 점수입니다. Rosetta-4B는 300건 모두 빈 번역이었습니다.</p>'
    h += table(mt[keep], bold_max=('감성 유지 점수', '감성 일치율(%)', 'LLM 별점 일치율(%)', '속도(건/초)', '종합 점수'), bold_min=('극성 반전율(%)', '실패율(%)')) + '</section>'
    h += '<section class="card" id="senti"><h2>2. 감성 모델 결과 (테스트 3,001건)</h2><h3>별점 5단계</h3><p class="note">KO = 한국어 번역문, EN = 영어 원문.</p>'
    h += table(summ[keep2], bold_max=('정확도(%)', 'Macro-F1(%)', '±1점 정확도(%)', '감성 정확도(%)'))
    h += '<h3>긍/부정 점수 방식 (3점 제외, 점수 = P(4·5점) − P(1·2점))</h3><p class="note">2분류로 보면 90% 이상이고 번역으로 잃는 폭은 1~3%p입니다. 한글 모델은 번역문으로 학습·평가했습니다.</p>'
    h += table(binary_table(te), bold_max=('긍/부정 정확도(%)', 'AUC', 'Spearman(점수,별점)')) + '</section>'
    h += '<section class="card" id="absa"><h2>3. 속성 기반 감성분석(ABSA) 시험</h2><p class="note">의류 한정, 속성 10개, 긍정/부정/중립, Gemini 추출. 라벨 기준은 docs/absa-label-guide.md (1차 확정).</p>' + absa_section() + '<h3>작은 모델(증류) 실행 기록</h3>' + small_model_section() + '</section>'
    if internal:
        h += '<section class="card" id="human"><h2>3-1. 사람이 라벨한 평가셋 채점 (내부용)</h2>' + human_eval_section() + '</section>'
    h += '<section class="card" id="next"><h2>4. 추후 진행사항</h2>'
    for title, items in NEXT_STEPS:
        h += f'<h3>{esc(title)}</h3><ul>' + ''.join(f'<li>{esc(i)}</li>' for i in items) + '</ul>'
    h += '</section><p class="note">관련 문서: docs/absa-label-guide.md · docs/korean-review-crawling-legal-notes.md · README.md</p></main></body></html>'
    if internal:   # 원문이 들어간 화면은 private/에만 둔다
        h = h.replace('<h1>아마존 리뷰 한국어 감성 실험 — 전체 결과</h1>', '<h1>아마존 리뷰 한국어 감성 실험 — 전체 결과 <span class="ng">[내부용]</span></h1>')
        path = C.ROOT / 'private' / 'overview_internal.html'
        path.parent.mkdir(exist_ok=True)
    else:
        path = C.OUT_DIR / 'overview.html'
    path.write_text(h, encoding='utf-8')
    return path
