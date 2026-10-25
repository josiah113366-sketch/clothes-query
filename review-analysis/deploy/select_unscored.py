"""아직 점수가 없는 후기만 골라 새 입력 파일로 쓴다 (Job 시작 전 단계).

두 가지 방식이 있다.
  (A) Silver 실행 출력에서 고르기 (기본, 운영용) — `--input-key` 를 주지 않는다.
      Silver 리뷰는 Spark 가 실행(run)별 경로에 쓴다: silver/runtime/reviews/runs/<run_id>/silver_reviews/ (Parquet, 그 실행의 전체 스냅샷).
      경로가 실행마다 바뀌므로 파일을 직접 가리키지 않고, athena 스택이 만든 읽기 전용 외부 테이블(silver_reviews_runs, run_id 파티션 프로젝션)을 Athena 로 읽는다.
        1. 어느 실행을 읽을지 정한다: 기본은 silver/runtime/reviews/current.json 의 run_id(status 가 PASS 가 아니면 중단). --run-id 로 직접 지정할 수도 있다
           (그 경우 completed/<run_id>.json 의 status 가 PASS 인지 확인한다).
        2. Athena 한 번으로 "그 실행의 후기 LEFT JOIN 점수 로그(현재 모델 번호)에서 로그가 없는 후기"만 가져온다.
        3. --max-reviews(기본 1500)건만 잘라 JSONL 로 쓰고 남은 건수를 알려 준다. (Job 한 번이 약 2,200건이 한계라서 잘라서 여러 번 돌린다)
  (B) 입력 파일 하나에서 고르기 (시험용) — `--input-key` 로 JSONL 파일 키를 준다. 아래 "흐름"이 이 방식이다.

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

실행(단독):
  (A) python deploy/select_unscored.py [--run-id reviews-v2-...] [--max-reviews 1500] [--dry-run]
  (B) python deploy/select_unscored.py --input-key <JSONL 파일 키> [--dry-run]
마지막 줄에 결과 JSON 한 줄을 출력한다.
  (A) {"run_id", "silver_total", "scored", "unscored_total", "selected", "remaining", "review_dates", "output_key"}  (selected 가 0 이면 output_key 는 null)
  (B) {"input": N, "duplicate": D, "scored": M, "unscored": K, "output_key": "..." 또는 null}
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
    try:
        text = s3.get_object(Bucket=bucket, Key=input_key)['Body'].read().decode('utf-8-sig')
    except Exception as e:   # 입력 파일이 없으면 트레이스백 대신 알기 쉬운 메시지와 0 이 아닌 종료 코드로 끝낸다
        code = getattr(e, 'response', {}).get('Error', {}).get('Code') if hasattr(e, 'response') else None
        if code in ('NoSuchKey', '404'):
            raise SystemExit(f'입력 파일이 없습니다: s3://{bucket}/{input_key}')
        raise
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


# ============================================================== (A) Silver 실행 출력에서 고르기
RUN_ID_RE = re.compile(r'[A-Za-z0-9_-]{1,100}')
NAME_RE = re.compile(r'[A-Za-z0-9_]+')


def _get_json(s3, bucket, key, what):
    """S3 JSON 객체를 읽는다. 없으면 트레이스백 대신 알기 쉬운 메시지로 종료한다."""
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=key)['Body'].read().decode('utf-8-sig'))
    except Exception as e:
        code = getattr(e, 'response', {}).get('Error', {}).get('Code') if hasattr(e, 'response') else None
        if code in ('NoSuchKey', '404'):
            raise SystemExit(f'{what} 파일이 없습니다: s3://{bucket}/{key}')
        raise


def resolve_run_id(s3, silver_root_uri, run_id=None):
    """읽을 Silver 실행 ID 를 정한다. 반환: (run_id, 메모 dict).

    run_id 를 주지 않으면 <root>current.json 의 run_id 를 쓴다. current.json 은 Spark 가 가장 최근 실행을 가리키는 내부 참조이므로
    status 가 PASS 가 아니면 중단한다. run_id 를 직접 주면 <root>completed/<run_id>.json(완료 기록)의 status 가 PASS 인지 확인한다.
    """
    bucket, root = split_s3(silver_root_uri)
    root = root.rstrip('/') + '/'
    if run_id:
        if not RUN_ID_RE.fullmatch(run_id):
            raise SystemExit(f'run_id 형식 오류: {run_id!r}')
        info = _get_json(s3, bucket, f'{root}completed/{run_id}.json', f'실행 {run_id} 의 완료 기록')
    else:
        info = _get_json(s3, bucket, f'{root}current.json', 'Silver 리뷰 current.json')
        run_id = info.get('run_id')
        if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
            raise SystemExit('current.json 에 올바른 run_id 가 없습니다')
    if info.get('status') != 'PASS':
        raise SystemExit(f"Silver 실행 {run_id} 의 status 가 PASS 가 아닙니다: {info.get('status')!r}. 읽지 않습니다")
    return run_id, {'status': info.get('status'), 'coverage_status': info.get('coverage_status'),
                    'silver_reviews': (info.get('output_counts') or {}).get('silver_reviews')}


def _check_names(database, *tables):
    for n in (database,) + tables:
        if not NAME_RE.fullmatch(n or ''):
            raise ValueError(f'데이터베이스·테이블 이름 형식 오류: {n!r}')


def silver_unscored_query(database, silver_table, log_table, run_id, model_version_no, limit=1000000):
    """그 실행의 Silver 후기 중 점수 로그(현재 모델 번호)에 없는 후기를 고르는 SQL.

    - silver_table 은 run_id 파티션 프로젝션(injected)이라 WHERE s.run_id = '...' 가 반드시 필요하다.
    - 점수 로그와 review_id 와 작성일(review_date)이 같고 model_version_no 가 현재 번호인 행이 없을 때만 남긴다(= 아직 점수 없음).
    - 점수화에 필요한 열만 가져온다: review_id, text, review_date_kst(문자열 YYYY-MM-DD), created_at_kst.
    """
    _check_names(database, silver_table, log_table)
    if not RUN_ID_RE.fullmatch(run_id or ''):
        raise ValueError(f'run_id 형식 오류: {run_id!r}')
    if not isinstance(model_version_no, str) or not VERSION_NO_RE.fullmatch(model_version_no):
        raise ValueError(f'model_version_no 는 "x.y" 형식(예: 1.0)이어야 합니다: {model_version_no!r}')
    if not isinstance(limit, int) or not 1 <= limit <= 10000000:
        raise ValueError('limit 범위 오류')
    return (
        "SELECT s.review_id, s.text, CAST(s.review_date_kst AS varchar) AS review_date_kst, s.created_at_kst "
        f"FROM {database}.{silver_table} s "
        f"LEFT JOIN {database}.{log_table} l "
        f"ON l.review_id = s.review_id AND l.review_date = s.review_date_kst AND l.model_version_no = DECIMAL '{model_version_no}' "
        f"WHERE s.run_id = '{run_id}' AND l.review_id IS NULL AND s.review_id IS NOT NULL AND s.text IS NOT NULL AND trim(s.text) <> '' "
        f"ORDER BY s.review_date_kst, s.review_id LIMIT {limit}")


def silver_count_query(database, silver_table, run_id):
    _check_names(database, silver_table)
    if not RUN_ID_RE.fullmatch(run_id or ''):
        raise ValueError(f'run_id 형식 오류: {run_id!r}')
    return f"SELECT count(*) AS total FROM {database}.{silver_table} WHERE run_id = '{run_id}'"


def run_athena_rows(athena, workgroup, sql, poll=3, timeout=900):
    """Athena 쿼리를 실행하고 결과 행(헤더 제외)을 열 값 목록의 목록으로 돌려준다. 빈 값(NULL)은 None."""
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
    rows, first = [], True
    for page in athena.get_paginator('get_query_results').paginate(QueryExecutionId=qid):
        for r in page['ResultSet']['Rows']:
            if first:   # 첫 행은 헤더
                first = False
                continue
            rows.append([c.get('VarCharValue') for c in r['Data']])
    return rows


def select_unscored_from_silver(s3, athena, sm_cfg, at_cfg, model_version_no, run_id=None, max_reviews=1500, dry_run=False, now=None):
    """(A) Silver 실행 출력에서 점수 없는 후기를 골라 최대 max_reviews 건을 새 입력 파일로 쓴다. 결과 dict 를 돌려준다."""
    for k in ('silver_reviews_runs_table', 'silver_reviews_root', 'log_table', 'database', 'workgroup'):
        if not at_cfg.get(k):
            raise SystemExit(f'athena 설정(SSM)에 {k} 가 없습니다. athena-review-score 스택을 apply 했는지 확인하세요')
    if not isinstance(max_reviews, int) or not 1 <= max_reviews <= 20000:
        raise SystemExit('--max-reviews 는 1~20000 이어야 합니다')
    run_id, memo = resolve_run_id(s3, at_cfg['silver_reviews_root'], run_id)
    wg = at_cfg['workgroup']
    total_rows = run_athena_rows(athena, wg, silver_count_query(at_cfg['database'], at_cfg['silver_reviews_runs_table'], run_id))
    silver_total = int(total_rows[0][0]) if total_rows and total_rows[0][0] is not None else 0
    rows = run_athena_rows(athena, wg, silver_unscored_query(at_cfg['database'], at_cfg['silver_reviews_runs_table'], at_cfg['log_table'],
                                                             run_id, model_version_no))
    seen, picked = set(), []
    for rid, text, day, kst in rows:   # 순서는 SQL 의 ORDER BY(작성일, review_id). 같은 review_id 가 또 나오면 첫 줄만
        if rid in seen:
            continue
        seen.add(rid)
        picked.append((rid, text, day, kst))
    selected = picked[:max_reviews]
    result = {'run_id': run_id, 'silver_total': silver_total, 'scored': silver_total - len(picked), 'unscored_total': len(picked),
              'selected': len(selected), 'remaining': len(picked) - len(selected),
              'review_dates': sorted({d for _, _, d, _ in selected if d}), 'output_key': None, 'silver_status': memo}
    if not selected:
        return result
    now = now or datetime.now(timezone.utc)
    key = output_key(sm_cfg['unscored_prefix'], now.strftime('%Y-%m-%d'), now.strftime('%Y%m%dT%H%M%SZ'))
    result['output_key'] = key
    if not dry_run:
        body = ''.join(json.dumps({'review_id': rid, 'text': text, 'review_date_kst': day, 'created_at_kst': kst},
                                  ensure_ascii=False) + '\n' for rid, text, day, kst in selected).encode('utf-8')
        s3.put_object(Bucket=sm_cfg['bucket'], Key=key, Body=body)
    return result


def load_configs(ssm, ssm_sagemaker=SSM_SAGEMAKER, ssm_athena=SSM_ATHENA):
    sm = json.loads(ssm.get_parameter(Name=ssm_sagemaker)['Parameter']['Value'])
    at = json.loads(ssm.get_parameter(Name=ssm_athena)['Parameter']['Value'])
    return sm, at


def main():
    import boto3
    ap = argparse.ArgumentParser(description='아직 점수가 없는 후기만 골라 새 입력 파일로 쓴다')
    ap.add_argument('--input-key', default=None, help='(B 시험용) 버킷 안의 JSONL 후기 파일 키. 없으면 (A) Silver 실행 출력에서 고른다')
    ap.add_argument('--run-id', default=None, help='(A) 읽을 Silver 실행 ID. 기본은 current.json 의 run_id')
    ap.add_argument('--max-reviews', type=int, default=1500, help='(A) 한 번에 점수화할 최대 후기 수(Job 한 번의 한계 약 2,200건 안쪽)')
    ap.add_argument('--date', default=None, help='(B) 출력 폴더 날짜(YYYY-MM-DD). 기본은 입력 키의 year=/month=/day=')
    ap.add_argument('--model-version-no', default=None, help='모델 번호 "x.y"(예: 1.0). 기본은 SSM 설정의 model_version_no')
    ap.add_argument('--region', default='ap-northeast-1')
    ap.add_argument('--dry-run', action='store_true', help='개수만 세고 파일은 쓰지 않는다')
    a = ap.parse_args()
    ssm = boto3.client('ssm', region_name=a.region)
    sm_cfg, at_cfg = load_configs(ssm)
    no = a.model_version_no if a.model_version_no is not None else sm_cfg.get('model_version_no')
    if no is None:   # SSM 설정에는 번호가 없다. 현재 릴리스 묶음(manifest)의 model_version_no 를 쓴다(run_processing_job 과 같은 값)
        import run_processing_job as rp
        no = rp.load_release(boto3.client('s3', region_name=a.region), sm_cfg, sm_cfg['release'], rp.registry_uri(sm_cfg, None))['model_version_no']
    s3, athena = boto3.client('s3', region_name=a.region), boto3.client('athena', region_name=a.region)
    if a.input_key:
        res = select_unscored(s3, athena, sm_cfg['bucket'], a.input_key, sm_cfg['unscored_prefix'], at_cfg, no, a.date, a.dry_run)
        print(f"입력 {res['input']}건(입력 안 중복 {res['duplicate']}건), 이미 점수 있음 {res['scored']}건, 점수 필요 {res['unscored']}건"
              + ('  → 남은 후기가 없어 Job 을 띄우지 않아도 됩니다' if not res['unscored'] else f"  → {res['output_key']}"))
    else:
        res = select_unscored_from_silver(s3, athena, sm_cfg, at_cfg, no, a.run_id, a.max_reviews, a.dry_run)
        print(f"Silver 실행 {res['run_id']}: 전체 {res['silver_total']}건, 이미 점수 있음 {res['scored']}건, 점수 필요 {res['unscored_total']}건 → "
              f"이번에 {res['selected']}건 선택, 남음 {res['remaining']}건"
              + ('  → 남은 후기가 없어 Job 을 띄우지 않아도 됩니다' if not res['selected'] else f"  → {res['output_key']}"))
        if res['selected']:
            print(f"Job 이 끝나면 작성일 {', '.join(res['review_dates'])} 에 대해 merge.sql → merge_log.sql 을 실행하세요")
    print(json.dumps(res, ensure_ascii=False))


if __name__ == '__main__':
    main()
