"""모델 패치노트(releases/*.yaml)를 검사하고, 대시보드가 읽는 JSON으로 바꾸고, S3에 올린다.
설계: 버전마다 releases/<model_version>.yaml 한 개를 git에 쓰고(A), 모델을 올릴 때 이 스크립트로 검증·변환·업로드(B)한다.

실행 (review-analysis 폴더에서)
  python deploy/release_notes.py validate                          # 전체 검사 (업로드 전·PR 전에 실행)
  python deploy/release_notes.py to-json --out <폴더>               # JSON 으로 변환만 (개발용 복사본 만들기)
  python deploy/release_notes.py upload --uri s3://<버킷>/review-score/model-registry/releases/ [--dry-run]

규칙 (releases/README.md 참고)
  - 파일 이름 = model_version. 파일 이름이 _ 로 시작하면(예: _template.yaml) 검사·업로드에서 뺀다.
  - 이미 올라간 버전은 notes(정정·추가)만 덧붙일 수 있다. 다른 필드가 바뀌면 거부한다(버전을 올려서 새 파일로 쓴다).
  - 후기 원문·AI Hub 원본 내용을 쓰지 않는다. 정해 둔 필드 밖의 키가 있으면 검사에서 막는다.
  - 버킷 이름을 코드에 넣지 않는다. --uri 로만 받는다.
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

import yaml

RELEASES = Path(__file__).resolve().parent.parent / 'releases'
# 패치노트 분류. 대시보드 화면(data.get_model_changelog)의 분류와 같게 둔다. 바꾸면 양쪽을 같이 고친다.
CATEGORIES = ['모델', '학습 데이터', '프롬프트·후처리', '속성 목록', '평가', '배포']
CHANGE_TYPES = ['최초', '메이저', '마이너']
TOP_KEYS = {'model_version', 'model_version_no', 'change_type', 'released_at', 'summary',
            'rescore_required', 'changes', 'evaluation', 'notes', 'based_on'}
# based_on: 되돌림(roll-forward) 버전만 쓴다. 원래 버전 이름이며, 새 번호로 원래 버전의 가중치·코드를 그대로 다시 배포한다
REQUIRED = TOP_KEYS - {'notes', 'based_on'}
EVAL_KEYS = {'eval_set', 'eval_n', 'f1', 'mae', 'qwk', 'source'}
SCHEMA = 1  # JSON 양식 번호. 필드를 바꾸면 올리고 대시보드 읽기 코드와 맞춘다.


def _text(v):
    return isinstance(v, str) and v.strip() != ''


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _date_str(v):
    """YAML 은 2026-10-14 를 날짜로 읽는다. 문자열이면 형식을 확인한다."""
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', v):
        datetime.date.fromisoformat(v)
        return v
    raise ValueError('YYYY-MM-DD 형식이어야 합니다')


def check_one(path, doc):
    """파일 하나의 문제 목록을 돌려준다 (비어 있으면 통과)."""
    errs = []
    if not isinstance(doc, dict):
        return ['최상위가 항목 모음(키: 값)이어야 합니다']
    for k in sorted(REQUIRED - doc.keys()):
        errs.append(f'필수 항목 없음: {k}')
    for k in sorted(doc.keys() - TOP_KEYS):
        errs.append(f'정해지지 않은 항목: {k} (후기 원문 같은 값을 넣지 마세요)')
    if 'model_version' in doc and doc['model_version'] != path.stem:
        errs.append(f'model_version({doc["model_version"]}) 이 파일 이름({path.stem})과 다릅니다')
    no = doc.get('model_version_no')
    if 'model_version_no' in doc and not (_num(no) and abs(no * 10 - round(no * 10)) < 1e-9 and no >= 0):
        errs.append('model_version_no 는 x.y 형식(소수 한 자리) 숫자여야 합니다')
    if 'change_type' in doc and doc['change_type'] not in CHANGE_TYPES:
        errs.append(f'change_type 은 {CHANGE_TYPES} 중 하나여야 합니다')
    if 'released_at' in doc:
        try:
            _date_str(doc['released_at'])
        except ValueError as e:
            errs.append(f'released_at: {e}')
    if 'summary' in doc and not _text(doc['summary']):
        errs.append('summary 가 비어 있습니다')
    if 'based_on' in doc and not (_text(doc['based_on']) and doc['based_on'] != doc.get('model_version')):
        errs.append('based_on 은 되돌릴 원래 버전 이름(자기 자신이 아닌 다른 버전)이어야 합니다')
    if 'rescore_required' in doc and not isinstance(doc['rescore_required'], bool):
        errs.append('rescore_required 는 true/false 여야 합니다')
    ch = doc.get('changes')
    if 'changes' in doc:
        if not isinstance(ch, list) or not ch:
            errs.append('changes 는 한 개 이상의 목록이어야 합니다')
        else:
            for i, c in enumerate(ch, 1):
                if not isinstance(c, dict) or set(c) != {'category', 'item', 'detail'}:
                    errs.append(f'changes[{i}] 는 category, item, detail 만 가져야 합니다')
                    continue
                if c['category'] not in CATEGORIES:
                    errs.append(f'changes[{i}].category 는 {CATEGORIES} 중 하나여야 합니다')
                for f in ('item', 'detail'):
                    if not _text(c[f]):
                        errs.append(f'changes[{i}].{f} 가 비어 있습니다')
    ev = doc.get('evaluation')
    if 'evaluation' in doc:
        if not isinstance(ev, dict) or set(ev) != EVAL_KEYS:
            errs.append(f'evaluation 은 {sorted(EVAL_KEYS)} 항목을 모두 가져야 합니다')
        else:
            if not _text(ev['eval_set']) or not _text(ev['source']):
                errs.append('evaluation.eval_set / source 가 비어 있습니다')
            if not (isinstance(ev['eval_n'], int) and not isinstance(ev['eval_n'], bool) and ev['eval_n'] > 0):
                errs.append('evaluation.eval_n 은 1 이상의 정수여야 합니다')
            for k, lo, hi in (('f1', 0, 1), ('mae', 0, 4), ('qwk', -1, 1)):
                if not (_num(ev[k]) and lo <= ev[k] <= hi):
                    errs.append(f'evaluation.{k} 는 {lo}~{hi} 사이 숫자여야 합니다')
    for i, n in enumerate(doc.get('notes') or [], 1):
        if not isinstance(n, dict) or set(n) != {'date', 'text'}:
            errs.append(f'notes[{i}] 는 date, text 만 가져야 합니다')
            continue
        try:
            _date_str(n['date'])
        except ValueError as e:
            errs.append(f'notes[{i}].date: {e}')
        if not _text(n['text']):
            errs.append(f'notes[{i}].text 가 비어 있습니다')
    return errs


def load_all(folder):
    """폴더의 패치노트를 읽어 (문제 목록, {model_version: 문서}) 를 돌려준다. 문서는 JSON 으로 바로 쓸 수 있게 정리돼 있다."""
    errs, docs = [], {}
    for p in sorted(Path(folder).glob('*.yaml')):
        if p.name.startswith('_'):
            continue
        try:
            doc = yaml.safe_load(p.read_text(encoding='utf-8'))
        except yaml.YAMLError as e:
            errs.append(f'{p.name}: YAML 을 읽을 수 없습니다 ({e})')
            continue
        e = [f'{p.name}: {m}' for m in check_one(p, doc)]
        errs += e
        if not e:
            doc = dict(doc)
            doc['released_at'] = _date_str(doc['released_at'])
            doc['notes'] = [{'date': _date_str(n['date']), 'text': n['text']} for n in (doc.get('notes') or [])]
            doc['model_version_no'] = round(float(doc['model_version_no']), 1)
            docs[doc['model_version']] = doc
    errs += check_chain(docs)
    return errs, docs


def check_chain(docs):
    """파일 사이의 규칙: 번호가 유일하고, 가장 낮은 번호만 '최초', 변경 유형이 번호 변화와 맞는다."""
    errs, seen = [], {}
    for v, d in docs.items():
        if d['model_version_no'] in seen:
            errs.append(f'{v}: model_version_no {d["model_version_no"]} 가 {seen[d["model_version_no"]]} 와 같습니다')
        seen[d['model_version_no']] = v
    for v, d in docs.items():
        b = d.get('based_on')
        if b is None:
            continue
        if b not in docs:
            errs.append(f'{v}: based_on 의 {b} 패치노트가 없습니다')
        elif docs[b]['model_version_no'] >= d['model_version_no']:
            errs.append(f'{v}: based_on({b}) 보다 번호가 높아야 합니다 (되돌림도 번호를 올린다. Gold 가 가장 큰 번호를 읽기 때문)')
        elif docs[b].get('based_on'):
            errs.append(f'{v}: based_on 은 실제 가중치가 있는 버전을 가리켜야 합니다({b} 도 되돌림 버전이니 {docs[b]["based_on"]} 을 쓰세요)')
    ordered = sorted(docs.values(), key=lambda d: d['model_version_no'])
    for i, d in enumerate(ordered):
        v = d['model_version']
        if i == 0:
            if d['change_type'] != '최초':
                errs.append(f'{v}: 가장 낮은 번호는 change_type 이 최초여야 합니다')
            continue
        prev = ordered[i - 1]
        if d['change_type'] == '최초':
            errs.append(f'{v}: 최초는 가장 낮은 번호 하나뿐입니다')
        elif d['change_type'] == '메이저' and int(d['model_version_no']) <= int(prev['model_version_no']):
            errs.append(f'{v}: 메이저인데 {prev["model_version"]} 보다 메이저 번호가 오르지 않았습니다')
        elif d['change_type'] == '마이너' and int(d['model_version_no']) != int(prev['model_version_no']):
            errs.append(f'{v}: 마이너인데 메이저 번호가 다릅니다 (메이저는 change_type 을 메이저로)')
    return errs


def to_json(doc):
    return json.dumps({'schema': SCHEMA, **doc}, ensure_ascii=False, indent=2, sort_keys=False)


def index_json(docs):
    rows = [{k: d.get(k) for k in ('model_version', 'model_version_no', 'change_type', 'released_at', 'summary', 'based_on')}
            for d in sorted(docs.values(), key=lambda d: d['model_version_no'], reverse=True)]
    return json.dumps({'schema': SCHEMA, 'versions': rows}, ensure_ascii=False, indent=2)


def same_but_notes(old, new):
    """올라가 있는 문서와 새 문서가 notes 만 다르게(덧붙여서) 같은지 본다."""
    o, n = dict(old), dict(new)
    on, nn = o.pop('notes', []), n.pop('notes', [])
    o.pop('schema', None)
    return o == n and nn[:len(on)] == on


def upload(docs, uri, dry_run, s3=None):
    assert uri.startswith('s3://') and uri.endswith('/'), '--uri 는 s3://<버킷>/<경로>/ 형식이어야 합니다'
    bucket, prefix = uri[5:].split('/', 1)
    if s3 is None and not dry_run:
        import boto3
        s3 = boto3.client('s3')
    plan = []
    for v, d in sorted(docs.items()):
        key = prefix + v + '.json'
        old = None
        if s3 is not None:
            try:
                old = json.loads(s3.get_object(Bucket=bucket, Key=key)['Body'].read())
            except Exception as e:  # noqa: BLE001  없는 키는 새 버전으로 보고, 그 밖의 오류는 그대로 올린다
                code = getattr(e, 'response', {}).get('Error', {}).get('Code')
                if code not in ('NoSuchKey', '404') and e.__class__.__name__ != 'NoSuchKey':
                    raise
        if old is None:
            plan.append((key, '새 버전'))
        elif old.get('notes') == d['notes'] and same_but_notes(old, d):
            plan.append((key, '변경 없음, 건너뜀'))
        elif same_but_notes(old, d):
            plan.append((key, 'notes 덧붙임'))
        else:
            sys.exit(f'{v}: 이미 올라간 내용과 notes 밖의 필드가 다릅니다. 배포된 버전은 고치지 않고 새 버전 파일로 쓰세요.')
    print(f'→ s3://{bucket}/{prefix}')
    for key, what in plan:
        print(f'  {key.rsplit("/", 1)[-1]}: {what}')
    if dry_run:
        print('(dry-run) 올리지 않았습니다')
        return plan
    for key, what in plan:
        if what != '변경 없음, 건너뜀':
            v = key.rsplit('/', 1)[-1][:-5]
            s3.put_object(Bucket=bucket, Key=key, Body=to_json(docs[v]).encode('utf-8'),
                          ContentType='application/json; charset=utf-8')
    s3.put_object(Bucket=bucket, Key=prefix + 'index.json', Body=index_json(docs).encode('utf-8'),
                  ContentType='application/json; charset=utf-8')
    print('업로드 완료 (index.json 갱신)')
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['validate', 'to-json', 'upload'])
    ap.add_argument('--dir', default=str(RELEASES))
    ap.add_argument('--out')
    ap.add_argument('--uri')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    errs, docs = load_all(a.dir)
    if errs:
        print('\n'.join(errs))
        sys.exit(f'검사 실패: {len(errs)}건')
    print(f'검사 통과: {len(docs)}개 버전 ({", ".join(sorted(docs))})')
    if a.cmd == 'to-json':
        out = Path(a.out or 'model_releases')
        out.mkdir(parents=True, exist_ok=True)
        for v, d in docs.items():
            (out / f'{v}.json').write_text(to_json(d), encoding='utf-8')
        (out / 'index.json').write_text(index_json(docs), encoding='utf-8')
        print(f'{out} 에 {len(docs)}개와 index.json 을 썼습니다')
    elif a.cmd == 'upload':
        assert a.uri, '--uri 가 필요합니다'
        upload(docs, a.uri, a.dry_run)


if __name__ == '__main__':
    main()
