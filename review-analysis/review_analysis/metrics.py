"""평가 지표 (torch 없이 동작)."""
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, mean_absolute_error

from .data import SENT_ORDER, STAR2SENT, STARS


def native_label_to_star(label):
    """모델의 원래 라벨 이름을 별점(1~5)으로 바꾼다. 바꿀 수 없으면 None."""
    s = str(label).lower().strip()
    if 'star' in s:
        digits = [c for c in s if c.isdigit()]
        return int(digits[0]) if digits else None
    five = {'very negative': 1, 'negative': 2, 'neutral': 3, 'positive': 4, 'very positive': 5}
    return five.get(s)


def native_label_to_sent(label):
    """모델의 원래 라벨 이름을 부정/중립/긍정으로 바꾼다."""
    s = str(label).lower()
    if 'star' in s:
        return STAR2SENT.get(native_label_to_star(s))
    if 'neg' in s:
        return '부정'
    if 'neu' in s:
        return '중립'
    if 'pos' in s:
        return '긍정'
    return None


def compute_metrics(y_true, y_pred, categories):
    """실제 별점·예측 별점·카테고리 배열을 받아 모든 지표를 dict로 돌려준다."""
    y_true, y_pred, categories = np.asarray(y_true), np.asarray(y_pred), np.asarray(categories)
    sent_true = np.array([STAR2SENT[s] for s in y_true])
    sent_pred = np.array([STAR2SENT[s] for s in y_pred])
    return dict(
        accuracy=float(accuracy_score(y_true, y_pred)),
        macro_f1=float(f1_score(y_true, y_pred, labels=STARS, average='macro', zero_division=0)),
        within1=float(np.mean(np.abs(y_true - y_pred) <= 1)),
        mae=float(mean_absolute_error(y_true, y_pred)),
        sent_accuracy=float(accuracy_score(sent_true, sent_pred)),
        per_star={int(s): float(np.mean(y_pred[y_true == s] == s)) for s in STARS if (y_true == s).any()},
        per_category={str(c): float(np.mean(y_pred[categories == c] == y_true[categories == c]))
                      for c in pd.unique(categories)},
        per_sentiment={s: float(np.mean(sent_pred[sent_true == s] == s)) for s in SENT_ORDER if (sent_true == s).any()},
        confusion=confusion_matrix(y_true, y_pred, labels=STARS).tolist(),
    )


def zero_shot_metrics(native_labels, y_true):
    """학습 전 모델의 원래 출력으로 감성(3분류)·별점 정확도를 잰다."""
    y_true = np.asarray(y_true)
    sent_true = np.array([STAR2SENT[s] for s in y_true])
    sent_pred = np.array([native_label_to_sent(l) for l in native_labels], dtype=object)
    stars = [native_label_to_star(l) for l in native_labels]
    out = dict(zs_sent_accuracy=float(np.mean(sent_pred == sent_true)))
    if all(s is not None for s in stars):
        out['zs_star_accuracy'] = float(np.mean(np.array(stars) == y_true))
    return out


def pct(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(100 * x, 1)
