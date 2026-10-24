# 조사 단독 시험과 Airflow 승인 API 연결

상태: 2026-10-24 KST 실제 클러스터 시험 성공, 시험 종료 정리 완료.

## 시험 범위와 결과

사용자가 전달한 PR #105 `agent/test-anomaly`의 `agent/investigator/test_anomaly.sql`을 사용했다. 소스 커밋은 `b9282f9f421d3fb158a1230440fe9aa646c551e6`이다. PR 머지나 업무 코드 수정 없이 `a-test-0001` 한 건을 추가했다. 규칙은 `R1_PG_FAILURES`, 범위는 `PG_A`이며 근거에 `test: true`가 있다. 실제 원장에 근거가 없으므로 UNKNOWN도 허용한다는 담당자의 최신 성공 기준을 적용했다.

- 사전 확인: 기존 시험 줄·리포트·실행 기록 0건, 다른 조사 대기와 만료 처리 대상 0건.
- 원래 paused였던 `agent_investigation_5min`을 잠시 활성화했다. 수동 trigger 없이 예약 실행으로 처리했다.
- `scheduled__2026-10-24T06:40:00+00:00` 실행과 investigation 태스크가 첫 시도에 success였다.
- 실제 조사 ServiceAccount Pod의 컨테이너 종료 코드 0을 삭제 전 Kubernetes watch로 확인했다.
- JP Haiku 프로필 `jp.anthropic.claude-haiku-4-5-20251001-v1:0` 호출 4회, 도구 호출 7회가 실행 기록에 남았다.
- `agent.investigation_reports`와 `agent.investigation_runs`에 각각 1건이 저장됐다. 실행 상태는 REPORTED, 원인 층은 UNKNOWN이었다. UNKNOWN 허용 계약에 따라 연결 시험 성공이다. 분석 품질 전체를 평가한 결과는 아니다.

## 시간 측정

모두 2026-10-24 KST이다. 논리 실행 시각을 실제 시작 시각으로 계산하지 않았다.

| 구간 | 시각 또는 소요 시간 |
|---|---|
| 시험 INSERT 완료 | 15:41:46.450 |
| Airflow 태스크 시작 | 15:42:11.364 |
| 예약·활성화 대기: INSERT 완료 → 태스크 시작 | 약 24.9초 |
| 태스크 실행 | 15:42:11.364 → 15:43:15.380, 약 64.0초 |
| 컨테이너 실행 | 15:42:17 → 15:43:11, 54초 |
| 조사 코드 실행 기록 | 15:42:21 → 15:43:05, 44초 |
| DAG 최종 success | 15:43:16.266 |

일시정지를 해제한 직후의 예약 실행 한 번을 측정했다. 모든 사건이 이 시간 내에 처리된다는 보장은 아니다.

## 정리와 보존

조사 DAG는 원래대로 paused로 복원했고 판정 DAG는 활성 상태를 유지했다. 일시정지 직전 15:45 예약 실행이 하나 더 생성돼 해당 실행의 정상 종료도 확인했다. 종료 후 조회에서 시험 리포트·실행 기록은 각각 1건이었다.

제공 SQL대로 같은 anomaly_id에 RESOLVED 줄을 추가했고 `gold_b.anomaly_current`의 RESOLVED를 확인했다. 이상 줄·리포트·실행 기록을 삭제하지 않았다. 채점에서 `a-test-`를 제외하는 변경은 별도 #96 브랜치에 있어 main 반영 여부는 채점 담당자가 확인해야 한다.

## 승인 화면 담당자에게 전달할 연결

대시보드 Pod 안에서 실제 내부 접속과 인증을 확인했다.

- `AIRFLOW_API_URL=http://airflow-api-server.airflow.svc.cluster.local:8080`
- namespace `dashboard`, ServiceAccount `approval-dashboard`
- 인증: Simple Auth Manager 사용자/비밀번호로 `POST /auth/token`, 받은 access token을 이후 요청의 `Authorization: Bearer ...`에 사용한다.
- Secret `dashboard/airflow-api-client`의 `username` → `AIRFLOW_API_USER`, `password` → `AIRFLOW_API_PASSWORD`로 참조한다. 비밀값 자체는 문서나 메시지로 전달하지 않는다.
- 실제 대시보드 Pod의 토큰 발급 HTTP 201, 두 DAG `gold_b_reprocess`·`silver_gold_a_reprocess` 조회 HTTP 200을 확인했다. 재처리 trigger나 승인 기록 생성은 하지 않았다.

## Sink 정지 리허설은 일정 협의 대기

이번 시험에서는 `bronze-s3-sink-v2`를 멈추지 않았고 요청 상태 running을 확인했다. 리허설은 성철 담당자의 시작 기록 → 인프라 정지 → 35~40분 관찰 → 인프라 running 복원 및 실제 connector/tasks·S3 재개 확인 → 담당자 끝 기록 순서로 별도 진행한다. 공동 시작 시각이 아직 정해지지 않았다.
