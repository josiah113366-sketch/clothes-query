# 후기 점수화 배포 (s2c, 합친 모델)

1. 로컬 검증: `python deploy/check_prompt.py` → `python deploy/score_batch.py --model-dir private/merged/2.4b_score_s2c --input <후기.csv> --output <점수.csv>`
2. 전용 S3와 SageMaker 실행 역할은 Terraform으로 만든다. Terraform 코드는 `infra/` 규칙에 따라 이 폴더가 아니라 따로 올린다(이 폴더에는 없음). 역할 이름은 `review-score-sagemaker-processing-<리전>`을 기대한다
3. 모델 업로드: `python deploy/upload_model.py --dir private/merged/2.4b_score_s2c --uri s3://<버킷>/model/2.4b_score_s2c/` (`--dry-run`으로 목록 먼저 확인)
4. S3 입력으로 테스트: `python deploy/score_batch.py --model-dir ... --input s3://<버킷>/input/reviews_100.csv --output s3://<버킷>/output/out_100.csv`
5. 검증 후 팀 S3로 같은 방법 업로드, SageMaker Processing Job으로 하루 1회 실행(다음 단계).

출력 형식: CSV `review_id,aspect,score` (속성별 한 행, 3분류 열 없음) + `<출력>.summary.json`.
입력 형식: CSV(`review_id,text`) 또는 JSONL. 후기를 Kafka → S3/RDS에서 읽는 경우는 S3에 위 형식 파일로 떨어지게 하거나, 읽기 부분만 `read_reviews`에 추가한다.
