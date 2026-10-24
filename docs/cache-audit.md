# 로컬 캐시 용량과 정리 대상

기준: 2026-10-23. 이 문서는 분류 결과이며 이번 조사에서 파일·Docker 이미지·브랜치·AWS 자원을 삭제하지 않았다.

## 왜 많아졌나

테스트마다 소스 복사본과 Terraform 초기화 디렉터리를 따로 만들면서 같은 provider 실행 파일을 반복 내려받았다. 또한 .cache 안에 실제 Git worktree와 접속 도구·검증 기록도 함께 보관했다. 종료한 테스트의 임시 폴더를 정리하지 않은 것이 주요 원인이다.

읽을 수 있는 .cache 파일 크기 합계는 34.64GB(32.26GiB), 파일 약 25,823개다. Terraform provider 파일은 52개·30.83GB로 전체 약 89%다. 실제 디스크 회수량을 확정한 값은 아니며 파일 크기 합계다. inode/하드링크 식별 정보가 제공되지 않아 중복 디스크 할당은 검증하지 못했다. 권한이 없어 읽지 못한 임시 폴더 2개는 합계에서 제외했다. 인증값·업무 데이터 내용은 조사하지 않았다.

## 먼저 정리할 후보

| 분류 | 폴더 | 파일 크기 합계 | 확인한 근거 |
|---|---|---:|---|
| 종료된 Terraform 검사 | share-tf-data-* 2개, share-tf-pipelines-* 3개, spark-terraform-check-* 2개, share-tf-spark-* 1개 | 20.38GB | init/validate/test 결과 로그가 있고 Git worktree가 아님. 과거 실패한 중간 시도도 포함하되 후속 통과 기록과 구분 |
| 예전 mock 실행 환경 | agent-data-write-mock, eks-audit-restore-mock, agent-development-mock | 2.56GB | 별도 provider 및 모듈 복사본. 현재 Terraform 프로세스 없음 |
| 재다운로드 가능한 보안 DB | connect-security/trivy-cache | 3.21GB | 스캔 DB 캐시이며 프로젝트 작업 코드·AWS 데이터가 아님 |
| 합계 | 위 12개 임시 폴더 | 약 26.15GB | 로그/결과를 작게 보존한 후 정리할 1차 후보 |

정리 전에 tests-test.log 등 결과 로그와 이 조사 기록을 작은 보관 폴더로 복사한다. 일부 과거 검사에는 실패 이력이 있으므로 “전부 성공한 폴더”로 뭉개지 않는다. mock 환경 및 스캔 DB는 필요하면 다시 만들거나 내려받을 수 있다.

삭제 시에는 확정한 절대 경로가 workspace/.cache 안인지 다시 검증하고, 와일드카드로 .cache 전체를 지우지 않는다. 실제 worktree나 공유 코드 저장소에 해당하는 경로는 제외한다. 현재 생성한 후보 manifest도 검토용이며 삭제 명령은 아니다.

## 보존할 것

| 대상 | 이유 |
|---|---|
| silver-gold-a-connections | 실제 Spark·ECR·권한 적용 코드와 미게시 로컬 커밋. 약 3.48GB 중 대부분 provider지만 worktree 전체는 임시 검사가 아님 |
| agent-bedrock-catalog | Bedrock·#53·Airflow 연결 최신 코드·미게시 기록. 약 1.77GB |
| incident-readiness | 현재 infra/grafana-plugin-recovery worktree이며 알림·복구 후속이 남음. 약 1.77GB |
| 루트의 Gold B 이미지 변경 | 사용자 요청으로 보류한 미커밋 변경. 캐시 정리 대상으로 취급하지 않음 |
| share-provider-cache | 공용 provider 캐시 약 0.91GB. 앞으로 중복 다운로드를 줄이는 용도로 활용 가능 |
| 최신 접속 설정·도구 | kubeconfig, Helm, 현재 쓰는 Python 환경과 운영 helper. 테스트 결과/TF plan/실제 values에는 민감값이 있을 수 있어 Git 제외 유지 |
| 최신 검증 요약 | 적용 자원·시험 데이터 정리·이미지 digest 및 실행 결과 기록. 대형 실행 파일과 구분해 보관 |

작업 worktree의 .terraform provider도 재다운로드 가능하지만 이번 1차 정리 후보에는 넣지 않았다. backend 메타데이터와 실제 작업 소스를 함께 삭제하지 않도록 별도 검토한다.

## 끝난 리뷰용 worktree

pr82-review, pr-infra-merge-review, kafka-retention-only는 모두 clean이며 해당 커밋이 origin/main 이력에 포함돼 있다. 필요 기록을 보관한 뒤 git worktree remove로 정리할 수 있다. 세 폴더 합계는 약 28MB로 주요 용량 원인은 아니다. 브랜치 자체를 자동 삭제하거나 다른 활성 worktree를 제거하지 않는다.

## Docker는 별도

Docker 전체 집계는 이미지 52개·57.51GB, 빌드 캐시 47.08GB다. reclaimable 표시는 각각 42.46GB와 19.98GB지만 공유 레이어 등이 있어 합산 회수량으로 보지 않는다. 다른 프로젝트 이미지·볼륨도 섞여 있으므로 프로젝트 .cache 용량과도 구분한다.

기본 이미지 및 #82 합성 검사는 끝났고 기본 이미지는 ECR에 발행돼 있다. 반면 보류한 Gold B 호환 이미지와 다른 수업/프로젝트 이미지가 함께 있어 Docker 전체 prune을 실행하지 않는다. 다음에 정리한다면 종료된 이 프로젝트 시험 이미지/빌드 기록을 식별한 후 대상별로 처리한다.

## 완료한 시험과 남은 시험

| 이미 종료한 시험 | 아직 남은 검증 |
|---|---|
| Terraform 구조·mock·각 스택 plan/적용 후 drift 검사 | Gold A/B 동시 자원 측정·장애 복구 |
| #82 리뷰 및 Spark 기본 이미지 버전/패키지/JAR·합성 계산, 과거 인프라 합성 Spark 검증 | Silver·Gold A 실제 업무 EKS/S3 실행·Athena 공개 |
| 실제 판정 ServiceAccount의 #53 첫 INSERT/조회, 시험 행·파일·Pod 정리 | 판정·조사 이미지 전체 실행·Bedrock 응답·5분 주기 |
| agent DAG import 및 실제 등록/paused/실행 이력 0개 확인 | Gold B 상시 ingest/collector 배포 및 재처리 연결 |
| Grafana 플러그인 복구·실제 지표 쿼리, 이메일 수신 확인 | 승인 화면부터 재처리·재판정까지 전체 연결 |

완료된 테스트 캐시를 지우는 것과 AWS의 업무 데이터를 지우는 것은 다른 작업이다. 이번 분류는 로컬 파일 및 Docker 현황 조사에 한정한다.
