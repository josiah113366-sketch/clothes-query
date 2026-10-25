# 작업 지시서: pipelines/gold-b-ops-fixes

> 상태: 진행 중 · 브랜치: `pipelines/gold-b-ops-fixes` (최신 `main` `25feba2`) · 담당: 은서 · 다음 작업: PR (사용자), DAG 실행 (재영 님) (2026-10-25 사용자: "1번 해줘", "3번 … 정리해줘", "4번 정리해줘")

## 목표

2026-10-25 운영 점검에서 찾은 Gold B 문제 두 개를 고치고, 시연 점검표와 문서를 정리한다.

1. **재처리 승인 대기:** 승인 범위의 시간 폴더가 끝나기 전에 승인하면 poller가 바로 골라 `FAILED`(다시 시도 안 함)로 끝났다. 승인 만료 전까지 기다렸다가 폴더가 끝나면 고르게 한다.
2. **파일 합치기 날짜 입력:** DAG가 어제(UTC)만 합쳐서, 적재 잡이 Kafka를 따라잡으며 쌓은 10-20~10-23 폴더를 합칠 방법이 없었다. DAG에 날짜 입력(`day`)을 두고, 비우면 지금처럼 어제를 합친다.
3. **시연 점검표:** 시나리오 3개와 재처리 시연에서 무엇을 걸고 무엇을 확인하는지.
4. **문서 정리:** 설계 문서 체크리스트(이미 끝난 항목), `pipelines/gold_b/README.md`, #100·#101 머지 표시.

만들지 않는 것: 대시보드 화면(`dashboard/gold-b-scenarios`), 인프라 권한, 시뮬레이터 사건.

## 먼저 읽을 것

- `pipelines/gold_b/jobs/README.md` 「다음에 돌릴 요청 고르기 (poller)」, 「파일 합치기」
- `infra/platform/airflow/dags/gold_b.py`, `pipelines/gold_b/tests/test_dags.py`
- `docs/design/gold-b/README.md` 「⑤ reprocess_events」, 6·7·9·10단계
- `docs/design/agent/anomaly-answer-key.md` (시나리오·사건·판정 규칙)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 위 1·2는 설계에 없던 동작 변경이지만 사용자가 고치기로 정했다 (2026-10-25 "1번 해줘").
- `pipelines/gold-b-workflow-doc`(push 안 함)에서 정리 커밋(#100·#101 머지 표시, 설계 체크리스트 4개)만 가져온다. 워크플로우 문서·그림은 넣지 않는다 (사용자가 노션에 따로 둠, 2026-10-24).

## 정한 기본값

1. 기다리는 조건은 잡의 시작 전 확인과 같다: 마지막 시간 폴더 끝 + 10분(`Options.margin`). 기다리는 동안에도 승인 만료(60분)는 그대로다. 만료되면 승인 화면에서 새로 요청한다.
2. 범위가 잘못된 요청(끝 ≤ 시작)은 기다리지 않고 골라서, 잡이 이유와 함께 `FAILED`로 남긴다.
3. 할 일이 없을 때 로그에 기다리는 승인 수를 같이 쓴다 (왜 안 도는지 Airflow 로그로 알 수 있게).
4. 합치기 날짜는 Airflow `Param`(문자열, `YYYY-MM-DD` 또는 빈 값)이다. Pod 환경변수 `GOLD_B_COMPACT_DAY`로 넘기고, 잡은 빈 값이면 어제(UTC)를 합친다. 날짜 형식은 Airflow와 잡이 둘 다 확인한다. 명령 인자(`--day`)로 넘기면 DAG 파일이 이미지보다 먼저 바뀌었을 때 옛 이미지가 빈 값을 못 읽어 실패해서, 옛 이미지가 무시하는 환경변수로 넘긴다 (Python 3.10·3.12에서 `--`만 넘기는 방법도 실패함을 확인).
5. 점검표는 `docs/design/gold-b/scenario-checks.md`에 둔다 (상태: 제안. 사건 거는 법·판정 기준은 탐지·시뮬레이터 문서를 따른다).

## 작업 순서

1. 이 지시서, 브랜치 대장, #100·#101 정리
2. 재처리 poller 기다리기와 시험
3. 파일 합치기 날짜 입력(잡·DAG)과 시험
4. 시나리오·재처리 시연 점검표
5. 설계 문서 체크리스트·README 정리, 작업 결과

## 완료 확인

- [ ] `python -m pytest -q pipelines/gold_b/tests` 통과
- [ ] 실제 Airflow 3.3.2에서 `airflow.sdk.Param`과 KubernetesPodOperator `arguments` 템플릿 확인 (가져오기만)
- [ ] `git diff --check`

## 작업 결과 (머지 전에 작성한다)
