# 후기 점수화 배포 (s2c, 합친 모델)

1. 로컬 검증: `python deploy/check_prompt.py` → `python deploy/score_batch.py --model-dir private/merged/2.4b_score_s2c --input <후기.csv> --output <점수.csv>`
2. 전용 S3와 SageMaker 실행 역할은 Terraform으로 만든다. Terraform 코드는 `infra/` 규칙에 따라 이 폴더가 아니라 따로 올린다(이 폴더에는 없음). 팀 계정에서는 `infra/stacks/sagemaker-review-score`가 역할·보안 그룹·SSM 설정(`/clothes-query/dev/sagemaker-review-score/config`)을 만든다
3. 모델 버전 올리기 (릴리스 묶음). **manifest 하나 = 한 버전 세트**: 가중치(경로·파일별 크기·sha256), 실행 코드 사본(`score_batch.py`, `requirements.txt`), 고정 라이브러리 목록, 컨테이너 이미지, 번호, 추론 설정(`bs`)을 한 파일에 묶는다. 설계는 `release_bundle.py` 머리말.
   - 먼저 패치노트 `releases/<model_version>.yaml`을 쓴다(양식은 [releases/README.md](../releases/README.md)). **패치노트 검사를 통과하고 그 버전 파일이 있어야만 올라간다.** 검사만 할 때는 `python deploy/release_notes.py validate`
   - 라이브러리는 [`runtime-requirements.txt`](runtime-requirements.txt)에 `==`로 고정한다(고정 안 된 줄이 있으면 멈춘다). torch·CUDA 는 이미지에 들어 있다
   - 새 버전: `python deploy/upload_model.py --dir private/merged/<버전> --uri s3://<버킷>/review-score/model/<버전>/ --registry-uri s3://<버킷>/review-score/model-registry/releases/ --image-uri <이미지> --dry-run` → 확인 뒤 `--dry-run` 빼고 실행
   - 묶음 방식 이전에 올린 가중치(지금의 `2.4b_score_s2c`)는 같은 명령에 `--weights-already-uploaded`를 붙여 등록만 한다(로컬 파일과 S3 크기를 대조하고 다시 올리지 않음). 이미지는 지금 SSM 설정의 `image_uri` 값을 쓴다
   - 이미 묶음이 있는 버전, 이미 파일이 있는 가중치 폴더에는 올리지 않는다(덮어쓰기 없음). 실행 코드에 커밋 안 된 변경이 있으면 멈춘다(시험이면 `--allow-dirty`)
   - 패치노트 JSON은 묶음이 있는 버전만 S3에 올라간다(아직 모델을 올리지 않은 버전의 패치노트가 대시보드에 먼저 보이지 않게)
3-1. 되돌리기(roll-forward): Gold 가 가장 큰 번호를 읽으므로 번호를 내리지 않고 올리면서 되돌린다. 패치노트에 `based_on: <원래 버전>`을 쓴 새 버전 파일(번호는 문제 버전보다 높게)을 만들고 `python deploy/upload_model.py --model-version <새 버전> --registry-uri ...` 를 실행한다. 가중치를 다시 올리지 않고 원래 버전의 가중치·코드·라이브러리·이미지·추론 설정을 그대로 가리키는 묶음만 만든다. 그 뒤 SSM `release` 를 새 버전으로 바꾸면 번호가 올라 다음 실행에서 재점수화된다. 학습 PC·학습 데이터는 필요 없다
3-2. S3 파일 복구: 덮어쓰기를 막아 두어 거의 쓸 일이 없다. 실수로 지운 파일만 버킷 버저닝의 이전 VersionId 를 찾아 다시 복사한다(`aws s3api list-object-versions --bucket <버킷> --prefix <키>` → `aws s3api copy-object --copy-source "<버킷>/<키>?versionId=<id>" ...`). `review-score/model/`·`review-score/model-registry/`에는 수명주기 규칙을 걸지 않는다
4. S3 입력으로 테스트: `python deploy/score_batch.py --model-dir ... --input s3://<버킷>/input/reviews_100.csv --output s3://<버킷>/output/out_100.csv`
5. 수동 실행: `python deploy/run_processing_job.py --input-key <후기 파일 S3 키> [--release <버전>] --dry-run` 로 요청 확인 → `--wait` 로 실행. 실행 버전은 `--release`, 없으면 SSM 설정의 `release`(sagemaker 스택에 추가 예정, 그 전에는 `--release`를 준다). manifest 형식과 S3 가중치(이름·크기)를 대조해 어긋나면 Job 을 만들지 않는다. 가중치·코드·이미지·번호는 모두 manifest 에서 가져오고 SSM 에서는 역할·네트워크·출력 경로만 읽는다. 결과는 `staging/review-score/year=/month=/day=/scores_<model_version>_<실행시각>.parquet`(Iceberg MERGE 입력, 실행마다 새 파일)(날짜는 실행일이 아니라 **후기 작성일(KST)** 이고, 후기 행의 `review_date_kst` 등에서 읽어 날짜별로 나눠 쓴다. 날짜 없는 후기는 `--date` 또는 입력 키의 year=/month=/day= 를 쓴다). 하루 1회 실행은 Airflow silver DAG 종료 후 Airflow가 같은 방식으로 한다(다음 단계).

출력 형식: 출력 경로가 `.parquet` 이면 Parquet(팀 Silver 형식, 열 `review_id,aspect,score,model_version,model_version_no,analyzed_at,review_date`, `pyarrow` 필요), 그 외 확장자는 CSV(같은 열). 속성별 한 행, 3분류 열 없음. 요약 파일은 Parquet 이면 `_summary_<이름>.json`, CSV 면 `<출력>.summary.json`. `--model-version` 으로 버전 값을 주고(기본 `MODEL_VERSION` 환경변수 또는 `unknown`), `--error-dir` 를 주면 파싱 실패 후기를 `errors_<model_version>.jsonl` 로 쓴다.
입력 형식: CSV(`review_id,text`) 또는 JSONL. 후기를 Kafka → S3/RDS에서 읽는 경우는 S3에 위 형식 파일로 떨어지게 하거나, 읽기 부분만 `read_reviews`에 추가한다.

모델 번호(`model_version_no`, "x.y" 형식): 평가 모델/로직이 바뀌면 메이저를 올리고(0.0→1.0), 작은 수정·버그 수정이면 마이너를 올린다(0.0→0.1). 마이너는 0~9 까지이고 x.9 다음 변경은 메이저를 올린다. 현재 `2.4b_score_s2c` = `1.0`. 번호는 패치노트에 쓰고 manifest 에 복사되며, `run_processing_job.py` 가 manifest 에서 읽어 `score_batch.py --model-version-no` 로 넘긴다.

미점수 후기만 점수화하기: `python deploy/select_unscored.py --input-key <Silver 후기 파일 S3 키>`(개수만 보려면 `--dry-run`) 또는 `python deploy/run_processing_job.py --input-key <키> --select-unscored --wait`. 점수 로그(`review_score_log`)에 현재 모델 번호로 이미 기록된 후기를 빼고 남은 것만 입력으로 쓰며, 남은 후기가 0건이면 Job 을 만들지 않는다. Job 이 끝난 뒤 `merge.sql` → `merge_log.sql` 을 실행해야 다음 실행에서 "이미 점수 있음"으로 인식된다.
