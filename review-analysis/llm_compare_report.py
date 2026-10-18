"""LoRA(EXAONE 2.4B) vs Gemini 비교 화면 voc_amazon_ko/llm_compare.html 생성. 저장된 결과만 읽는다(GPU·API 없음).
실제 후기 원문은 넣지 않는다(사람 평가셋은 지표만). 실행: python llm_compare_report.py"""
import html
import json

from review_analysis import absa as A, absa_synth2 as S, config as C

OUT = C.OUT_DIR / 'llm_compare.html'   # 옛 위치(archive/에 보관). 다시 만들면 여기에 생긴다
C.OUT_DIR.mkdir(parents=True, exist_ok=True)
LORA = ['2.4b_v0', '2.4b_v1']
LABEL = {'2.4b_v0': 'LoRA v0 (합성v1+영어)', '2.4b_v1': 'LoRA v1 (합성v1+v2+영어)', 'gemini': 'Gemini 재추출'}


def metrics(g, p):
    r = A.compare(g, p)
    r['완전일치'] = round(sum(a == b for a, b in zip(g, p)) / len(g), 3)
    return r


def table(rows, cols, head=None):
    h = ''.join(f'<th>{html.escape(c)}</th>' for c in (head or ['모델'] + cols))
    body = ''
    for name, vals in rows:
        best = {c: max(v[c] for _, v in rows if v.get(c) is not None) for c in cols}
        tds = ''.join(f'<td class="{"best" if vals[c] == best[c] else ""}">{vals[c]:.3f}</td>' if vals.get(c) is not None else '<td>-</td>' for c in cols)
        body += f'<tr><th>{html.escape(name)}</th>{tds}</tr>'
    return f'<table><tr>{h}</tr>{body}</table>'


def main():
    runs = json.loads((A.OUT / 'llm_local' / 'synth_eval_v2.json').read_text(encoding='utf-8'))
    d = json.loads((A.OUT / 'synth_eval_v2.json').read_text(encoding='utf-8'))
    data, gold, gem, clean = S.validate(d, name='synth_eval_v2_pred')
    cols = ['탐지_F1', '탐지_정밀도', '탐지_재현율', '감성일치율', '극성반전율', '완전일치']
    syn = [(LABEL['gemini'], metrics(gold, gem))] + [(LABEL[k], runs[f'lora:{k}']['전체']) for k in LORA]
    sub = [(LABEL[k], runs[f'lora:{k}']['일치부분집합']) for k in LORA]
    per = {LABEL['gemini']: A.per_aspect(gold, gem)['F1']}
    for k in LORA:
        per[LABEL[k]] = {a: runs[f'lora:{k}']['속성별_전체'][a]['F1'] for a in A.ASPECTS}
    prow = ''.join(f'<tr><th>{a}</th>' + ''.join(f'<td>{per[m][a]:.2f}</td>' for m in per) + '</tr>' for a in A.ASPECTS)

    # 사람 평가셋: 지표만 (원문 없음). Gemini는 캐시 파일에서 읽어 외부 호출 없음
    ids, texts, hg = A.load_eval_gold(C.ROOT / 'private' / 'absa_eval_human_real.csv')
    hum = []
    cache = sorted((A.OUT).glob(f'human_eval_{len(ids)}_*.{A.VERSION}.json'))
    import hashlib
    h = hashlib.sha1('|'.join(texts).encode('utf-8')).hexdigest()[:8]
    cp = A.OUT / f'human_eval_{len(ids)}_{h}.{A.VERSION}.json'
    if cp.exists():
        hum.append((LABEL['gemini'], metrics(hg, json.loads(cp.read_text(encoding='utf-8')))))
    for k in LORA:
        hum.append((LABEL[k], metrics(hg, json.loads((C.ROOT / 'private' / 'lora' / k / 'human_pred.json').read_text(encoding='utf-8')))))

    page = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LoRA vs Gemini 비교</title>
<style>:root{{--bg:#fff;--fg:#1c1c1e;--mut:#6b6b70;--line:#e2e2e6;--best:#e3f3e6}}
@media(prefers-color-scheme:dark){{:root{{--bg:#16161a;--fg:#ececf0;--mut:#9a9aa2;--line:#33333a;--best:#1f3a27}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,'Malgun Gothic',sans-serif;max-width:900px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px}}h2{{font-size:17px;margin-top:32px}}p,li{{color:var(--mut)}}
table{{border-collapse:collapse;width:100%;margin:8px 0;font-size:14px}}th,td{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:right}}
th:first-child,tr>th{{text-align:left}}td.best{{background:var(--best);font-weight:600}}</style>
<h1>EXAONE-3.5-2.4B LoRA vs Gemini</h1>
<p>ABSA(속성별 감성 추출) 비교. 로컬 GPU에서 학습·추론했고 이 화면에는 실제 후기 원문이 없습니다. 초록 칸이 열 최고값(극성반전율은 낮을수록 좋음).</p>
<h2>1. 평가용 합성 리뷰 {len(gold)}건</h2>
<p>학습 세트와 시드·문구가 겹치지 않는 평가 전용 세트. 정답은 생성 지시서입니다. LoRA v1은 이 평가셋과 같은 방식(v2)의 합성으로 학습해서 유리하고, Gemini 행은 같은 모델이 쓰고 다시 읽은 값이라 참고용입니다. 실제 후기 성능이 아닙니다.</p>
{table(syn, cols)}
<h3>Gemini 재추출이 지시서와 일치한 부분집합 {len(clean)}건 (더 낙관적)</h3>
{table(sub, cols)}
<h3>속성별 탐지 F1 (전체)</h3>
<table><tr><th>속성</th>{''.join(f'<th>{html.escape(m)}</th>' for m in per)}</tr>{prow}</table>
<h2>2. 사람이 라벨한 실제 후기 {len(ids)}건</h2>
<p>내부 평가셋(원문 비공개, 지표만 표시). 표본이 적어 속성 하나만 달라져도 F1이 0.1 이상 움직입니다. 순위의 근거로는 약합니다. 정답은 2026-10-12 수정본 기준입니다.</p>
{table(hum, cols)}
<h2>메모</h2><ul><li>LoRA: r=16, 2에폭, 한글 합성 + 영어 아마존(Gemini 라벨). 사람 평가셋은 학습에 쓰지 않았습니다.</li>
<li>가장 시급한 일은 실제 후기 평가셋을 늘리는 것입니다.</li></ul></html>'''
    OUT.write_text(page, encoding='utf-8')
    print(OUT)


if __name__ == '__main__':
    main()
