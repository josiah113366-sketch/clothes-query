"""감성(별점) 분류 모델 학습·평가. GPU가 없으면 매우 느리니 Colab 등에서 실행할 것.
영어 실험과 같은 코드이고 입력 열(text_col)만 바꿀 수 있다."""
import random
import time

import numpy as np
import torch
from sklearn.metrics import accuracy_score, f1_score
from torch.utils.data import DataLoader
from tqdm.auto import tqdm
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from . import config as C
from .data import STARS
from .translators import dtype_kw, free_memory

DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
USE_AMP = DEVICE == 'cuda'
ID2LABEL = {i: f'{i + 1} star' for i in range(5)}
LABEL2ID = {v: k for k, v in ID2LABEL.items()}


def set_seed(seed):
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def make_loader(tok, texts, labels=None, batch_size=32, shuffle=False):
    items = list(zip(texts, labels)) if labels is not None else [(t, None) for t in texts]

    def collate(batch):
        enc = tok([b[0] for b in batch], truncation=True, max_length=C.MAX_LEN, padding=True, return_tensors='pt')
        if labels is not None:
            enc['labels'] = torch.tensor([b[1] for b in batch], dtype=torch.long)
        return enc

    g = torch.Generator().manual_seed(C.SEED)
    return DataLoader(items, batch_size=batch_size, shuffle=shuffle, collate_fn=collate, generator=g)


@torch.inference_mode()
def predict_probs(model, tok, texts):
    """문장 목록에 대한 클래스별 확률(softmax)을 numpy 배열로 돌려준다."""
    model.eval()
    out = []
    for batch in make_loader(tok, texts, batch_size=C.EVAL_BATCH_SIZE):
        batch = {k: v.to(DEVICE) for k, v in batch.items()}
        with torch.autocast(device_type='cuda', dtype=torch.float16, enabled=USE_AMP):
            logits = model(**batch).logits
        out.append(torch.softmax(logits.float(), dim=-1).cpu().numpy())
    return np.concatenate(out)


def zero_shot(cfg, texts):
    """학습 전 원래 모델로 예측해 원래 라벨 이름 목록을 돌려준다."""
    tok = AutoTokenizer.from_pretrained(cfg['hf'])
    model = AutoModelForSequenceClassification.from_pretrained(cfg['hf']).to(DEVICE)
    probs = predict_probs(model, tok, texts)
    id2label = model.config.id2label
    override = cfg.get('label_override', {})
    labels = [override.get(id2label[i], id2label[i]) for i in probs.argmax(1)]
    del model
    free_memory()
    return labels


def fine_tune(cfg, train_df, val_df, test_df, text_col):
    """모델 하나를 파인튜닝하고, 테스트 예측과 학습 기록을 돌려준다."""
    set_seed(C.SEED)
    tok = AutoTokenizer.from_pretrained(cfg['hf'])
    model = AutoModelForSequenceClassification.from_pretrained(
        cfg['hf'], num_labels=5, id2label=ID2LABEL, label2id=LABEL2ID,
        ignore_mismatched_sizes=True, **{dtype_kw(): torch.float32}).to(DEVICE)
    n_params = sum(p.numel() for p in model.parameters())

    train_loader = make_loader(tok, train_df[text_col].tolist(), train_df['label'].tolist(),
                               batch_size=C.BATCH_SIZE, shuffle=True)
    total_steps = C.EPOCHS * len(train_loader)
    warmup_steps = int(C.WARMUP_RATIO * total_steps)
    optimizer = torch.optim.AdamW(model.parameters(), lr=C.LR, weight_decay=C.WEIGHT_DECAY)

    def lr_lambda(step):
        if step < warmup_steps:
            return (step + 1) / max(1, warmup_steps)
        return max(0.0, (total_steps - step) / max(1, total_steps - warmup_steps))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)
    scaler = torch.amp.GradScaler(enabled=USE_AMP)

    history, best_f1, best_state, best_epoch, bad_epochs = [], -1.0, None, 0, 0
    t0 = time.time()
    for epoch in range(1, C.EPOCHS + 1):
        model.train()
        running = 0.0
        for batch in tqdm(train_loader, desc=f"{cfg['short']} epoch {epoch}", leave=False):
            batch = {k: v.to(DEVICE) for k, v in batch.items()}
            with torch.autocast(device_type='cuda', dtype=torch.float16, enabled=USE_AMP):
                loss = model(**batch).loss
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer); scaler.update()
            optimizer.zero_grad(set_to_none=True)
            scheduler.step()
            running += loss.item()

        val_pred = predict_probs(model, tok, val_df[text_col].tolist()).argmax(1) + 1
        val_acc = float(accuracy_score(val_df['star'], val_pred))
        val_f1 = float(f1_score(val_df['star'], val_pred, labels=STARS, average='macro', zero_division=0))
        history.append(dict(epoch=epoch, train_loss=running / len(train_loader), val_accuracy=val_acc, val_macro_f1=val_f1))
        print(f"  epoch {epoch}: train_loss={history[-1]['train_loss']:.4f}  val_acc={val_acc:.4f}  val_macroF1={val_f1:.4f}")

        if val_f1 > best_f1:
            best_f1, best_epoch, bad_epochs = val_f1, epoch, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            bad_epochs += 1
            if bad_epochs >= C.PATIENCE:
                print('  검증 성능이 나아지지 않아 조기 종료합니다.')
                break
    train_minutes = (time.time() - t0) / 60

    model.load_state_dict(best_state)
    t1 = time.time()
    probs = predict_probs(model, tok, test_df[text_col].tolist())
    infer_sec = time.time() - t1

    if C.SAVE_MODELS:
        save_dir = C.MODELS_DIR / cfg['short']
        model.save_pretrained(save_dir); tok.save_pretrained(save_dir)

    del model, best_state, optimizer, scaler
    free_memory()
    return dict(n_params=int(n_params), history=history, best_epoch=best_epoch, train_minutes=train_minutes,
                infer_per_sec=len(test_df) / infer_sec, test_pred=(probs.argmax(1) + 1).tolist(),
                test_conf=probs.max(1).round(4).tolist(), test_probs=probs.round(4).tolist())
