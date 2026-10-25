# 완료 리뷰 Silver 재사용·Gold-only 집계

상태: 완료 (로컬 구현·최소 검증 완료, 실제 AWS 운영 검증 전)

## 결정·범위

- 완료된 PASS 리뷰 Silver와 같은 실행의 상품 Parquet을 재사용한다. Bronze/Silver 재처리와 모델 점수화는 하지 않는다.
- 최신 모델 점수는 기존 review_scores.snapshot_scores로 Athena 뷰에서 실행별 Parquet으로 고정한다. 기존 점수·중복·연결·집계 규칙은 유지한다.
- 기존 spark_batch.py의 job=reviews 진입점을 유지하고 요청의 gold_only=true로 분기한다. 퍼널 코드·DAG는 수정하지 않는다.
- 새 Gold run_id, 기존 silver_run_id·manifest·SHA256, 상품 manifest·SHA256, 점수 snapshot 출처를 보존한다. Gold 공개 목록도 기존 Silver ID를 기록한다.

## 실행 요청

- 예시: pipelines/examples/reviews-gold-only.json. 새 run_id와 실제 기존 manifest 바이트의 SHA256으로 교체해야 한다. 날짜는 기존 Silver의 전체 KST 범위와 같아야 한다.
- 상품은 기존 Silver 실행의 products/manifest.json에 기록된 PASS Parquet을 사용한다. 없거나 품질·건수·스키마 검증에 실패하면 중단하며 seed에서 임의 재생성하지 않는다.
- 같은 데이터 레이크 root 안에서만 재사용한다. Silver manifest와 completed 기록 일치·해시, Parquet 건수/스키마, 실제 DQ PASS·격리 0·키/날짜/별점 등을 검사한다.
- 기존 silver_gold_a_reviews DAG의 conf에는 config_uri만 전달한다. 예시 요청은 아직 업로드하지 않았으며 main·이미지 반영과 운영 검수 후 실행할 수 있다.
- Gold 데이터·새 완료 manifest 저장 후 기존 gold_publication.py로 공개한다. Gold-only 공개는 기존 PASS Silver 완료 기록과 해시를 다시 검사한다.

## 작업 결과

- 변경 코드는 gold_a/reviews.py와 gold_publication.py뿐이며 review_scores.py·spark_batch.py·퍼널·DAG는 그대로 유지했다.
- Python 3.12에서 완료 출처·해시·품질/범위 거부·공개 Silver ID 보존 9개와 기존 Gold 공개 실패/재시도 회귀 1개, 총 10개 통과. 초기 로컬 시험은 sandbox 임시 폴더 생성 권한 문제로 8개 setup 오류가 있었으며 작업 공간의 전용 basetemp로 해결했다.
- 운영 Python 3.10.12/Spark 4.2 이미지에서 신규 Gold-only 시험 1개 및 기존 일반 리뷰 점수 스냅샷 시험 1개 통과. 소스는 읽기 전용 마운트, AWS 호출은 대체하고 네트워크 차단. 새 이미지 빌드는 하지 않았다.
- 신규 시험은 기존 Silver·상품 Parquet만 사용, 상품별 리뷰 3건/별점 합계 10/평균 3.3333, 모델별 속성 집계 2행/중복 점수 제외/미채점 1건을 확인했다. 기존 Silver manifest·completed·current·Parquet이 바뀌지 않고 새 Silver 실행 폴더도 생성되지 않음을 확인했다.
- Ruff(py310), git diff --check 통과. 전체 테스트는 재실행하지 않았다.
- 최신 main 738cbd1과 차이·충돌 없음 확인. 열린 PR 없음. 확인한 리뷰 담당 원격 review-model/compare-model 변경은 review-analysis/에 있어 대상 파일과 겹치지 않았다. 다른 사람의 미공개 로컬 수정 여부는 확인할 수 없다.
- 실제 기존 실행의 상품 manifest 존재·내용, 최신 점수와 기존 Silver의 연결 건수, 실제 Athena/대시보드 공개는 AWS 운영 검증으로 남긴다.
- 운영 Silver/Gold current·manifest에 쓰기를 수행하지 않았다. 로컬 검증에서는 기존 Silver 원본 보존을 확인했다. 실제 Gold-only 성공 시 새 Gold 결과와 완료 기록을 만들고 기존 공개 함수로 Gold current를 갱신하며, 기존 실행별 manifest는 보존한다.
- 사용자 승인에 따라 관련 파일만 커밋·push·PR 제출한다. AWS 실행·S3 업로드·이미지 발행은 수행하지 않는다. 이미 통과한 전체 시험은 반복하지 않는다.
