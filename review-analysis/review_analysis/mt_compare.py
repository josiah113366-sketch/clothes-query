"""번역 후보 비교: 감성 유지 중심 지표, 역번역 chrF, Gemini 별점 판정."""
import json

import numpy as np
import pandas as pd

from . import config as C
from .metrics import native_label_to_sent, native_label_to_star
from .text import failure_reason
from .translators import GeminiClient, get_translations, make_translator, translate_reviews, free_memory


def pick_eval_set(test_df):
    """별점별로 고르게 MT_EVAL_N건 고르기 (이전 실행과 같은 리뷰가 뽑혀 번역 캐시를 다시 씀)."""
    per = max(1, C.MT_EVAL_N // 5)
    return test_df.sample(frac=1, random_state=C.SEED).groupby('star').head(per).reset_index(drop=True)


def translate_candidates(mt_eval, names=None):
    """사용 가능한 후보로 비교용 리뷰를 번역한다. 반환: {이름: 번역 리스트}, {이름: 속도}"""
    mt_out, mt_speed = {}, {}
    speed_path = C.TRANS_DIR / '_speed.json'
    speed_log = json.loads(speed_path.read_text()) if speed_path.exists() else {}
    for cfg in enabled_candidates(names):
        try:
            ko, n_new, secs = get_translations(cfg, mt_eval, '(비교용)')
        except Exception as e:
            print(f"[실패] {cfg['short']}: {repr(e)[:300]}")
            free_memory()
            continue
        if n_new:
            speed_log[cfg['short']] = n_new / max(secs, 1e-6)
            speed_path.write_text(json.dumps(speed_log))
        mt_out[cfg['short']] = ko.tolist()
        mt_speed[cfg['short']] = speed_log.get(cfg['short'])
    return mt_out, mt_speed


def enabled_candidates(names=None):
    """enabled인 후보 중 키가 있는 것만 (names를 주면 그 이름만)."""
    out = []
    for c in C.MT_CANDIDATES:
        if names is not None:
            if c['short'] not in names:
                continue
        elif not c['enabled']:
            continue
        if c['kind'] == 'gemini' and not C.secret('GEMINI_KEY'):
            print(f"API 키가 없어 {c['short']}는 건너뜁니다."); continue
        if c['kind'] == 'papago' and not (C.secret('PAPAGO_CLIENT_ID') and C.secret('PAPAGO_CLIENT_SECRET')):
            print(f"API 키가 없어 {c['short']}는 건너뜁니다."); continue
        out.append(c)
    return out


def label_values(labels):
    """판정기 라벨마다 감성 점수(-1 ~ +1)를 정한다."""
    if len(labels) == 5 and all(native_label_to_star(l) is not None for l in labels):
        return np.array([(native_label_to_star(l) - 3) / 2 for l in labels])
    return np.array([{'부정': -1.0, '중립': 0.0, '긍정': 1.0}.get(native_label_to_sent(l), 0.0) for l in labels])


def js_divergence(p, q):
    p, q = np.clip(p, 1e-9, 1), np.clip(q, 1e-9, 1)
    m = (p + q) / 2
    kl = lambda a, b: (a * np.log2(a / b)).sum(1)
    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


STAR_PROMPT = ('다음은 상품 리뷰 목록입니다(영어 또는 한국어). 각 리뷰 작성자가 줬을 별점(1~5 정수)을 리뷰 내용만 보고 추정하세요.\n'
               '출력: [{"id": 번호, "star": 별점}] 형식의 JSON 배열만 출력하세요.\n\n입력:\n')


def judge_probs(src, mt_out):
    """다국어 감성 판정기로 원문·번역문의 감성 확률을 구한다 (torch 필요)."""
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    from .classify import DEVICE, predict_probs
    judged = {}
    for j in C.SENTI_JUDGES:
        try:
            jtok = AutoTokenizer.from_pretrained(j['hf'])
            jm = AutoModelForSequenceClassification.from_pretrained(j['hf']).to(DEVICE)
        except Exception as e:
            print(f"[판정기 실패] {j['short']}: {repr(e)[:200]}")
            continue
        labels = [jm.config.id2label[i] for i in range(len(jm.config.id2label))]
        res = {'labels': labels, 'EN': predict_probs(jm, jtok, src)}
        for name, ko in mt_out.items():
            res[name] = predict_probs(jm, jtok, ko)
        judged[j['short']] = res
        del jm
        free_memory()
    return judged


def llm_star_judgements(src, mt_out):
    """(선택) Gemini가 원문·번역문의 별점을 따로 추정. 결과는 mt_llm_star.json에 저장."""
    if not (C.USE_LLM_JUDGE and C.secret('GEMINI_KEY')):
        return {}
    path = C.OUT_DIR / 'mt_llm_star.json'
    llm_star = json.loads(path.read_text()) if path.exists() else {}
    gc_ = GeminiClient(C.LLM_JUDGE_MODEL)
    for name, texts in [('EN', src)] + list(mt_out.items()):
        if name in llm_star and len(llm_star[name]) == len(texts):
            continue
        got = gc_.batched(STAR_PROMPT, texts, 'review', 'star', desc=f'별점 판정 {name}')
        llm_star[name] = [int(v) if str(v).isdigit() and 1 <= int(v) <= 5 else None for v in got]
        path.write_text(json.dumps(llm_star))
    return llm_star


def back_translations(mt_out):
    """번역문을 BACK_MT로 영어로 되돌려 mt_back.json에 저장한다. 실패하면 이유를 출력하고 빈 dict를 돌려준다."""
    path = C.OUT_DIR / 'mt_back.json'
    back = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    todo = [n for n in mt_out if n not in back or len(back[n]) != len(mt_out[n])]
    if todo:
        try:
            btr = make_translator(C.MT_BY_NAME[C.BACK_MT], direction='ko2en')
            for name in todo:
                texts = [t if t.strip() else '.' for t in mt_out[name]]   # 빈 번역(실패 후보)은 역번역을 건너뜀
                back[name] = translate_reviews(btr, texts)
            btr.close()
            path.write_text(json.dumps(back, ensure_ascii=False), encoding='utf-8')
        except Exception as e:
            print('[역번역 실패]', repr(e)[:300])
    return back


def sentiment_metrics(name, judged, llm_star, true_sent, n):
    agree, flip, inten, simil, acc, per_review = [], [], [], [], [], []
    for jn, res in judged.items():
        vals = label_values(res['labels'])
        p_en, p_ko = res['EN'], res[name]
        s_en, s_ko = p_en @ vals, p_ko @ vals
        lab_en = np.array([native_label_to_sent(res['labels'][i]) for i in p_en.argmax(1)])
        lab_ko = np.array([native_label_to_sent(res['labels'][i]) for i in p_ko.argmax(1)])
        agree.append(np.mean(lab_en == lab_ko))
        flip.append(np.mean(((s_en > 0.33) & (s_ko < -0.33)) | ((s_en < -0.33) & (s_ko > 0.33))))
        inten.append(1 - np.mean(np.abs(s_en - s_ko)) / 2)
        simil.append(1 - np.mean(js_divergence(p_en, p_ko)))
        acc.append(np.mean(lab_ko == true_sent))
        per_review.append(s_ko - s_en)
    m = dict(agree=np.mean(agree), flip=np.mean(flip), inten=np.mean(inten), simil=np.mean(simil), acc=np.mean(acc),
             shift=np.mean(per_review, axis=0) if per_review else np.zeros(n))
    if 'EN' in llm_star and name in llm_star:
        pairs = [(a, b) for a, b in zip(llm_star['EN'], llm_star[name]) if a and b]
        m['llm_agree'] = np.mean([a == b for a, b in pairs]) if pairs else np.nan
        m['llm_diff'] = np.mean([abs(a - b) for a, b in pairs]) if pairs else np.nan
    return m


def compare(mt_eval, mt_out, mt_speed):
    """비교 표(mt_compare), 리뷰별 샘플 표(mt_samples), 원문 감성 정확도를 만들고 CSV로 저장한다."""
    import sacrebleu
    src = mt_eval['src_en'].tolist()
    true_sent = np.array(mt_eval['sentiment'])
    judged = judge_probs(src, mt_out)
    llm_star = llm_star_judgements(src, mt_out)
    back = back_translations(mt_out)

    en_acc = np.mean([np.mean(np.array([native_label_to_sent(r['labels'][i]) for i in r['EN'].argmax(1)]) == true_sent)
                      for r in judged.values()]) if judged else np.nan
    rows, shifts = [], {}
    for name, ko in mt_out.items():
        fails = [failure_reason(s, k) for s, k in zip(src, ko)]
        m = sentiment_metrics(name, judged, llm_star, true_sent, len(src))
        shifts[name] = m['shift']
        parts = [m['agree'], m['inten'], m['simil']] + ([m['llm_agree']] if not np.isnan(m.get('llm_agree', np.nan)) else [])
        keep = 100 * np.mean(parts) - 2 * 100 * m['flip']
        rows.append({
            '번역 모델': name, '종류': C.MT_BY_NAME[name]['kind'], '라이선스': C.MT_BY_NAME[name]['license'],
            '감성 유지 점수': round(keep, 1),
            '감성 일치율(%)': round(100 * m['agree'], 1), '극성 반전율(%)': round(100 * m['flip'], 1),
            '강도 유지율(%)': round(100 * m['inten'], 1), '분포 유사도(%)': round(100 * m['simil'], 1),
            'LLM 별점 일치율(%)': round(100 * m['llm_agree'], 1) if 'llm_agree' in m else None,
            'LLM 별점 차이': round(m['llm_diff'], 2) if 'llm_diff' in m else None,
            '번역문 감성 정확도(%)': round(100 * m['acc'], 1),
            '역번역 chrF': round(sacrebleu.corpus_chrf(back[name], [src]).score, 1) if name in back else None,
            '실패율(%)': round(100 * np.mean([f != '' for f in fails]), 1),
            '실패 유형': ', '.join(f'{k} {v}' for k, v in pd.Series([f for f in fails if f]).value_counts().items()) or '-',
            '속도(건/초)': round(mt_speed[name], 1) if mt_speed.get(name) else None,
        })
    mt_compare = pd.DataFrame(rows)
    mt_compare['종합 점수'] = (0.85 * mt_compare['감성 유지 점수'] + 0.15 * mt_compare['역번역 chrF'].astype(float).fillna(0)).round(1)
    mt_compare = mt_compare.sort_values('종합 점수', ascending=False).reset_index(drop=True)
    mt_compare = mt_compare.dropna(axis=1, how='all')
    mt_compare.to_csv(C.OUT_DIR / 'mt_compare.csv', index=False, encoding='utf-8-sig')

    samples = mt_eval[['review_id', 'star', 'src_en']].rename(columns={'star': '별점', 'src_en': '원문'}).copy()
    for name, ko in mt_out.items():
        samples[name] = ko
        samples[f'{name} 감성 변화'] = np.round(shifts[name], 2)
        if name in back:
            samples[f'{name} 역번역'] = back[name]
    samples.to_csv(C.OUT_DIR / 'mt_samples.csv', index=False, encoding='utf-8-sig')
    return mt_compare, samples, round(100 * en_acc, 1) if not np.isnan(en_acc) else None


def choose_main(mt_compare):
    """MAIN_MT='auto'면 종합 점수 1위(실패율 5% 이하, API 제외 옵션 적용)."""
    if C.MAIN_MT != 'auto':
        return C.MAIN_MT
    cand = mt_compare[mt_compare['실패율(%)'] <= 5]
    if not C.AUTO_ALLOW_API:
        cand = cand[cand['번역 모델'].map(lambda n: C.MT_BY_NAME[n]['kind'] not in ('gemini', 'papago'))]
    assert len(cand), '자동으로 고를 번역 후보가 없습니다. config.MAIN_MT를 직접 지정하세요.'
    return cand.iloc[0]['번역 모델']
