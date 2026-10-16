"""후기 점수화 배치 (score 모델 s2c, 합친 모델 전용). 로컬과 SageMaker Processing Job에서 같은 코드로 돈다.
입력: CSV(review_id,text) 또는 JSONL({"review_id","text"}). 로컬 경로 또는 s3://버킷/키.
출력: CSV(review_id,aspect,score) — 속성별 한 행, 3분류 열 없음. 같은 위치에 <출력>.summary.json(건수·실패 목록)도 쓴다.
실행: python score_batch.py --model-dir private/merged/2.4b_score_s2c --input in.csv --output out.csv
"""
import argparse
import csv
import io
import json
import os
import re
import time

ASPECTS = ['재질·촉감', '사이즈·핏', '색상·디자인', '품질·내구성', '가격·가성비', '냄새', '세탁·관리', '활용성·사용감', '배송', '포장', '교환·환불·CS']
# 학습·평가에 쓴 프롬프트(review_analysis/score.py SHORT_SCORE)와 같아야 한다. 같은지는 deploy/check_prompt.py가 검사한다
PROMPT = (f'의류 리뷰에서 리뷰가 실제로 평가한 속성과 점수를 추출하세요. 속성: {", ".join(ASPECTS)}. '
          '점수는 정수 -2~2: 2=분명한 만족·칭찬(좋아요, 마음에 들어요, 최고예요), 1=약한 만족(나쁘지 않아요, 괜찮은 것 같아요, 적당해요, 단서가 붙은 만족), 0=보통·무난 또는 장단점 혼재, '
          '-1=약한 불만·의견형 불만(별로예요, 아쉬워요, 좀 크네요, 좋진 않아요), -2=분명한 불만(작아요·줄어들어요 같은 단정적 문제, 너무 ~해요, 최악이에요, 못 입겠어요). '
          '평가 없이 사실만 적었거나 추측·조언·코디 이야기인 속성은 출력하지 마세요. '
          '{"aspects": [{"aspect": "속성", "score": 점수}]} 형식의 JSON 객체 하나만 출력하세요.\n리뷰: ')
MAX_CHARS = 1500   # 학습 때 프롬프트 최대 640토큰이었으므로 너무 긴 후기는 잘라서 넣는다


def is_s3(p):
    return str(p).startswith('s3://')


def s3_client():
    import boto3   # 로컬 파일만 쓸 때는 필요 없다
    return boto3.client('s3')


def read_bytes(path):
    if is_s3(path):
        b, k = path[5:].split('/', 1)
        return s3_client().get_object(Bucket=b, Key=k)['Body'].read()
    with open(path, 'rb') as f:
        return f.read()


def write_bytes(path, data):
    if is_s3(path):
        b, k = path[5:].split('/', 1)
        s3_client().put_object(Bucket=b, Key=k, Body=data)
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)


def read_reviews(path):
    raw = read_bytes(path).decode('utf-8-sig')
    if path.lower().endswith(('.jsonl', '.ndjson')):
        rows = [json.loads(x) for x in raw.splitlines() if x.strip()]
    else:
        rows = list(csv.DictReader(io.StringIO(raw)))
    out = []
    for r in rows:
        rid, text = str(r.get('review_id', '')).strip(), str(r.get('text', '')).strip()
        if rid and text:
            out.append((rid, text))
    return out


def parse(text):
    m = re.search(r'\{.*\}', text, re.S)
    try:
        arr = json.loads(m.group(0)).get('aspects')
    except Exception:
        return None
    d = {}
    for a in (arr or []):
        if isinstance(a, dict) and a.get('aspect') in ASPECTS and a['aspect'] not in d:
            try:
                s = int(round(float(a.get('score'))))
            except (TypeError, ValueError):
                continue
            d[a['aspect']] = max(-2, min(2, s))
    return d


def load_model(model_dir):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    t = time.time()
    tok = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True, padding_side='left')
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    if dev == 'cpu':
        print('경고: GPU가 없어 CPU로 실행합니다(매우 느림)', flush=True)
    model = AutoModelForCausalLM.from_pretrained(model_dir, trust_remote_code=True, torch_dtype=torch.bfloat16, device_map=dev).eval()
    print(f'모델 로드 {time.time() - t:.0f}초 ({dev})', flush=True)
    return tok, model


def generate(tok, model, texts, max_new=160):
    import torch
    msgs = [tok.apply_chat_template([{'role': 'user', 'content': PROMPT + x[:MAX_CHARS]}], add_generation_prompt=True, tokenize=False) for x in texts]
    enc = tok(msgs, return_tensors='pt', padding=True, add_special_tokens=False).to(model.device)
    with torch.no_grad():
        out = model.generate(**enc, max_new_tokens=max_new, do_sample=False, pad_token_id=tok.pad_token_id)
    return [tok.decode(o[enc.input_ids.shape[1]:], skip_special_tokens=True) for o in out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model-dir', default=os.environ.get('MODEL_DIR', '/opt/ml/processing/model'))
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--bs', type=int, default=16)
    a = ap.parse_args()
    t0 = time.time()
    reviews = read_reviews(a.input)
    print(f'입력 후기 {len(reviews)}건', flush=True)
    tok, model = load_model(a.model_dir)
    order = sorted(range(len(reviews)), key=lambda i: len(reviews[i][1]))   # 길이가 비슷한 후기끼리 묶어 패딩을 줄인다
    res, failed = {}, []
    for s in range(0, len(order), a.bs):
        idx = order[s:s + a.bs]
        for i, raw in zip(idx, generate(tok, model, [reviews[i][1] for i in idx])):
            p = parse(raw)
            if p is None:
                failed.append(reviews[i][0])
            res[i] = p or {}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(['review_id', 'aspect', 'score'])
    n_rows = no_aspect = 0
    for i, (rid, _) in enumerate(reviews):
        if not res[i]:
            no_aspect += 1
        for asp, sc in res[i].items():
            w.writerow([rid, asp, sc]); n_rows += 1
    write_bytes(a.output, buf.getvalue().encode('utf-8-sig'))
    summary = dict(입력후기=len(reviews), 출력행=n_rows, 속성없음후기=no_aspect, 파싱실패=len(failed), 파싱실패_review_id=failed,
                   초=round(time.time() - t0), 초당=round(len(reviews) / max(time.time() - t0, 1e-6), 2))
    write_bytes(a.output + '.summary.json', json.dumps(summary, ensure_ascii=False, indent=1).encode('utf-8'))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
