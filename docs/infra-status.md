# 인프라 작업 현황과 공유 순서

기준일: 2026-10-22 KST. Git 기준 main은 `0312bad`(#69 공유 ALB 템플릿 머지)다. 실제 상태는 아래 각 작업의 마지막 적용·관측 기록을 뜻하며, 이 문서 작성 과정에서 AWS 전체를 다시 조회하거나 배포하지 않았다.

## 현재 위치

RDS → CDC → Kafka → S3 Bronze 경로는 연결·스모크 시험 이력이 있다. Airflow·모니터링·Argo CD도 설치되어 있다. **설치 완료와 실제 업무 파이프라인 완료는 다르다.** Spark는 합성 시험 후 임시 리소스를 정리했으며 업무 처리용 상시 배포는 비활성이다. Bedrock 외에도 업무 이미지·DAG·S3·Glue 및 승인 화면의 연결 검증이 남아 있다.

main 밖의 원본 작업 여섯 브랜치는 아래에 보존했다. 사용자 승인으로 최신 main에서 공유용 브랜치 세 개를 만들었다. 서로 다른 시점에 작성된 원본 작업 지시서의 '로컬 보관', '다음 단계' 문구는 당시 기록이다. 현재 공유 상태는 이 문서와 통합 작업 지시서를 기준으로 판단한다.

| 공유 묶음 | 통합 브랜치 | 내용 |
|---|---|---|
| 운영 도구 | `infra/operations-tools-share` | 모니터링 + Argo CD |
| 데이터·Airflow 연결 | `infra/data-runtime-share` | Airflow·승인 화면 연결 + Gold B 카탈로그 + 점검 기록 + 이 현황 문서 |
| Spark 준비 | `infra/spark-preparation-share` | 기본 비활성 Spark 실행 기반·연결 준비 |

| 작업 | 보관 브랜치 / 커밋 | 마지막 확인한 적용·시험 범위 | 남은 작업 |
|---|---|---|---|
| 모니터링 | `infra/monitoring-baseline` / `c76809a` | 기존 API 노드에 Prometheus·Grafana·Metrics Server 설치, 수집 대상 5개 정상, 짧은 WAS 부하 관찰 | main 반영, Pod·노드 자원 이력·업무 도착 지표·외부 알림은 후속 |
| Argo CD | `infra/argocd-runtime` / `6f84450` | 기존 API 노드에 설치, 로그인·저장소 접근·권한 확인 | main 반영, Application 등록·배포 소유권 전환·실제 sync 검증. 자동 배포는 미연결 |
| Airflow·승인 화면 연결 기반 | `infra/agent-runtime-connections` / `444418c` | Git DAG 공급, dashboard 전용 AWS 역할·Pod Identity·workgroup, API 인증 연결 시험 | main 반영, 업무 대시보드·DAG·이미지 연동. JP Haiku 모델 선택 완료, invoke 권한은 미적용 |
| Gold B 카탈로그 | `infra/gold-b-catalog` / `7499681` | Glue DB·원장 테이블 등록 이력 | main 반영. 이번 현황 작성에서는 Glue를 재조회하지 않음. agent #53 전체 업무 DDL 적용 완료를 뜻하지 않음 |
| Spark 기반·Silver/Gold A 연결 준비 | `infra/spark-runtime-prep` / `c311785` | 기본 이미지 로컬 시험, EKS 합성 계산과 Executor 1→2→1 검증, 임시 리소스 정리. 연결 변수·권한 병합 도구 준비 | 미정 명세 수령 후 역할·ECR·업무 이미지·DAG 연결 및 실제 S3 입출력 검증. 공유 설정 `enabled=false` 유지 |
| 읽기 전용 점검·DAG 공급 안내 | `infra/live-code-audit` / `01ec915` | 실제 배포/main 차이, Kafka lag 패턴, Git DAG 로딩, RDS 슬롯·WAL·Kafka 디스크 관측 | Airflow 연결 PR 이후 안내서 중복 조정. 점검 기록이며 새로운 배포 설정이 아님 |

원본 작업 기록은 각 브랜치의 `docs/tasks/infra-<작업명>.md`에 있다. 데이터·Airflow 묶음은 이 문서와 관련 실행 코드를 함께 담는다. 다른 두 묶음은 독립 PR로 검토한다.

## 검토·머지 순서

1. 위 세 묶음을 초안 PR 세 개로 공유한다. 운영 도구와 데이터·Airflow 사이에 필수 배포 선후 관계를 새로 만들지는 않는다.
2. 데이터·Airflow 묶음에서 Git 공급 values와 DAG_DELIVERY.md·README를 함께 정리한다. 점검 기록은 당시 관측이며 재배포 결과로 해석하지 않는다.
3. Spark는 노드 비활성·업무 미실행 상태로 공유하고 명세가 모두 올 때까지 배포를 기다린다.
4. 각 PR의 검토 직전에 앞서 머지된 PR과 이후 main 변경을 반영하고 필요한 검사를 수행한다. 검토·승인·머지는 팀원이 수행한다.

처음 여섯 원본을 각각 main `0312bad`와 검사했을 때 텍스트 충돌은 없었다. 이후 승인된 묶음 내부 통합에서 공통 대장·README 동시 추가 충돌이 나 양쪽 내용을 보존했다. 서로 다른 공유 PR 사이의 공통 대장·README·workflow 변경은 앞 PR 머지 후 다시 확인한다.

기준 main의 Airflow values는 이전 ConfigMap DAG 공급 설정이므로 실제 GitDagBundle과 차이가 있다. 이 묶음에는 현재 Git 공급 설정을 포함했으며 main에 머지되기 전 이전 values로 무심코 upgrade하지 않는다. monitoring/argocd 디렉터리가 main에 없다고 기존 별도 Helm release가 자동 삭제되는 것은 아니다.

## Spark 연결에 필요한 팀원 입력

| 항목 | 확정/대기 내용 |
|---|---|
| 개발자 ECR push 신원 | `arn:aws:iam::827913617635:user/de-ai-18` 확정. 아직 push 권한 추가 적용 전. 실행용 Pod Identity 역할과 분리하며 추후 ARN 교체 가능 |
| 실행 공간 | `pipelines` 제안. Gold B 공유 여부·제출기/Driver/Executor 계정 이름 확정 필요 |
| 입력 | `s3://clothes-query-datalake/bronze/orders/`, `bronze/order-items/`, `bronze/payments/` JSON Lines. 상품 스냅샷 경로·첫 검증 고정 객체 목록은 대기 |
| 출력 | `silver/runtime/trade/`, `gold_a/runtime/trade/` 기준으로 로컬 권한 계획 준비. manifest·완료 기록·current.json은 각 출력 루트 안에 포함. 실제 권한 적용 전 |
| 실행 요청 | `--config-uri`가 읽을 요청 JSON prefix·첫 고정 객체 경로 필요 |
| 이미지·실행 | 최종 업무 이미지 digest, 구현된 진입 파일·인자·패키지 필요. 기본 이미지 영구 ECR 발행도 미완료 |
| 저장·정리 | S3 커미터·임시 prefix·삭제/멀티파트 정리 범위 대기. Bronze는 읽기 전용 |
| 검증 | 고정 입력과 기대 건수·금액·완료 상태 필요. 기존 합성 시험은 실제 업무 검증을 대신하지 않음 |
| Glue·Athena | 스키마·파티션·완료 실행 선택·테이블/뷰 공개 방식 필요. current.json 갱신만으로 Athena 대상이 바뀌지 않음 |

Spark 최초 용량은 전용 t3a.large 한 대분(2 CPU·8GiB), Driver 1개·Executor 초기/최소 1개·최대 2개다. 기존 합성 시험은 자동 증감 동작 확인이며 업무 크기·성능 보장이 아니다. 일 없을 때 노드가 없어지는 구성으로 준비했고 현재 노드를 미리 올리지 않는다.

## 다른 팀 작업과 연결할 항목

- #54 조사 실행/Bedrock, #62 이미지 빌드, #64 판정·조사 DAG, #66 승인 백엔드, #67 Gold A가 열린 상태다. 이는 위 Git 조회 시점 기준이다.
- 후속 읽기 전용 AWS 조회에서 gold_b 기존 표 5개, agent 표 0개, 두 에이전트 ECR 이미지 0개, AIRFLOW_AGENT_CONFIG 미연결, 조사 역할 Bedrock 정책 미적용을 확인했다. #53 DDL은 main에 머지됐지만 업무 표 4개·뷰 배포와 실제 첫 쓰기 시험은 남아 있다. 동일 형식의 격리 표 INSERT/SELECT는 이전에 성공했다.
- 모델은 `jp.anthropic.claude-haiku-4-5-20251001-v1:0`으로 확정됐다. Nova는 제외하며 해당 프로필·조회한 목적지 ARN만 investigation-agent 역할에 연결할 예정이다. 이 공유에는 권한 활성화를 포함하지 않는다.
- #54 검토에서 조사 전부 ERROR여도 프로세스 exit 0으로 끝나는 동작을 가짜 모델로 재현했다. 수정 요청 권장 항목이며 이 인프라 묶음에서 앱 코드를 변경하지 않는다. #62·#64 코드 검토와 로컬 검사 통과는 실제 이미지 빌드·클러스터 실행 완료를 뜻하지 않는다.
- 현재 Airflow Git bundle은 main의 `infra/platform/airflow/dags/`를 읽는다. 별도 `agent/dags/` 파일은 추가 bundle 연결 없이 자동으로 읽히지 않는다. 신규 DAG는 기본 paused다.
- #69 공유 ALB 템플릿은 main에 있지만 실제 적용·listener/target/접근 시험은 이번에 확인하지 않았다. 템플릿의 외부 포트는 Dashboard 80, Airflow 8080, Kafka UI 8081이며 과거 논의 포트와 구분한다.
- 업무 SQL·품질 분기·모델 선택·승인 상태 제한은 각 앱 담당 범위다. 인프라는 경로·배포·실행 권한·자원·연결 검증을 맡는다.
- Gold B 담당자의 그림은 Kafka 직접 입력 Spark Streaming과 별도 지연 수집기를 상시 운영하는 설계다. Silver·Gold A 배치와 구분하며 Spark 노드가 항상 0으로 내려간다고 가정하지 않는다. 실행 이미지·checkpoint·자원·배치 확정과 실측 전이며 이번에는 인지 사항만 기록한다.

## 보류 유지

`infra/operations-alerts`(비용·이메일 알림)와 `docs/cicd-preparation`(이전 CI/CD 초안)은 이번 공유 대상 실행 코드에 합치지 않는다. Argo CD 설치와 앱 자동 배포 활성화도 구분한다. 새 노드·외부 알림·업무 DAG 실행·Terraform/Helm apply·자동 머지를 이번 공유 절차에 포함하지 않는다.

## 이번 공유 준비의 확인 결과

- 여섯 브랜치의 main 대비 추가 파일과 비밀값 패턴을 검사했고 `.cache`·local tfvars·state/plan 포함을 거부하는 검사를 통과했다. 패턴 검사는 모든 비밀 부재의 보증은 아니므로 초안 검토에서 파일을 함께 확인한다.
- 여섯 원본 `git diff --check` 통과. 이후 새 공유 브랜치에서 통합했으며 원본 브랜치와 main은 보존했다.
- Spark Python 회귀 검사 20개 통과. 기존 클라우드 시험·Terraform/Helm 검증 이력은 각 작업 기록을 참조한다. 이번에는 전체 클라우드 시험을 반복하지 않았다.
- AWS 변경·이미지 push·새 노드·테스트 데이터 생성 없음. 공유 대상은 원본 여섯 개가 아니라 새 통합 브랜치 세 개와 초안 PR 세 개다. PR 승인·머지는 팀원이 수행한다.
