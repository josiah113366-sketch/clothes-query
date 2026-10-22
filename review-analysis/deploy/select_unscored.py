"""아직 점수가 없는 후기만 골라 새 입력 파일로 쓴다 (Job 시작 전 단계).

흐름
  1. 그날의 Silver 후기 파일(JSONL, S3)을 읽는다.
  2. Athena 로 후기별 점수 로그 테이블(review_score_log)에서 "현재 모델 번호(model_version_no)로 이미 점수를 매긴 review_id"를 조회한다.
  3. 입력에서 그 review_id 를 빼고, 남은 후기를 <unscored_prefix>/year=/month=/day=/unscored_<실행시각>.jsonl 로 쓴다.
  4. 남은 후기가 0건이면 파일을 쓰지 않고 정상 종료한다(Job 을 띄우지 않는다).

왜 점수 테이블이 아니라 점수 로그를 보나: 속성이 하나도 안 나온 후기는 점수 행이 없어서, 점수 테이블만 보면 "점수 없음"으로 보여
매일 다시 점수화 대상이 된다. 점수 로그에는 그런 후기도 한 행(n_aspects=0)이 남는다. 파싱에 실패한 후기는 로그에 없으므로 다시 선택된다.
모델을 올려서 model_version_no 가 커지면 로그에 새 번호의 행이 없으므로 모든 후기가 다시 선택된다(재점수화).

주의: Job 이 끝난 뒤 merge.sql 과 merge_log.sql 을 실행해 로그 테이블에 반영해야 다음 실행에서 "이미 점수 있음"으로 인식된다.
      반영 전에 이 스크립트를 다시 실행하면 같은 후기가 다시 선택된다.

실행(단독): python deploy/select_unscored.py --input-key silver/reviews/scopes/<scope>/year=2026/month=10/day=21/part-00000.jsonl [--dry-run]
마지막 줄에 결과 JSON 한 줄을 출력한다: {"input": N, "duplicate": D, "scored": M, "unscored": K, "output_key": "..." 또는 null}
(run_processing_job.py --select-unscored 가 이 모듈을 불러 쓴다.)
"""
import argparse
import json
import re
import time
from datetime import datetime, timezone

SSM_SAGEMAKER = '/clothes-query/dev/sagemaker-review-score/config'
SSM_ATHENA = '/clothes-query/dev/athena-review-score/config'
VERSION_NO_RE = re.compile(r'\d{1,2}\.\d')   # 모델 번호 "x.y" (decimal(4,1))
DATE_IN_KEY = re.compile(r'year=(\d{4})/month=(\d{2})/day=(\d{2})')


def split_s3(uri):
    assert uri.startswith('s3://'), uri
    b, _, k = uri[5:].partition('/')
    return b, k


def read_jsonl_lines(text):
    """JSONL 본문을 (review_id, 원본 줄, 작성일 KST 또는 '') 목록으로 바꾼다. 빈 줄은 건너뛴다. review_id 가 없는 줄은 오류."""
    from score_batch import review_date   # 점수화 때와 같은 방식으로 작성일(KST)을 읽는다
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        rid = str(row.get('review_id', '')).strip()
        if not rid:
            raise ValueError(f'{n}번째 줄에 review_id 가 없습니다')
        out.append((rid, line, review_date(row)))
    return out


def filter_unscored(rows, scored_ids):
    """이미 점수가 있는 review_id 를 뺀다. 입력 안의 중복 review_id 는 첫 줄만 남긴다."""
    seen, out = set(), []
    for rid, line, day in rows:
        if rid in scored_ids or rid in seen:
            continue
        seen.add(rid)
        out.append((rid, line, day))
    return out


def log_query(database, table, model_version_no, rows):
    """현재 모델 번호로 점수 로그가 있는 review_id 를 찾는 SQL. 입력에 나온 작성일 범위로 좁혀 스캔량을 줄인다."""
    if not isinstance(model_version_no, str) or not VERSION_NO_RE.fullmatch(model_version_no):
        raise ValueError(f'model_version_no 는 "x.y" 형식(예: 1.0)이어야 합니다: {model_version_no!r}')
    if not re.fullmatch(r'[A-Za-z0-9_]+', database) or not re.fullmatch(r'[A-Za-z0-9_]+', table):
        raise ValueError('데이터베이스·테이블 이름 형식 오류')
    days = sorted({d for _, _, d in rows if d})
    where = f"model_version_no = DECIMAL '{model_version_no}'"
    if days:
        for d in (days[0], days[-1]):
            datetime.strptime(d, '%Y-%m-%d')   # 형식 검증(SQL 에 직접 넣으므로)
        where += f" AND review_date BETWEEN DATE '{days[0]}' AND DATE '{days[-1]}'"
    return f'SELECT DISTINCT review_id FROM {database}.{table} WHERE {where}'


def run_athena_ids(athena, workgroup, sql, poll=3, timeout=600):
    """Athena 쿼리를 실행하고 첫 열(review_id)을 집합으로 돌려준다."""
    qid = athena.start_query_execution(QueryString=sql, WorkGroup=workgroup)['QueryExecutionId']
    t0 = time.time()
    while True:
        st = athena.get_query_execution(QueryExecutionId=qid)['QueryExecution']['Status']
        if st['State'] in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
            break
        if time.time() - t0 > timeout:
            raise TimeoutError(f'Athena 쿼리가 {timeout}초 안에 끝나지 않았습니다: {qid}')
        time.sleep(poll)
    if st['State'] != 'SUCCEEDED':
        raise RuntimeError(f"Athena 쿼리 실패({st['State']}): {st.get('StateChangeReason', '')}")
    ids, first = set(), True
    for page in athena.get_paginator('get_query_results').paginate(QueryExecutionId=qid):
        for r in page['ResultSet']['Rows']:
            if first:   # 첫 행은 헤더
                first = False
                continue
            v = r['Data'][0].get('VarCharValue')
            if v:
                ids.add(v)
    return ids


def output_key(unscored_prefix, day, stamp):
    """미점수 입력 파일 키. day(YYYY-MM-DD)는 보관 정리를 위한 폴더 이름일 뿐이다."""
    y, m, d = day.split('-')
    return f'{unscored_prefix.strip("/")}/year={y}/month={m}/day={d}/unscored_{stamp}.jsonl'


def select_unscored(s3, athena, bucket, input_key, unscored_prefix, athena_cfg, model_version_no, date=None, dry_run=False, now=None):
    """미점수 후기만 골라 새 입력 파일을 쓰고 결과 dict 를 돌려준다. 0건이면 output_key 는 None."""
    text = s3.get_object(Bucket=bucket, Key=input_key)['Body'].read().decode('utf-8-sig')
    rows = read_jsonl_lines(text)
    sql = log_query(athena_cfg['database'], athena_cfg['log_table'], model_version_no, rows)
    scored = run_athena_ids(athena, athena_cfg['workgroup'], sql)
    unique = filter_unscored(rows, set())          # 입력 안의 중복 review_id 만 제거한 목록
    rest = filter_unscored(rows, scored)
    result = {'input': len(rows), 'duplicate': len(rows) - len(unique), 'scored': len(unique) - len(rest),
              'unscored': len(rest), 'output_key': None}
    if not rest:
        return result
    now = now or datetime.now(timezone.utc)
    m = DATE_IN_KEY.search(input_key)
    day = date or (f'{m.group(1)}-{m.group(2)}-{m.group(3)}' if m else now.strftime('%Y-%m-%d'))
    key = output_key(unscored_prefix, day, now.strftime('%Y%m%dT%H%M%SZ'))
    result['output_key'] = key
    if not dry_run:
        body = ''.join(line.rstrip('\r\n') + '\n' for _, line, _ in rest).encode('utf-8')
        s3.put_object(Bucket=bucket, Key=key, Body=body)
    return result


def load_configs(ssm, ssm_sagemaker=SSM_SAGEMAKER, ssm_athena=SSM_ATHENA):
    sm = json.loads(ssm.get_parameter(Name=ssm_sagemaker)['Parameter']['Value'])
    at = json.loads(ssm.get_parameter(Name=ssm_athena)['Parameter']['Value'])
    return sm, at


def main():
    import boto3
    ap = argparse.ArgumentParser(description='아직 점수가 없는 후기만 골라 새 입력 파일로 쓴다')
    ap.add_argument('--input-key', required=True, help='버킷 안의 Silver 후기 JSONL 파일 키')
    ap.add_argument('--date', default=None, help='출력 폴더 날짜(YYYY-MM-DD). 기본은 입력 키의 year=/month=/day=')
    ap.add_argument('--model-version-no', default=None, help='모델 번호 "x.y"(예: 1.0). 기본은 SSM 설정의 model_version_no')
    ap.add_argument('--region', default='ap-northeast-1')
    ap.add_argument('--dry-run', action='store_true', help='개수만 세고 파일은 쓰지 않는다')
    a = ap.parse_args()
    ssm = boto3.client('ssm', region_name=a.region)
    sm_cfg, at_cfg = load_configs(ssm)
    no = a.model_version_no if a.model_version_no is not None else sm_cfg.get('model_version_no')
    res = select_unscored(boto3.client('s3', region_name=a.region), boto3.client('athena', region_name=a.region), sm_cfg['bucket'],
                          a.input_key, sm_cfg['unscored_prefix'], at_cfg, no, a.date, a.dry_run)
    print(f"입력 {res['input']}건(입력 안 중복 {res['duplicate']}건), 이미 점수 있음 {res['scored']}건, 점수 필요 {res['unscored']}건"
          + ('  → 남은 후기가 없어 Job 을 띄우지 않아도 됩니다' if not res['unscored'] else f"  → {res['output_key']}"))
    print(json.dumps(res, ensure_ascii=False))


if __name__ == '__main__':
    main()
