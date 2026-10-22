"""후기 점수화 배치 (score 모델 s2c, 합친 모델 전용). 로컬과 SageMaker Processing Job에서 같은 코드로 돈다.
입력: CSV(review_id,text) 또는 JSONL({"review_id","text"}). 로컬 경로 또는 s3://버킷/키.
출력: 확장자가 .parquet 이면 Parquet(팀 Silver 형식), 아니면 CSV. 열은 review_id,aspect,score,model_version,analyzed_at,review_date — 속성별 한 행, 3분류 열 없음.
      review_date 는 후기 작성일(KST, date)로 Iceberg 테이블의 파티션 열이다. 실행한 날이 아니다.
      Parquet 은 score int32, analyzed_at timestamp(UTC), review_date date, 나머지 string. 건수·실패 목록 요약은 같은 폴더에 쓴다(Parquet 이면 _summary_*.json — Spark/Athena 는 _ 로 시작하는 파일을 데이터로 읽지 않는다. CSV 면 <출력>.summary.json).
      --output-root 모드(작업 환경): <root>/year=/month=/day=/scores_<model_version>_<실행시각>.parquet 로 후기 작성일별 폴더에 쓴다. 파일명에 실행시각이 들어가 같은 날짜를 다시 실행해도 파일이 겹치지 않는다(staging 은 쌓이는 방식 — 중복은 MERGE 쪽에서 제거).
      파싱 실패 후기는 실패가 있을 때만 errors_<model_version>_<실행시각>.jsonl 로 쓴다.
실행: python score_batch.py --model-dir private/merged/2.4b_score_s2c --input in.csv --output out.csv
"""
import argparse
import csv
import io
import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone

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
            out.append((rid, text, review_date(r)))
    return out


KST = timezone(timedelta(hours=9))


def review_date(r):
    """후기의 작성일(KST, YYYY-MM-DD). Silver 의 review_date_kst → created_at_kst → created_at(ISO) 순으로 찾고, 없으면 ''."""
    d = str(r.get('review_date_kst') or '').strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', d):
        return d
    for key in ('created_at_kst', 'created_at'):
        v = str(r.get(key) or '').strip()
        if not v:
            continue
        try:
            t = datetime.fromisoformat(v.replace('Z', '+00:00'))
        except ValueError:
            continue
        if t.tzinfo is None:   # 시간대가 없으면 KST 로 본다
            t = t.replace(tzinfo=KST)
        return t.astimezone(KST).strftime('%Y-%m-%d')
    return ''


def part_dir(root, day):
    """<root>/year=YYYY/month=MM/day=DD (root 는 로컬 폴더 또는 s3://버킷/접두사)."""
    y, m, d = day.split('-')
    return f'{str(root).rstrip("/")}/year={y}/month={m}/day={d}'


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


COLUMNS = ['review_id', 'aspect', 'score', 'model_version', 'analyzed_at', 'review_date']


def to_bytes(path, rows, model_version, analyzed_at):
    """출력 확장자에 따라 Parquet 또는 CSV 바이트를 만든다. rows = [(review_id, aspect, score, review_date 'YYYY-MM-DD' 또는 '')]."""
    if str(path).lower().endswith('.parquet'):
        import pyarrow as pa   # Parquet 을 쓸 때만 필요하다(컨테이너는 pip install pyarrow)
        import pyarrow.parquet as pq
        ts = datetime.fromisoformat(analyzed_at)
        schema = pa.schema([('review_id', pa.string()), ('aspect', pa.string()), ('score', pa.int32()),
                            ('model_version', pa.string()), ('analyzed_at', pa.timestamp('us', tz='UTC')),
                            ('review_date', pa.date32())])
        table = pa.table({'review_id': [r[0] for r in rows], 'aspect': [r[1] for r in rows], 'score': [r[2] for r in rows],
                          'model_version': [model_version] * len(rows), 'analyzed_at': [ts] * len(rows),
                          'review_date': [date.fromisoformat(r[3]) if r[3] else None for r in rows]}, schema=schema)
        buf = io.BytesIO()
        pq.write_table(table, buf, compression='snappy')
        return buf.getvalue()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(COLUMNS)
    for rid, asp, sc, day in rows:
        w.writerow([rid, asp, sc, model_version, analyzed_at, day])
    return buf.getvalue().encode('utf-8-sig')


def errors_bytes(review_ids, model_version, analyzed_at, error='PARSE_FAILED'):
    """오류 후기 목록을 JSON Lines 바이트로 만든다(비어 있으면 빈 파일)."""
    return ''.join(json.dumps(dict(review_id=rid, model_version=model_version, analyzed_at=analyzed_at, error=error),
                              ensure_ascii=False) + '\n' for rid in review_ids).encode('utf-8')


def summary_path(output):
    """요약 파일 위치. Parquet 은 데이터 폴더에 섞여도 읽는 쪽이 무시하도록 _ 로 시작하는 이름을 쓴다."""
    out = str(output)
    if out.lower().endswith('.parquet'):
        head, _, name = out.rpartition('/')
        return (head + '/' if head else '') + '_summary_' + name[:-len('.parquet')] + '.json'
    return out + '.summary.json'


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
    ap.add_argument('--output', default=None, help='결과 파일 하나(.parquet 또는 .csv), 날짜를 나누지 않는다. --output-root 와 둘 중 하나만 지정')
    ap.add_argument('--output-root', default=None, help='후기 작성일(KST)별로 <root>/year=/month=/day=/scores_<model_version>_<실행시각>.parquet 를 나눠 쓴다(로컬/S3)')
    ap.add_argument('--error-root', default=None, help='--output-root 와 같은 방식으로 <root>/year=/month=/day=/errors_<model_version>_<실행시각>.jsonl 에 파싱 실패 후기를 쓴다(실패가 있을 때만)')
    ap.add_argument('--default-date', default=None, help='작성일을 알 수 없는 후기에 쓸 날짜(YYYY-MM-DD). 없으면 그런 후기는 점수를 매기지 않고 오류(no_review_date)로 남긴다')
    ap.add_argument('--bs', type=int, default=16)
    ap.add_argument('--model-version', default=os.environ.get('MODEL_VERSION', 'unknown'), help='출력 열 model_version 에 넣는 값(파일명 규칙 [A-Za-z0-9._-])')
    ap.add_argument('--error-dir', default=None, help='(--output 모드) 파싱 실패 후기를 errors_<model_version>_<실행시각>.jsonl 로 쓸 폴더(실패가 있을 때만)')
    a = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9._-]+', a.model_version):
        raise SystemExit(f'model_version 형식 오류: {a.model_version!r}')
    if bool(a.output) == bool(a.output_root):
        raise SystemExit('--output 과 --output-root 중 하나만 지정하세요')
    if a.default_date and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', a.default_date):
        raise SystemExit('--default-date 형식은 YYYY-MM-DD')
    t0 = time.time()
    analyzed_at = datetime.now(timezone.utc).isoformat(timespec='seconds')   # 이번 실행의 분석 시각(UTC), 모든 행이 같은 값
    stamp = analyzed_at.replace('-', '').replace(':', '').replace('+0000', 'Z').replace('+00:00', 'Z')   # 파일명용 실행시각 (예: 20261022T005806Z)
    reviews = read_reviews(a.input)
    if a.output_root:
        reviews = [(rid, text, day or a.default_date or '') for rid, text, day in reviews]
    print(f'입력 후기 {len(reviews)}건', flush=True)
    nodate = [rid for rid, _, day in reviews if a.output_root and not day]   # 작성일을 몰라 파티션을 정할 수 없는 후기
    todo = [i for i, r in enumerate(reviews) if not (a.output_root and not r[2])]
    tok, model = load_model(a.model_dir)
    order = sorted(todo, key=lambda i: len(reviews[i][1]))   # 길이가 비슷한 후기끼리 묶어 패딩을 줄인다
    res, failed = {}, []
    for s in range(0, len(order), a.bs):
        idx = order[s:s + a.bs]
        for i, raw in zip(idx, generate(tok, model, [reviews[i][1] for i in idx])):
            p = parse(raw)
            if p is None:
                failed.append(reviews[i][0])
            res[i] = p or {}
    rows_by_day, failed_by_day, no_aspect = {}, {}, 0
    failed_set = set(failed)
    for i in todo:
        rid, _, day = reviews[i]
        if not res[i]:
            no_aspect += 1
        for asp, sc in res[i].items():
            rows_by_day.setdefault(day, []).append((rid, asp, sc, day))
        if rid in failed_set:
            failed_by_day.setdefault(day, []).append(rid)
    n_rows = sum(len(v) for v in rows_by_day.values())
    if a.output:   # 단일 파일 모드(로컬 시험용): 날짜를 나누지 않는다
        rows = [r for v in rows_by_day.values() for r in v]
        write_bytes(a.output, to_bytes(a.output, rows, a.model_version, analyzed_at))
        if a.error_dir and failed:
            write_bytes(a.error_dir.rstrip('/') + f'/errors_{a.model_version}_{stamp}.jsonl', errors_bytes(failed, a.model_version, analyzed_at))
        summary_file = summary_path(a.output)
    else:          # 작성일별 파티션 모드: 각 후기를 자기 작성일 폴더에 쓴다
        days = sorted(rows_by_day)
        for day in days:
            write_bytes(f'{part_dir(a.output_root, day)}/scores_{a.model_version}_{stamp}.parquet',
                        to_bytes('x.parquet', rows_by_day[day], a.model_version, analyzed_at))
        if a.error_root:
            # 실패가 있는 날짜에만 오류 파일을 쓴다. 파일명에 실행시각이 있어 이전 실행의 기록을 덮어쓰지 않는다
            for day in sorted(d for d in failed_by_day if d):
                write_bytes(f'{part_dir(a.error_root, day)}/errors_{a.model_version}_{stamp}.jsonl',
                            errors_bytes(failed_by_day[day], a.model_version, analyzed_at))
            if nodate:
                write_bytes(f'{a.error_root.rstrip("/")}/no_review_date/errors_{a.model_version}_{stamp}.jsonl',
                            errors_bytes(nodate, a.model_version, analyzed_at, 'NO_REVIEW_DATE'))
        summary_file = f'{a.output_root.rstrip("/")}/_summary_scores_{a.model_version}_{stamp}.json'
    summary = dict(모델버전=a.model_version, 분석시각=analyzed_at, 입력후기=len(reviews), 출력행=n_rows, 속성없음후기=no_aspect,
                   파싱실패=len(failed), 파싱실패_review_id=failed, 작성일없음_review_id=nodate,
                   작성일별_출력행={d: len(v) for d, v in sorted(rows_by_day.items())},
                   초=round(time.time() - t0), 초당=round(len(reviews) / max(time.time() - t0, 1e-6), 2))
    write_bytes(summary_file, json.dumps(summary, ensure_ascii=False, indent=1).encode('utf-8'))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
