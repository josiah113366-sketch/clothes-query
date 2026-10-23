# 작업 지시서: pipelines/gold-b-dags

> 상태: 진행 중 · 브랜치: `pipelines/gold-b-dags` (최신 `main` `6c00ddc`, #99 머지 뒤) · 다음 작업: 구현 (2026-10-24 사용자: "2번 해줘")

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

- [ ] `python -m pytest -q pipelines/gold_b/tests` 통과
- [ ] DAG 시험 (가짜 Airflow 모듈로 읽기)
- [ ] `git diff --check`

## 작업 결과 (머지 전에 작성한다)
