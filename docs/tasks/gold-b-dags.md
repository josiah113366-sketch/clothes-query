# 작업 지시서: pipelines/gold-b-dags

> 상태: 검토 대기 · 브랜치: `pipelines/gold-b-dags` (최신 `main` `6c00ddc`, #99 머지 뒤) · 다음 작업: PR (사용자), 실행 설정·pool 준비 뒤 DAG 켜기 (재영 님)

## 목표

Gold B 재처리 잡과 파일 합치기를 Airflow로 돌릴 DAG 2개를 만든다. 승인 화면은 `gold_b_reprocess` DAG가 5분마다 승인 줄을 읽는다고 보고 만들어져 있다 (`agent/approval/approval.py`의 `dag_by_rule`: R1·R4·R5 → POLLER). DAG는 꺼진 채로 올라가고, 인프라가 실행 설정·pool을 준비한 뒤 켠다.

## 먼저 읽을 것

- `infra/platform/airflow/dags/silver_gold_a.py`, `infra/platform/airflow/dags/README.md`: 팀 DAG 방식 (Airflow 3, KubernetesPodOperator, 실행 설정 JSON, 꺼진 채로 생성, 설정이 없으면 확인 태스크에서 멈춤)
- `pipelines/gold_b/jobs/README.md` 「Airflow DAG 명세」, 재처리·파일 합치기 실행 입구
- `pipelines/gold_b/README.md` 「이미지」 (이미지 안 실행 명령)
- `agent/approval/approval.py` (`gold_b_reprocess`를 POLLER로 부름)

## 정한 기본값 (설계에 없는 세부, 2026-10-24 사용자 "해줘")

1. **파일:** `infra/platform/airflow/dags/gold_b.py` 하나에 DAG 2개. Airflow가 main의 이 폴더를 약 60초마다 읽는다 (Silver DAG와 같은 자리, Silver DAG도 pipelines 브랜치에서 더함). 인프라 설정·권한은 바꾸지 않는다.
2. **`gold_b_reprocess`:** 5분마다(`*/5 * * * *`), 밀린 실행은 하지 않음(catchup 끔), 한 번에 하나(max_active_runs 1), Airflow 재시도 0 (다시 돌릴지는 잡의 poller가 `reprocess_events`를 보고 정함), 실행 상한 2시간. 명령 `python3 -m pipelines.gold_b.jobs.reprocess`.
3. **`gold_b_compact`:** 매일 00:30 UTC (끝난 어제 + 여유 10분 뒤), 한 번에 하나, 재시도 2번(10분 간격, 합치기는 다시 돌려도 결과가 같음). 명령 `python3 -m pipelines.gold_b.jobs.compact` (날짜를 주지 않아 어제 UTC).
4. **실행 설정:** 환경변수 `AIRFLOW_GOLD_B_RUNTIME` JSON (인프라가 공급, Silver의 `AIRFLOW_PIPELINE_RUNTIME`과 따로). 키: `image`(digest), `namespace`, `service_account`, `ledger_root`, `kafka_bootstrap`, `kafka_tls_secret`, `pool`, `node_selector`. 없거나 틀리면 확인 태스크에서 멈추고 Pod를 띄우지 않는다. `agent`·`kafka`·`kube-system` namespace는 거부한다 (Silver와 같음).
5. **같은 시간에 돌지 않기:** 두 DAG의 Pod 태스크를 같은 pool(`pool` 키, 예: 슬롯 1개짜리 `gold_b_ledger`)에 넣는다. 재처리가 승인 범위 밖 결제 시각 폴더도 고칠 수 있어서다 (#99). pool을 아직 만들지 않았으면 Airflow 기본 pool을 쓴다 (지금 Airflow는 전체 동시 작업 1개라 겹치지 않음).
6. **Pod:** Gold B 이미지, 실행 신원(Pod Identity: S3 원장 읽기·쓰기), k8s API 토큰은 붙이지 않음(automount 끔), EC2 메타데이터 끔, 자원 요청 0.25 CPU·512Mi / 상한 1 CPU·2Gi, 끝나면 Pod를 지운다.
7. **Kafka (재처리만):** 인증서 Secret(`kafka_tls_secret`, 키 `ca.crt`=Kafka 클러스터 CA, `user.crt`, `user.key`)을 `/opt/kafka-tls`에 붙이고 `KAFKA_SSL_*` 경로를 준다. `KAFKA_SECURITY_PROTOCOL=SSL`.
8. **시험:** Airflow 없이 가짜 모듈로 DAG 파일을 읽어 DAG 설정·명령·환경변수·확인 규칙을 본다 (`pipelines/gold_b/tests/test_dags.py`).

## 만들지 않는 것

- Airflow pool, 실행 설정 ConfigMap, namespace, 실행 신원·Pod Identity, Kafka 사용자·Secret (재영 님)
- 판정 잡 변경 (주현 님)
- Bronze 재처리 (다음 브랜치. 그때 이 DAG에 Bronze 위치 설정을 더한다)

## 작업 순서

1. 머지된 #99 정리와 이 지시서 (2026-10-24)
2. DAG 파일·시험·문서
3. "완료 확인" 실행과 작업 결과 기록

## 완료 확인

- [x] `python -m pytest -q pipelines/gold_b/tests` 통과 (226개, 로컬 Python 3.12)
- [x] DAG 시험 (가짜 Airflow 모듈로 읽기, 18개)
- [x] `git diff --check`

## 작업 결과 (머지 전에 작성한다)

### 만든 것

- `infra/platform/airflow/dags/gold_b.py`: DAG 2개
  - `gold_b_reprocess`: 5분마다 설정 확인 → Pod `python3 -m pipelines.gold_b.jobs.reprocess`. Airflow 재시도 0, 실행 상한 2시간. Kafka 인증서 Secret을 `/opt/kafka-tls`에 붙이고 `KAFKA_SECURITY_PROTOCOL=SSL`과 `KAFKA_SSL_*` 경로를 준다.
  - `gold_b_compact`: 매일 00:30 UTC 설정 확인 → Pod `python3 -m pipelines.gold_b.jobs.compact` (날짜 없음 = 어제 UTC). 재시도 2번(10분 간격), 실행 상한 1시간.
  - 공통: 꺼진 채로 생성, catchup 끔, 한 번에 하나, 두 Pod가 같은 pool(`pool` 키, 없으면 기본 pool), automount 끔, EC2 메타데이터 끔, 요청 0.25 CPU·512Mi / 상한 1 CPU·2Gi, 끝나면 Pod 지움. Pod 이름은 `gold-b-reprocess`, `gold-b-compact`.
  - 실행 설정 `AIRFLOW_GOLD_B_RUNTIME`: digest 이미지·namespace·실행 신원·`s3://` 원장 위치가 없으면 두 DAG 모두, Kafka 주소·인증서 Secret이 없으면 재처리만 확인 태스크에서 멈춘다. `agent`·`kafka`·`kube-system` namespace는 거부한다. 설정이 없어도 DAG 파일은 읽혀 Airflow 화면에 보인다.
- `pipelines/gold_b/tests/test_dags.py` (18개): 가짜 Airflow·Kubernetes 모듈로 DAG 파일을 읽는다. DAG 설정, Pod 명령·환경변수·인증서, 같은 pool(없으면 기본 pool), 노드 배치, 설정 확인 규칙을 본다. 잡과 맞물리는지도 본다: 재처리 잡이 Pod 환경변수로 만든 Kafka 설정이 붙인 인증서 파일을 가리키는지, 00:30에 날짜 없이 부르면 파일 합치기 잡이 어제를 거부하지 않는지.
- 문서: DAG 설명(`infra/platform/airflow/dags/README.md` 「Gold B 재처리·파일 합치기 DAG」: 실행 설정 예와 켜기 전에 준비할 것), 잡 설명의 DAG 절(`pipelines/gold_b/jobs/README.md`), Gold B README 표, 설계 문서(6·7단계 체크리스트, 파일 구조, 재영 님 확인 표, poller 절).

### 왜

- 승인 화면이 R1·R4·R5 재처리를 `gold_b_reprocess`가 5분마다 읽는다고 보고 만들어져 있어서, 이 DAG가 없으면 승인된 Gold B 재처리가 돌지 않는다.
- 파일 합치기를 돌리지 않으면 시간 폴더마다 1분짜리 파일이 60개 넘게 쌓인다.
- 시간대는 `timezone.utc`로 썼다 (Silver DAG는 `UTC`). Airflow는 Python 3.12라 둘 다 되지만, Gold B 시험을 팀 기본 이미지의 3.10에서도 돌릴 수 있게 했다.

### 확인한 결과

- `python -m pytest -q pipelines/gold_b/tests`: 226개 통과 (로컬 Python 3.12)
- DAG 시험 18개 통과. DAG 파일을 일부러 틀리게 바꾼 8가지(재처리 재시도 1, pool 고정, Kafka 설정 확인 빠짐, CA 경로 틀림, 거부할 namespace 빠짐, 합치기 시각 00:05, automount 켬, 합치기에 Kafka 확인)를 모두 시험이 잡았다.
- `git diff --check`: 문제 없음
- 실제 Airflow에서 읽히는지와 Pod 실행은 확인하지 못했다 (실행 설정·이미지가 아직 없음).

### 다음 할 일

- 재영 님: Gold B 이미지 빌드·ECR, `AIRFLOW_GOLD_B_RUNTIME` 공급, pool(슬롯 1개), 잡 namespace·실행 신원(S3 권한)·Pod 실행 RBAC, Kafka TLS 사용자와 인증서 Secret. 그 뒤 DAG를 켜고 한 번씩 돌려 본다.
- 다음 브랜치 `pipelines/gold-b-bronze-reprocess`: 보관 기간(7일)이 지난 폴더를 Bronze v2 파일에서 읽는 재처리. 그때 이 DAG에 Bronze 위치 설정을 더한다.
