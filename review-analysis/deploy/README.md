# 후기 점수화 배포 (s2c, 합친 모델)

1. 로컬 검증: `python deploy/check_prompt.py` → `python deploy/score_batch.py --model-dir private/merged/2.4b_score_s2c --input <후기.csv> --output <점수.csv>`
2. 전용 S3와 SageMaker 실행 역할은 Terraform으로 만든다. Terraform 코드는 `infra/` 규칙에 따라 이 폴더가 아니라 따로 올린다(이 폴더에는 없음). 팀 계정에서는 `infra/stacks/sagemaker-review-score`가 역할·보안 그룹·SSM 설정(`/clothes-query/dev/sagemaker-review-score/config`)을 만든다
3. 모델 업로드: `python deploy/upload_model.py --dir private/merged/2.4b_score_s2c --uri s3://<버킷>/model/2.4b_score_s2c/` (`--dry-run`으로 목록 먼저 확인)
4. S3 입력으로 테스트: `python deploy/score_batch.py --model-dir ... --input s3://<버킷>/input/reviews_100.csv --output s3://<버킷>/output/out_100.csv`
5. 팀 S3 `review-score/model/2.4b_score_s2c/`·`review-score/code/`로 업로드 후, 수동 실행: `python deploy/run_processing_job.py --input-key <후기 파일 S3 키> --dry-run` 로 요청 확인 → `--wait` 로 실행. 결과는 `staging/review-score/year=/month=/day=/scores_<model_version>_<실행시각>.parquet`(Iceberg MERGE 입력, 실행마다 새 파일)(날짜는 실행일이 아니라 **후기 작성일(KST)** 이고, 후기 행의 `review_date_kst` 등에서 읽어 날짜별로 나눠 쓴다. 날짜 없는 후기는 `--date` 또는 입력 키의 year=/month=/day= 를 쓴다). 하루 1회 실행은 Airflow silver DAG 종료 후 Airflow가 같은 방식으로 한다(다음 단계).

출력 형식: 출력 경로가 `.parquet` 이면 Parquet(팀 Silver 형식, 열 `review_id,aspect,score,model_version,analyzed_at,review_date`, `pyarrow` 필요), 그 외 확장자는 CSV(같은 열). 속성별 한 행, 3분류 열 없음. 요약 파일은 Parquet 이면 `_summary_<이름>.json`, CSV 면 `<출력>.summary.json`. `--model-version` 으로 버전 값을 주고(기본 `MODEL_VERSION` 환경변수 또는 `unknown`), `--error-dir` 를 주면 파싱 실패 후기를 `errors_<model_version>.jsonl` 로 쓴다.
입력 형식: CSV(`review_id,text`) 또는 JSONL. 후기를 Kafka → S3/RDS에서 읽는 경우는 S3에 위 형식 파일로 떨어지게 하거나, 읽기 부분만 `read_reviews`에 추가한다.
