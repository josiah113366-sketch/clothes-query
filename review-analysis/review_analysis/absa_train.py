"""ABSA 증류 학습: Gemini가 만든 속성별 감성 라벨로 작은 인코더(KLUE-RoBERTa 등)를 학습한다.
리뷰 하나를 입력하면 속성 10개 각각에 대해 {미언급, 긍정, 부정, 중립} 4분류를 동시에 낸다(다중 헤드).
torch/transformers와 GPU 환경(Colab 등)에서 실행한다. 이 PC에서는 실행해 보지 못했다(문법 검사만 함)."""
import random
import time

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader
from tqdm.auto import tqdm
from transformers import AutoModel, AutoTokenizer, get_linear_schedule_with_warmup

from . import config as C
from .absa import ASPECTS, compare, per_aspect

CLASSES = ['미언급', '긍정', '부정', '중립']   # 0 = 미언급 (출력하지 않음)
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'


def to_labels(gold):
    """{속성: 감성} → 길이 10의 정수 리스트."""
    return [CLASSES.index(gold[a]) if a in gold else 0 for a in ASPECTS]


def from_labels(ids):
    return {a: CLASSES[i] for a, i in zip(ASPECTS, ids) if i != 0}


class AbsaModel(nn.Module):
    def __init__(self, name):
        super().__init__()
        self.enc = AutoModel.from_pretrained(name)
        self.drop = nn.Dropout(0.1)
        self.head = nn.Linear(self.enc.config.hidden_size, len(ASPECTS) * len(CLASSES))

    def forward(self, **batch):
        h = self.enc(**batch).last_hidden_state[:, 0]          # [CLS] 위치
        return self.head(self.drop(h)).view(-1, len(ASPECTS), len(CLASSES))


def _loader(tok, items, shuffle, bs):
    def collate(b):
        enc = tok([x[0] for x in b], truncation=True, max_length=C.MAX_LEN, padding=True, return_tensors='pt')
        enc['labels'] = torch.tensor([x[1] for x in b], dtype=torch.long)
        return enc
    return DataLoader(items, batch_size=bs, shuffle=shuffle, collate_fn=collate)


@torch.inference_mode()
def predict(model, tok, texts, bs=64):
    model.eval()
    out = []
    for batch in _loader(tok, [(t, [0] * len(ASPECTS)) for t in texts], False, bs):
        batch.pop('labels')
        logits = model(**{k: v.to(DEVICE) for k, v in batch.items()})
        out += logits.argmax(-1).cpu().tolist()
    return [from_labels(ids) for ids in out]


def train_absa(train, val, test, model_name='klue/roberta-base', epochs=10, lr=5e-5, bs=16, seed=C.SEED):
    """train/val/test: [(text, {속성: 감성})]. 검증 탐지 F1이 가장 좋은 에폭의 가중치로 테스트를 평가한다."""
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    tok = AutoTokenizer.from_pretrained(model_name)
    model = AbsaModel(model_name).to(DEVICE)
    tr = _loader(tok, [(t, to_labels(g)) for t, g in train], True, bs)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=C.WEIGHT_DECAY)
    sched = get_linear_schedule_with_warmup(opt, int(0.1 * epochs * len(tr)), epochs * len(tr))
    # 대부분의 (속성, 리뷰) 칸이 '미언급'이라 그대로 학습하면 전부 미언급으로 답하는 쪽으로 무너진다 → 드문 클래스에 가중치
    counts = np.bincount([y for _, g in train for y in to_labels(g)], minlength=len(CLASSES)).astype(float) + 1.0
    weight = torch.tensor((counts.sum() / (len(CLASSES) * counts)) ** 0.5, dtype=torch.float).to(DEVICE)
    best, best_state = -1.0, None
    for ep in range(1, epochs + 1):
        model.train()
        for batch in tqdm(tr, desc=f'epoch {ep}', leave=False):
            batch = {k: v.to(DEVICE) for k, v in batch.items()}
            y = batch.pop('labels')
            loss = nn.functional.cross_entropy(model(**batch).reshape(-1, len(CLASSES)), y.reshape(-1), weight=weight)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
        f1 = compare([g for _, g in val], predict(model, tok, [t for t, _ in val]))['탐지_F1']
        print(f'  epoch {ep}: 검증 속성 탐지 F1 {f1:.3f}')
        if f1 > best:
            best, best_state = f1, {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    gold, pred = [g for _, g in test], predict(model, tok, [t for t, _ in test])
    return dict(전체=compare(gold, pred), 속성별=per_aspect(gold, pred)), model, tok
