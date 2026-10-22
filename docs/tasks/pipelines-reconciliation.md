상태: 완료 · 브랜치: `pipelines/reconciliation`

# Kafka 원본 추적과 결제 대조 설계

## 제출 범위

최신 main 기준으로 선택적 Kafka 메타데이터 추적만 구현한다. 실제 대조 잡·Sink/Gold B 변경·자동 실행은 제안으로 분리한다. Gold A 코드는 포함하지 않는다. 실행 변경은 기존 Silver common.py/transactions.py, 검증은 기존 test_transactions.py에 한정한다.

## 작업 및 검증 기록

## 2026-10-21 승인된 대조 설계·원본 추적

- 목적: Silver/Gold B 결제 경로 대조 초안과 담당자별 PR 검토 항목을 기존 공통 계약에 모은다. 작업 브랜치는 pipelines/silver이며 #34가 이 브랜치로 합쳐진 원격 이력을 fast-forward로 반영했다. main 머지와 원격 제출은 이번 작업에서 하지 않는다.
- 승인 범위: 기존 common.py/transactions.py에 선택적 Kafka 추적 검증·후보/격리 참조·실행별 관측 범위를 추가한다. 기존 거래 테스트에 원본 추적·누락/잘못된 메타데이터·업무 중복 분리를 검증한다. 새 코드/테스트 파일은 만들지 않는다.
- 실제 대조 잡·Gold B 어댑터·Kafka Sink 변경·Airflow/알림은 합의 후 연결한다. 관측 min/max는 완료 증거가 아니며 coverage_status=UNVERIFIED다. 업무 규칙 YAML과 추적 입력 초안을 혼합하지 않는다.

### 작업 결과: 대조 초안·추적

- 공통 계약에 비교 단계·결과 상태·구조도·단계별 후속 구현·PR 확인 체크표를 추가했다. 각 체크는 수용/구현 완료와 구분한다.
- 거래 입력의 검사된 Kafka 정보는 impact_candidates.source 및 격리 kafka_reference에 남긴다. current.json.kafka_observations에서 입력별 관측 범위와 추적 유효성 건수를 확인할 수 있다. 메타데이터가 없는 입력도 처리하고 업무 계산에는 섞지 않는다.
- 실제 데이터/Sink/Gold B 대조를 완료한 것이 아니다. 검증 결과는 실행 후 아래에 기록한다.
- 검증: Silver·Gold A·연결 테스트 47개 통과(9.22초), 변경 common.py/transactions.py Ruff와 git diff --check 통과. 같은 Kafka 위치 재수신·충돌 후보 양쪽 위치·누락/잘못된 추적 정보·메타데이터와 업무 중복 판정 분리를 기존 테스트 파일에서 확인했다. 실제 AWS 호출은 하지 않았다.


## 제출 전 정리

- 위 Silver 브랜치 작업 기록은 이번 구현의 최초 로컬 검증 이력이다. 실제 제출은 최신 main 기반의 pipelines/reconciliation이며 원래 Silver/Gold A 이력은 보존한다.
- 기존 Silver 작업 지시서는 main 버전 그대로 두고 이번 기록만 이 파일에 모은다.
- main 기반 Silver 회귀 검증, Ruff, diff 검사와 변경 범위를 확인한다. 실제 AWS·Gold B 실행이나 대조 판정은 하지 않는다.

## 최종 작업 결과

- main 기준 Silver 테스트 29개 통과(2.19초), 변경 실행 파일 Ruff 및 git diff --check 통과. Gold A 코드는 main에 없으므로 47개 전체 검증은 최초 작업 브랜치의 과거 기록이며 이번 제출 검증 수와 구분한다.
- 현재 제출 범위는 계약 설계·Silver 추적 코드·기존 거래 테스트·Silver 설명·브랜치 등록·이 지시서다. 기존 Silver 지시서는 변경하지 않는다.
- 메타데이터 관측은 입력 완료 증거가 아니며 모든 실행의 coverage_status는 UNVERIFIED다. 실제 비교 어댑터와 합의된 완료 범위 증거가 준비되기 전에는 대조 잡을 실행하지 않는다.
- 2026-10-22 main 통합: 최신 origin/main을 병합하고 브랜치 대장의 양쪽 등록을 보존해 충돌을 해결했다. Silver 29개 통과(2.36초), 실행 파일 Ruff 및 diff 공백 검사 통과. 실제 대조 잡을 구현한 것으로 표시하지 않는다.
