"""모델 버전 하나를 S3에 올린다: 가중치 + 릴리스 묶음(manifest·실행 코드 사본) + 패치노트. 합친 모델만 올리며 어댑터·데이터는 올리지 않는다.
설계: release_bundle.py 머리말. manifest 하나 = 한 버전 세트이고, 점수화 Job(run_processing_job.py --release <버전>)은 manifest 만 보고 돈다.

실행 (review-analysis 폴더에서. 먼저 --dry-run 으로 계획을 확인한다)
  새 버전       python deploy/upload_model.py --dir private/merged/<버전> --uri s3://<버킷>/review-score/model/<버전>/
                    --registry-uri s3://<버킷>/review-score/model-registry/releases/ --image-uri <점수화 컨테이너 이미지> [--dry-run]
  이미 올린 가중치  위 명령에 --weights-already-uploaded  (가중치는 다시 올리지 않고 로컬 파일과 S3 크기를 대조한 뒤 묶음만 만든다.
                    묶음 방식 이전에 올린 2.4b_score_s2c 처럼 manifest 가 없는 버전을 등록할 때 쓴다)
  되돌리기       패치노트에 based_on: <원래 버전> 을 쓴 새 버전이면 --dir/--uri/--image-uri 없이
                    python deploy/upload_model.py --model-version <새 버전> --registry-uri ...  (원래 버전 manifest 의 가중치·코드·이미지를 그대로 가리킨다)

순서와 멈추는 조건 (하나라도 걸리면 그 뒤는 하지 않는다)
  1. 패치노트 검사 통과 + releases/<버전>.yaml 있음
  2. runtime-requirements.txt 의 모든 줄이 == 로 고정돼 있음
  3. 이 버전의 manifest 가 S3 에 아직 없음 (있으면 덮어쓰지 않는다. 고칠 일이 있으면 번호를 올린 새 버전으로)
  4. 새 가중치면 대상 폴더가 비어 있음 (기존 가중치를 덮어쓰지 않는다)
  5. 가중치 업로드(크기 확인) → 실행 코드 사본 업로드 → manifest 업로드(맨 마지막) → 패치노트 JSON·index.json 업로드
  중간에 실패하면 manifest 가 없으므로 그 버전은 "없는 버전"으로 남는다. 원인을 고친 뒤 다시 실행하면 된다
  (새 가중치 업로드 중 실패했다면 남은 파일 때문에 4번에서 멈추니, 그때는 --weights-already-uploaded 로 이어서 등록한다).
버킷 이름·계정 ID 는 코드·문서에 쓰지 않는다(공개 저장소). 경로는 인자로만 받는다."""
import argparse
import sys
from pathlib import Path

import release_bundle as rb
import release_notes


def check_release(model_version):
    """패치노트 검사. 통과하면 (전체 문서)를 돌려주고, 아니면 이유를 보여주고 멈춘다."""
    errs, docs = release_notes.load_all(release_notes.RELEASES)
    if errs:
        print('\n'.join(errs))
        sys.exit(f'패치노트 검사 실패 {len(errs)}건: 고친 뒤 다시 실행하세요 (python deploy/release_notes.py validate)')
    if model_version not in docs:
        sys.exit(f'releases/{model_version}.yaml 이 없습니다. 패치노트를 먼저 쓰세요 (양식: releases/_template.yaml)')
    d = docs[model_version]
    base = f', 되돌림: {d["based_on"]} 기준' if d.get('based_on') else ''
    print(f'패치노트 확인: {model_version} (번호 {d["model_version_no"]:.1f}, {d["change_type"]}{base}) - {d["summary"]}')
    return docs


def published_docs(s3, docs, registry_uri, current):
    """S3 에 올릴 패치노트: 이번 버전 + 이미 묶음(manifest)이 있는 버전만. 아직 모델을 올리지 않은 버전의 패치노트가 먼저 공개되지 않게 한다."""
    return {v: d for v, d in docs.items() if v == current or rb.read_manifest(s3, registry_uri, v) is not None}


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', help='합친 모델 폴더 (되돌림 버전이면 필요 없음)')
    ap.add_argument('--uri', help='가중치를 둘 S3 폴더 s3://<버킷>/review-score/model/<버전>/ (되돌림 버전이면 필요 없음)')
    ap.add_argument('--model-version', help='모델 버전. 기본은 --dir 의 마지막 폴더 이름')
    ap.add_argument('--registry-uri', '--releases-uri', dest='registry_uri', required=True,
                    help='s3://<버킷>/review-score/model-registry/releases/ (패치노트와 릴리스 묶음을 두는 곳)')
    ap.add_argument('--image-uri', help='점수화 컨테이너 이미지 (새 버전이면 필수. 지금 값은 SSM 설정의 image_uri)')
    ap.add_argument('--bs', type=int, default=rb.DEFAULT_INFERENCE['bs'], help='추론 배치 크기 (manifest inference.bs). 바꾸면 결과가 달라질 수 있다')
    ap.add_argument('--weights-already-uploaded', action='store_true',
                    help='가중치는 이미 --uri 에 있다. 다시 올리지 않고 로컬 --dir 파일과 S3 크기를 대조한 뒤 묶음만 만든다')
    ap.add_argument('--train-commit', help='(선택) 학습 코드 커밋')
    ap.add_argument('--train-data', help='(선택) 학습 데이터 이름·버전만 (예: aihub_work v3). 원문·경로 안의 내용은 쓰지 않는다')
    ap.add_argument('--allow-dirty', action='store_true', help='묶음에 들어가는 실행 코드에 커밋 안 된 변경이 있어도 진행 (manifest 에 git_dirty=true 로 남는다)')
    ap.add_argument('--dry-run', action='store_true', help='검사와 계획만 출력하고 아무것도 올리지 않는다')
    a = ap.parse_args(argv)
    if not a.model_version:
        if not a.dir:
            ap.error('--model-version 또는 --dir 가 필요합니다')
        a.model_version = Path(a.dir).resolve().name
    return a


def plan_new(a, note):
    """새 가중치(또는 이미 올린 가중치) 버전의 계획. (가중치 목록, 가중치 uri, 이미지, 추론 설정, 원래 버전 None)"""
    missing = [k for k in ('dir', 'uri', 'image_uri') if not getattr(a, k)]
    if missing:
        sys.exit(f'새 버전에는 {", ".join("--" + m.replace("_", "-") for m in missing)} 가 필요합니다')
    rb.split_uri(a.uri)
    if not a.uri.rstrip('/').endswith('/' + a.model_version):
        sys.exit(f'--uri 마지막 폴더는 모델 버전({a.model_version})이어야 합니다: {a.uri}')
    print(f'가중치 {a.dir} → {a.uri}')
    files = rb.local_weights(a.dir)
    print(f'  {len(files)}개 파일, {sum(f["size"] for f in files) / 1e9:.2f}GB')
    return files, a.uri, a.image_uri, {'bs': a.bs}


def plan_based_on(a, note, base_m):
    """되돌림 버전의 계획: 원래 버전 manifest 의 가중치·이미지·추론 설정을 그대로 쓴다."""
    for k in ('dir', 'uri', 'image_uri'):
        if getattr(a, k):
            sys.exit(f'되돌림 버전(based_on: {note["based_on"]})에는 --{k.replace("_", "-")} 를 주지 않습니다. 원래 버전의 값을 그대로 씁니다')
    print(f'되돌림: {note["based_on"]} 의 가중치·코드·라이브러리·이미지·추론 설정을 그대로 가리킵니다 (가중치 업로드 없음)')
    return base_m['weights']['files'], base_m['weights']['uri'], base_m['runtime']['image_uri'], base_m['inference']


def main(argv=None, s3=None):
    a = parse_args(argv)
    docs = check_release(a.model_version)
    note = docs[a.model_version]
    reg_bucket, reg_prefix = rb.split_uri(a.registry_uri)
    bundle = f'{reg_prefix}{a.model_version}/'
    if s3 is None:
        import boto3
        s3 = boto3.client('s3')

    # 3. 이미 묶음이 있으면 덮어쓰지 않는다 (dry-run 에서도 확인한다. 읽기만 함)
    if rb.read_manifest(s3, a.registry_uri, a.model_version) is not None:
        sys.exit(f'{a.model_version} 의 manifest 가 이미 있습니다. 배포된 버전은 고치지 않고 번호를 올린 새 버전으로 만드세요')

    base_m = None
    if note.get('based_on'):
        base_m = rb.read_manifest(s3, a.registry_uri, note['based_on'])
        if base_m is None:
            sys.exit(f'원래 버전 {note["based_on"]} 의 manifest 가 S3 에 없습니다. 묶음이 있는 버전으로만 되돌릴 수 있습니다')
        files, w_uri, image, inference = plan_based_on(a, note, base_m)
        pins = base_m['runtime']['pip']
        git = {k: base_m['code'].get(k) for k in ('git_commit', 'git_dirty')}
        code_src = [(f'{base_m["model_version"]}/code/{f["name"]}', f) for f in base_m['code']['files']]
    else:
        files, w_uri, image, inference = plan_new(a, note)
        pins = rb.read_pins()
        git = rb.git_info()
        if git['git_dirty'] and not a.allow_dirty:
            sys.exit(f'{", ".join(rb.CODE_FILES)} 에 커밋 안 된 변경이 있습니다. 커밋한 뒤 올리거나, 시험이면 --allow-dirty 를 붙이세요')
        code_src = [(rb.DEPLOY / src, {'name': rb.CODE_NAMES.get(src, src), 'sha256': rb.sha256_file(rb.DEPLOY / src)})
                    for src in rb.CODE_FILES]
        # 4. 새 가중치는 빈 폴더에만 올린다. 이미 올린 가중치면 로컬 파일과 S3 크기를 대조한다
        w_bucket, w_prefix = rb.split_uri(w_uri)
        have = rb.list_prefix(s3, w_bucket, w_prefix)
        if a.weights_already_uploaded:
            diff = [f['name'] for f in files if have.get(f['name']) != f['size']]
            if diff:
                sys.exit(f'S3 가중치가 로컬과 다릅니다(없거나 크기 다름): {diff}')
            print('  S3 가중치가 로컬 파일과 같습니다 (이름·크기). 다시 올리지 않습니다')
        elif have:
            sys.exit(f'{w_uri} 에 이미 파일이 {len(have)}개 있습니다. 덮어쓰지 않습니다 '
                     '(같은 가중치를 등록만 하려면 --weights-already-uploaded)')

    training = {'code_commit': a.train_commit, 'data': a.train_data} if (a.train_commit or a.train_data) else None
    if base_m is not None:
        training = base_m.get('training')
    manifest = rb.build_manifest(note, w_uri, files, [f for _, f in code_src], pins, image, inference, git, training,
                                 based_on=note.get('based_on'), created_by=rb.git_user())
    print(f'묶음 → s3://{reg_bucket}/{bundle}')
    print(f'  manifest: 번호 {manifest["model_version_no"]}, 이미지 {image}, 라이브러리 {", ".join(pins)}, 추론 {inference}')
    print(f'  코드: {", ".join(f["name"] for _, f in code_src)} (커밋 {git.get("git_commit")}, 변경 있음 {git.get("git_dirty")})')
    if a.dry_run:
        release_notes.upload(published_docs(s3, docs, a.registry_uri, a.model_version), a.registry_uri, dry_run=True, s3=s3)
        print('(dry-run) 아무것도 올리지 않았습니다')
        return manifest

    from boto3.s3.transfer import TransferConfig
    cfg = TransferConfig(multipart_threshold=64 * 1024 * 1024, multipart_chunksize=64 * 1024 * 1024, max_concurrency=8)
    if base_m is None and not a.weights_already_uploaded:
        w_bucket, w_prefix = rb.split_uri(w_uri)
        for f in files:
            p = Path(a.dir) / f['name']
            s3.upload_file(str(p), w_bucket, w_prefix + f['name'], Config=cfg)
            size = s3.head_object(Bucket=w_bucket, Key=w_prefix + f['name'])['ContentLength']
            assert size == f['size'], f'{f["name"]} 크기 불일치 {size}'
            print('  가중치 업로드 완료', f['name'], flush=True)
    for src, f in code_src:
        key = f'{bundle}code/{f["name"]}'
        if base_m is not None:   # 되돌림: 원래 버전 묶음의 코드 사본을 S3 안에서 복사
            s3.copy_object(Bucket=reg_bucket, Key=key, CopySource={'Bucket': reg_bucket, 'Key': reg_prefix + src})
        else:
            s3.upload_file(str(src), reg_bucket, key)
        print('  코드 업로드 완료', f['name'], flush=True)
    rb.put_json(s3, reg_bucket, bundle + rb.MANIFEST, manifest)   # 맨 마지막: 이 파일이 생겨야 "있는 버전"
    print('  manifest 업로드 완료')
    release_notes.upload(published_docs(s3, docs, a.registry_uri, a.model_version), a.registry_uri, dry_run=False, s3=s3)
    print(f'완료. 실행 버전을 바꾸려면 SSM 설정의 release 를 {a.model_version} 으로 바꾼다(sagemaker 스택). 바꾸기 전 확인: '
          f'python deploy/run_processing_job.py --release {a.model_version} --input-key <키> --dry-run')
    return manifest


if __name__ == '__main__':
    main()
