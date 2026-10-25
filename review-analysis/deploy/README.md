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

미점수 후기만 점수화하기(시험용, 파일 하나 지정): `python deploy/select_unscored.py --input-key <JSONL 후기 파일 S3 키>`(개수만 보려면 `--dry-run`) 또는 `python deploy/run_processing_job.py --input-key <키> --select-unscored --wait`. 점수 로그(`review_score_log`)에 현재 모델 번호로 이미 기록된 후기를 빼고 남은 것만 입력으로 쓰며, 남은 후기가 0건이면 Job 을 만들지 않는다. Job 이 끝난 뒤 `merge.sql` → `merge_log.sql` 을 실행해야 다음 실행에서 "이미 점수 있음"으로 인식된다.

### Silver 실행 출력에서 미점수 후기 점수화 — 수동 실행 (2026-10-25)

Silver 리뷰는 Spark 가 실행(run)별 경로(`silver/runtime/reviews/runs/<run_id>/silver_reviews/`, Parquet)에 쓰므로 경로가 계속 바뀐다.
그래서 athena 스택의 **읽기 전용 외부 테이블 `silver_reviews_runs`**(run_id 파티션 프로젝션)를 Athena 로 읽는다.
`select_unscored.py`(`--input-key` 없이)가 `silver/runtime/reviews/current.json` 의 `run_id`(status 가 PASS 일 때만)를 정하고, 그 실행의 후기 중 점수 로그에 현재 모델 번호가 없는 후기를 `--max-reviews`(기본 1500)건만 골라 `staging/review-score-input/…/unscored_<시각>.jsonl` 로 쓴다.
`silver_reviews_runs` 는 임시 읽기 전용 정의다(Silver 쪽이 `silver.reviews_runs` 를 공개하면 읽는 이름만 바꾸고 이 테이블은 지운다).

**0. 준비** (PowerShell, `review-analysis/` 폴더, AWS 자격이 잡힌 창)
```powershell
cd C:\workspace\e-commerce\clothes-query\review-analysis
# 주의: PowerShell 변수는 대소문자를 구분하지 않는다. $r 과 $R 은 같은 변수이므로 선택 결과는 $sel 로 쓴다
$R = "ap-northeast-1"
$S = aws ssm get-parameter --name /clothes-query/dev/sagemaker-review-score/config --region $R --query Parameter.Value --output text | ConvertFrom-Json
$A = aws ssm get-parameter --name /clothes-query/dev/athena-review-score/config   --region $R --query Parameter.Value --output text | ConvertFrom-Json
$B = $S.bucket
# manifest 에서 모델 이름·번호 (merge 에 쓴다)
$M = aws s3 cp "$($S.registry_prefix)$($S.release)/manifest.json" - --region $R | ConvertFrom-Json
$MV = $M.model_version; $MVNO = $M.model_version_no

function Run-Athena($sql) {   # 쿼리 실행 후 끝날 때까지 기다린다. 성공하면 실행 ID 를 돌려준다
  $id = aws athena start-query-execution --work-group $A.workgroup --query-string $sql --region $R --query QueryExecutionId --output text
  do { Start-Sleep 3; $st = aws athena get-query-execution --query-execution-id $id --region $R --query QueryExecution.Status --output json | ConvertFrom-Json } while ($st.State -in 'QUEUED','RUNNING')
  if ($st.State -ne 'SUCCEEDED') { throw "Athena $($st.State): $($st.StateChangeReason)" }
  $id
}
function Show($id) { aws athena get-query-results --query-execution-id $id --region $R --query "ResultSet.Rows[].Data[].VarCharValue" --output text }
function Fill($file, $day) {  # SQL 파일의 자리표시자를 값으로 바꾼다. $day = 'YYYY-MM-DD' (후기 작성일)
  $y,$m,$d = $day.Split('-')
  $t = Get-Content "..\infra\stacks\athena-review-score\sql\$file" -Raw -Encoding UTF8
  $map = @{database=$A.database; table=$A.table; log_table=$A.log_table; staging_table=$A.staging_table; staging_log_table=$A.staging_log_table;
           year=$y; month=$m; day=$d; model_version=$MV; model_version_no=$MVNO}
  foreach ($k in $map.Keys) { $t = $t.Replace("{{$k}}", [string]$map[$k]) }
  $t
}
```
- `score_batch.py` 를 고친 뒤에는 **S3 의 실행 코드 사본을 다시 올려야** 한다(릴리스 묶음 `…/releases/<버전>/code/`). 안 올리면 Job 이 옛 코드로 돌아 exit code 2 가 난다.
- `$A.silver_reviews_runs_table` 이 비어 있으면 `$A` 를 SSM 에서 다시 읽는다(athena 스택 apply 직후엔 값이 바뀐다).

**1. 건수 확인** (읽기만 한다, 파일을 쓰지 않는다)
```powershell
python deploy/select_unscored.py --dry-run                       # current.json 의 run_id (status PASS 일 때만)
python deploy/select_unscored.py --dry-run --run-id <run_id>     # 실행을 직접 지정 (completed/<run_id>.json 이 PASS 여야 함)
```
출력: `Silver 실행 <run_id>: 전체 N건, 이미 점수 있음 …, 점수 필요 …건 → 이번에 …건 선택, 남음 …건`

**2. 선택 + Job 실행**
```powershell
$out = python deploy/select_unscored.py --max-reviews 1500        # 후기를 골라 staging/review-score-input/ 에 JSONL 로 쓴다
$out                                                              # 사람용 요약
$sel = $out[-1] | ConvertFrom-Json                                  # 마지막 줄이 결과 JSON: run_id, selected, remaining, review_dates, output_key
if ($sel.selected -eq 0) { "남은 후기 없음 - 끝" } else {
  python deploy/run_processing_job.py --input-key $sel.output_key --wait     # Job 을 띄우고 끝날 때까지 기다린다
}
```
- 한 줄로 하고 싶으면 `python deploy/run_processing_job.py --select-unscored --wait [--run-id <id>] [--max-reviews 1500]` (선택과 Job 을 한 번에; 선택된 작성일이 화면에 나온다). 반복 자동화에는 위처럼 나누는 쪽이 편하다(작성일 목록 JSON).
- `--max-reviews` 기본 1500: Job 한 번(최대 3600초)이 초당 약 0.6~0.7건이라 약 2,200건이 한계이므로 여유를 둔다.
- Job 이 `Completed` 가 아니면 아래 3 으로 가지 않는다(오류 파일은 `silver/review_aspect_scores_error/`).

**3. 날짜별 반영** (선택된 작성일 = `$sel.review_dates` 또는 화면의 "작성일 … 에 대해")
```powershell
if (-not $sel.review_dates) { throw '작성일 목록($sel.review_dates)이 비었습니다. 2번의 $sel 를 확인하세요' }   # 비어 있으면 아래 루프가 조용히 아무것도 안 한다
foreach ($day in $sel.review_dates) {
  Run-Athena (Fill 'merge.sql'     $day) | Out-Null     # 점수 upsert + 빠진 속성 삭제
  Run-Athena (Fill 'merge_log.sql' $day) | Out-Null     # 후기별 점수 로그 (반드시 merge.sql 다음)
  "반영 완료: $day"
}
```
`merge_log.sql` 까지 끝나야 다음 선택에서 "이미 점수 있음"으로 인식된다.

**4. 확인**
```powershell
$V = "$($A.database).$($A.latest_view)"
Show (Run-Athena "SELECT count(*) AS rows, count(DISTINCT review_id) AS reviews FROM $V")                          # 점수가 들어간 후기 수
Show (Run-Athena "SELECT count(*) AS scored FROM $($A.database).$($A.log_table) WHERE model_version_no = DECIMAL '$MVNO'")   # 점수 로그(현재 번호)
python deploy/select_unscored.py --dry-run                                                                          # 남은 건수 (0 이 될 때까지)
```

**5. 남은 건수 0 까지 반복** — 첫 Silver 실행은 약 1.85만 건이라 약 13회(회당 약 40분, 합계 약 8시간, 비용 약 8.5달러)
```powershell
while ($true) {
  $out = python deploy/select_unscored.py --max-reviews 1500; $sel = $out[-1] | ConvertFrom-Json
  if ($sel.selected -eq 0) { "끝"; break }
  python deploy/run_processing_job.py --input-key $sel.output_key --wait
  if ($LASTEXITCODE -ne 0) { "Job 실패 - 멈춤"; break }
  if (-not $sel.review_dates) { "작성일 목록이 비어 멈춤"; break }
  foreach ($day in $sel.review_dates) { Run-Athena (Fill 'merge.sql' $day) | Out-Null; Run-Athena (Fill 'merge_log.sql' $day) | Out-Null }
  "방금 $($sel.selected)건 반영, 남음 $($sel.remaining)건"
}
```
Airflow DAG 가 생기면 이 반복은 DAG 가 맡는다.

**6. 자주 나는 오류**
| 증상 | 원인·조치 |
|---|---|
| Job exit code 2 | S3 의 `score_batch.py` 가 옛 버전. 새 파일을 릴리스 묶음 code/ 에 올린다 |
| `입력 파일이 없습니다 … NoSuchKey` | `--input-key` 의 키가 틀렸거나 지워짐. `select_unscored.py` 를 다시 실행해 새 파일을 만든다 |
| `Silver 실행 … status 가 PASS 가 아닙니다` | 그 실행은 읽지 않는다. 다른 `--run-id` 를 쓰거나 Silver 담당에게 확인 |
| `current.json 파일이 없습니다` / AccessDenied | Silver 경로 읽기 권한 확인: `python deploy/check_airflow_access.py --role <역할 이름>` |
| 같은 후기가 또 선택됨 / 남은 건수가 안 줄어듦 | `merge.sql` → `merge_log.sql` 을 아직 안 돌렸다(또는 다른 날짜가 빠졌다). `$sel.review_dates` 가 비어 있으면 루프가 조용히 건너뛰니 먼저 `$sel.review_dates` 를 출력해 본다. 점수 로그 행 수(`review_score_log`)가 늘었는지로 확인 |
| `athena 설정(SSM)에 … 가 없습니다` | athena 스택 apply 전이거나 `$A` 가 옛 값. SSM 을 다시 읽는다 |
| Git Bash 에서 SSM 이름 오류 | `/…` 이름이 변환된다. PowerShell 을 쓰거나 `MSYS_NO_PATHCONV=1` |

### 비교용 모델(s2r)로 1,500건 돌리기 (2026-10-25)

Gold 는 번호가 가장 큰 결과를 읽으므로 비교 모델은 s2c(1.0)보다 낮은 번호(0.1)로 올린다. 비교 모델은 **SSM 의 기본 실행 버전(`release`)을 바꾸지 않고** `--release` 로 지정해서만 돌린다.
이름과 번호는 그 버전의 릴리스 묶음(manifest)에서만 가져오고(따로 덮어쓰지 않는다), `merge.sql` 은 `model_version` 이름으로 구분해 쌓으므로 s2c 결과와 섞이지 않는다.
s2r 의 합친 모델과 릴리스 묶음은 2026-10-25 S3 에 등록했다(GPU PC 에서 병합 → 패치노트 `releases/2.4b_score_s2r.yaml` → `upload_model.py --weights-already-uploaded`). 다른 비교 모델을 추가할 때도 이 순서를 따른다. 묶음이 없으면 manifest 가 없어 실행이 멈춘다.

```powershell
# 위 "0. 준비" 블록($R, $S, $A 와 Run-Athena/Show/Fill)을 먼저 실행한 뒤 — 변수 $MV/$MVNO 를 비교 모델 것으로 바꾼다
$CMP = "2.4b_score_s2r"
$M = aws s3 cp "$($S.registry_prefix)$CMP/manifest.json" - --region $R | ConvertFrom-Json
$MV = $M.model_version; $MVNO = $M.model_version_no          # 2.4b_score_s2r / 0.1
"$MV $MVNO"

# 1) 같은 Silver 실행에서 점수 로그에 0.1 이 없는 후기 1,500건 선택 (정렬이 같아 s2c 첫 배치와 같은 후기가 뽑힌다)
$out = python deploy/select_unscored.py --model-version-no $MVNO --run-id reviews-v2-20261024T155307Z --max-reviews 1500
$sel = $out[-1] | ConvertFrom-Json
if (-not $sel.review_dates) { throw "작성일 목록이 비었습니다. 위 출력을 확인하세요" }

# 2) 비교 모델로 Job 실행 (SSM release 는 그대로)
python deploy/run_processing_job.py --release $CMP --input-key $sel.output_key --wait

# 3) 날짜별 반영 (merge → merge_log)
foreach ($day in $sel.review_dates) {
  Run-Athena (Fill 'merge.sql'     $day) | Out-Null
  Run-Athena (Fill 'merge_log.sql' $day) | Out-Null
  "반영 완료: $day"
}
# 끝난 뒤에는 위 "0. 준비" 블록을 다시 실행해 $MV/$MVNO 를 현재 버전으로 되돌린다
```
- 같은 후기를 s2c 도 점수화했는지: 대시보드 감성분석 모델 > 버전 비교 탭이 두 버전이 모두 점수를 낸 (후기, 속성) 쌍을 보여 준다(기준 A=2.4b_score_s2r, 비교 B=2.4b_score_s2c).
- 비교 실행으로 `review_aspect_scores_latest`(Gold)는 바뀌지 않는다(번호가 큰 s2c 결과가 우선). 미점수 후기 선택은 모델 번호별이라 기본 버전(1.0)의 남은 건수에도 영향이 없다.
- 비용·시간은 1,500건 기준 s2c 한 회와 같다(약 40분, 약 0.7달러).

### Airflow 실행 역할 권한 확인 (읽기 전용)

```powershell
python deploy/check_airflow_access.py --role <Airflow 업무 Pod 의 IAM 역할 이름>   # 여러 번 줄 수 있음
```

IAM policy simulator 로 "이 역할이 Silver 경로 읽기·staging 쓰기·Athena 쿼리·Glue 테이블 조회·SageMaker Job 생성·PassRole 을 할 수 있는가"를 표로 보여 준다(버킷 이름, 워크그룹, 테이블, Job 역할은 SSM 설정에서 읽는다). 버킷이 SSE-KMS 일 때만 KMS 항목을 보고, Lake Formation 기본 권한 설정도 알려 준다. AWS 를 바꾸는 호출은 하지 않는다. 종료 코드: 0 모두 허용, 1 막힌 항목 있음, 2 설정/역할을 못 찾음. athena 스택 apply 후 다시 돌려 "없음"이 "있음"으로 바뀌는지 확인한다.
