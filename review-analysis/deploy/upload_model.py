"""합친 모델 폴더를 S3에 올린다 (멀티파트, 크기 검증 포함). 합친 모델만 올리며 어댑터·데이터는 올리지 않는다.
실행: python deploy/upload_model.py --dir private/merged/2.4b_score_s2c --uri s3://<버킷>/model/2.4b_score_s2c/ [--dry-run]"""
import argparse
import os
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--uri', required=True)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    assert a.uri.startswith('s3://') and a.uri.endswith('/')
    bucket, prefix = a.uri[5:].split('/', 1)
    files = [p for p in sorted(Path(a.dir).iterdir()) if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    print(f'{len(files)}개 파일, {total / 1e9:.2f}GB → s3://{bucket}/{prefix}')
    for p in files:
        print(f'  {p.name} {p.stat().st_size / 1e6:.1f}MB')
    if a.dry_run:
        return
    import boto3
    from boto3.s3.transfer import TransferConfig
    s3 = boto3.client('s3')
    cfg = TransferConfig(multipart_threshold=64 * 1024 * 1024, multipart_chunksize=64 * 1024 * 1024, max_concurrency=8)
    for p in files:
        s3.upload_file(str(p), bucket, prefix + p.name, Config=cfg)
        size = s3.head_object(Bucket=bucket, Key=prefix + p.name)['ContentLength']
        assert size == p.stat().st_size, f'{p.name} 크기 불일치 {size}'
        print('  업로드 완료', p.name, flush=True)
    print('모두 업로드·검증 완료')


if __name__ == '__main__':
    main()
