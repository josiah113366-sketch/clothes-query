"""모델 릴리스 묶음(manifest) 만들기·읽기. upload_model.py(만들기)와 run_processing_job.py(읽기)가 같이 쓴다.

원칙: manifest 하나 = 한 버전 세트. 점수화 Job 은 버전 이름 하나만 받고, 가중치·실행 코드·라이브러리·이미지·번호를 전부 manifest 에서 가져간다.

S3 구조 (버킷 이름은 코드에 두지 않는다. 위치는 --registry-uri / SSM 으로만 받는다)
  review-score/model/<모델 버전>/                      가중치 (manifest 가 경로·파일별 크기·sha256 으로 가리킴. 복사하지 않음)
  review-score/model-registry/releases/
    index.json, <모델 버전>.json                        패치노트 (release_notes.py)
    <모델 버전>/manifest.json                           이 파일이 있어야 "있는 버전"이다. 업로드 맨 마지막에 쓴다
    <모델 버전>/code/score_batch.py, requirements.txt   그 버전에서 쓴 실행 코드와 고정 라이브러리 목록 사본

규칙
  - 한 번 만든 묶음(manifest.json)은 덮어쓰지 않는다. 고칠 일이 있으면 번호를 올린 새 버전을 만든다.
  - 되돌리기(roll-forward): 패치노트에 based_on: <원래 버전> 을 쓰고 새 번호로 올린다. 가중치를 다시 올리지 않고
    원래 버전의 가중치·코드·라이브러리·이미지·추론 설정을 그대로 가리키는 manifest 만 새로 만든다.
  - 학습 정보는 이름·커밋만 적는다. 후기 원문, AI Hub 원본 내용, 데이터 파일 경로 안의 내용은 넣지 않는다.
"""
import datetime
import hashlib
import json
import re
import subprocess
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent
# 묶음에 복사하는 실행 코드. 점수화 Job 이 쓰는 파일이 늘면 여기에 추가한다(컨테이너의 /opt/ml/processing/code/ 에 그대로 놓인다)
CODE_FILES = ['score_batch.py', 'runtime-requirements.txt']
CODE_NAMES = {'runtime-requirements.txt': 'requirements.txt'}   # 묶음 안에서 쓰는 이름 (실행 명령이 requirements.txt 로 읽는다)
MANIFEST = 'manifest.json'
SCHEMA = 1   # manifest 양식 번호. 필드를 바꾸면 올리고 run_processing_job.py 읽기 코드와 맞춘다
# 결과에 영향을 주는 추론 설정의 기본값. score_batch.py 인자와 이름을 맞춘다(bs = --bs). 바꾸면 새 버전으로 올린다
DEFAULT_INFERENCE = {'bs': 16}
PIN_RE = re.compile(r'^[A-Za-z0-9_.\-\[\]]+==[A-Za-z0-9_.+\-]+$')   # "이름==버전" 만 허용 (>=, 범위, 미지정 금지)


def split_uri(uri):
    assert uri.startswith('s3://') and uri.endswith('/'), f's3://<버킷>/<경로>/ 형식이어야 합니다: {uri}'
    bucket, prefix = uri[5:].split('/', 1)
    return bucket, prefix


def sha256_file(path, chunk=8 * 1024 * 1024):
    """큰 가중치 파일(수 GB)도 메모리에 다 올리지 않고 8MB 씩 읽어 해시를 계산한다."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(chunk), b''):
            h.update(b)
    return h.hexdigest()


def read_pins(path=None):
    """runtime-requirements.txt 를 읽어 고정된 라이브러리 목록을 돌려준다. 버전을 == 로 고정하지 않은 줄이 있으면 멈춘다."""
    path = Path(path or DEPLOY / 'runtime-requirements.txt')
    pins, bad = [], []
    for line in path.read_text(encoding='utf-8').splitlines():
        s = line.split('#', 1)[0].strip()
        if not s:
            continue
        (pins if PIN_RE.fullmatch(s) else bad).append(s)
    if bad:
        raise SystemExit(f'{path.name}: 버전을 == 로 고정하지 않은 줄이 있습니다: {bad}')
    if not pins:
        raise SystemExit(f'{path.name}: 라이브러리 목록이 비어 있습니다')
    return pins


def git_info():
    """지금 체크아웃의 커밋과, 묶음에 들어가는 실행 코드에 커밋되지 않은 변경이 있는지. git 이 없으면 None."""
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=DEPLOY, capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(['git', 'status', '--porcelain', '--', *CODE_FILES], cwd=DEPLOY,
                               capture_output=True, text=True, check=True).stdout.strip() != ''
        return {'git_commit': commit, 'git_dirty': dirty}
    except (OSError, subprocess.CalledProcessError):
        return {'git_commit': None, 'git_dirty': None}


def git_user():
    try:
        return subprocess.run(['git', 'config', 'user.name'], cwd=DEPLOY, capture_output=True, text=True, check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def local_weights(folder):
    """합친 모델 폴더의 파일 목록(이름·크기·sha256). 하위 폴더는 쓰지 않는다(upload_model.py 와 같은 기준)."""
    files = [p for p in sorted(Path(folder).iterdir()) if p.is_file()]
    if not files:
        raise SystemExit(f'{folder} 에 파일이 없습니다')
    out = []
    for p in files:
        print(f'  해시 계산 {p.name} ({p.stat().st_size / 1e6:.1f}MB)', flush=True)
        out.append({'name': p.name, 'size': p.stat().st_size, 'sha256': sha256_file(p)})
    return out


def list_prefix(s3, bucket, prefix):
    """prefix 바로 아래 객체 {이름: 크기}. 하위 폴더 안의 객체는 이름에 / 가 들어가 그대로 돌려준다."""
    out, token = {}, None
    while True:
        kw = dict(Bucket=bucket, Prefix=prefix)
        if token:
            kw['ContinuationToken'] = token
        r = s3.list_objects_v2(**kw)
        for o in r.get('Contents', []):
            out[o['Key'][len(prefix):]] = o['Size']
        if not r.get('IsTruncated'):
            return out
        token = r['NextContinuationToken']


def read_manifest(s3, registry_uri, version):
    """버전의 manifest 를 읽는다. 없으면 None (= 없는 버전)."""
    bucket, prefix = split_uri(registry_uri)
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=f'{prefix}{version}/{MANIFEST}')['Body'].read())
    except Exception as e:  # noqa: BLE001  없는 키만 None 으로 보고 권한 오류 등은 그대로 올린다
        code = getattr(e, 'response', {}).get('Error', {}).get('Code')
        if code in ('NoSuchKey', '404') or e.__class__.__name__ == 'NoSuchKey':
            return None
        raise


def build_manifest(note, weights_uri, weights_files, code_files, pins, image_uri, inference, git, training,
                   based_on=None, created_by=None):
    """manifest 문서를 만든다 (S3 호출 없음). note 는 release_notes.load_all 이 돌려준 패치노트 한 개."""
    return {
        'schema': SCHEMA,
        'model_version': note['model_version'],
        'model_version_no': f'{note["model_version_no"]:.1f}',   # 점수 테이블·SSM 과 같은 "x.y" 문자열
        'based_on': based_on,
        'weights': {'uri': weights_uri, 'files': weights_files},
        'code': {'files': code_files, **git},
        'runtime': {'image_uri': image_uri, 'pip': pins},
        'inference': inference,
        'training': training,
        'created_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'created_by': created_by,
    }


def check_manifest(m, version=None):
    """run_processing_job.py 가 실행 전에 부르는 형식 검사. 문제 목록을 돌려준다."""
    errs = []
    for k in ('model_version', 'model_version_no', 'weights', 'code', 'runtime', 'inference'):
        if k not in m:
            errs.append(f'manifest 에 {k} 가 없습니다')
    if errs:
        return errs
    if m.get('schema') != SCHEMA:
        errs.append(f'manifest schema {m.get("schema")} 를 이 스크립트(schema {SCHEMA})가 읽을 수 없습니다')
    if version and m['model_version'] != version:
        errs.append(f'manifest 의 model_version({m["model_version"]}) 이 요청한 버전({version})과 다릅니다')
    if not re.fullmatch(r'\d{1,2}\.\d', str(m['model_version_no'])):
        errs.append(f'model_version_no 형식 오류: {m["model_version_no"]!r}')
    if not m['weights'].get('files'):
        errs.append('weights.files 가 비어 있습니다')
    names = {f['name'] for f in m['code'].get('files', [])}
    if not {'score_batch.py', 'requirements.txt'} <= names:
        errs.append(f'code.files 에 score_batch.py, requirements.txt 가 모두 있어야 합니다: {sorted(names)}')
    if not m['runtime'].get('image_uri'):
        errs.append('runtime.image_uri 가 비어 있습니다')
    return errs


def verify_weights(s3, m):
    """S3 가중치 폴더가 manifest 와 같은지(파일 이름·크기) 확인한다. 해시까지 받아 보는 것은 비용이 커서 하지 않는다."""
    bucket, prefix = split_uri(m['weights']['uri'])
    have = list_prefix(s3, bucket, prefix)
    errs = []
    for f in m['weights']['files']:
        if f['name'] not in have:
            errs.append(f'가중치 파일 없음: {f["name"]}')
        elif have[f['name']] != f['size']:
            errs.append(f'가중치 크기 다름: {f["name"]} (manifest {f["size"]}, S3 {have[f["name"]]})')
    return errs


def put_json(s3, bucket, key, doc):
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(doc, ensure_ascii=False, indent=2).encode('utf-8'),
                  ContentType='application/json; charset=utf-8')
