# 공통 배포 설정 Git 공유

상태: 공통 설정 분리 완료·최신 main 통합 검증 중

## 사용자 결정과 범위

2026-10-21 사용자는 계정 ID·SG ID·일반 ARN·bucket 이름·운영 설정을 Git으로 관리하고 개인 IP·이메일·인증 비밀만 분리하기로 했다. 이전 계정 ID 비공개 규칙을 이 범위에서 갱신한다. 기존 AWS 배포값을 바꾸지 않고 공통 설정 브랜치를 게시했다. 2026-10-22 사용자가 최신 인프라와의 호환성을 확인한 뒤 PR 생성·머지를 요청했다. 자동 apply나 자체 승인 리뷰는 추가하지 않는다.

## 구현

- 기존 로컬 입력 11개를 공유 `deployment.auto.tfvars.json`과 개인 override로 분리한다. EKS의 public_access_cidrs, 알림 email_recipients만 개인 파일에 남기고 나머지 로컬 파일은 기존 명령 호환을 위해 빈 객체로 유지한다.
- 기존 backend 11개는 bucket/region만 포함함을 검토하고 같은 파일명으로 추적한다. state key나 backend 연결은 바꾸지 않는다.
- 보류 operations-alerts는 설정 공유만 하고 배포하지 않는다. 대체된 athena-query-base와 Helm 비공개 runtime은 범위에서 제외한다.
- 공통 규칙·실행 안내·기존 로컬 운영 도구의 입력 로더를 새 방식에 맞춘다. 기존 로컬 파일 원본은 Git 제외 백업에 보관한다.

## 완료 확인

- 분리 전 입력 = 공유 입력 + 개인 override임을 11개 파일 모두 비교한다.
- 새 추적 파일에 원본 개인 IP·이메일·자격증명이 없고 개인 override·백업·state·plan은 계속 Git 제외인지 검사한다.
- Terraform fmt/validate/mock을 AWS 인증 없는 격리 환경에서 확인한다.
- RDS 실제 읽기 전용 plan이 변경 없음인지 확인한다. AWS apply는 실행하지 않는다.

## 작업 결과

공통 auto tfvars 11개와 backend 위치 파일 11개를 추적하도록 분리했다. EKS 개인 공인 IP·알림 이메일은 로컬 override에만 남고 나머지 개인 파일은 빈 객체다. 기존 원본과 현재 공유+개인 입력의 선언된 값 11개를 모두 대조해 같음을 확인했다. network의 미사용 state_bucket 중복 1개만 tfvars에서 제거했고 실제 backend bucket은 보존했다.

신규 공유 파일의 실제 개인정보·인증 키 검사를 통과했고 로컬 override·백업·비밀번호 파일·state·plan 8개 경로가 계속 Git 제외됨을 확인했다. backend HCL 11개도 bucket/region 외 입력이 없는지 파싱했다. CI snapshot이 공통 auto 파일은 포함하고 개인 JSON은 제외하도록 기존 회귀 검사를 강화해 검사기 테스트 9건을 통과했다.

전체 격리 Terraform 검사 root 13개·mock suite 11개/plan 55건을 통과했다. 검사에서 발견한 미사용 network 변수 정리 후 해당 스택 validate도 경고 없이 재확인했다. source가 아직 main에 없는 Gold B/개발 접근/알림 스택은 공유 입력만 포함하며 관련 선행 브랜치를 반영해야 한다. 보류 스택을 배포하지 않았다.

실제 RDS 읽기 전용 plan은 명시적인 로컬 var-file 없이 공유 auto 파일만 자동 로드해 변경 없음이었다. 기존 두 database_clients와 논리 복제 설정도 공유 입력에 유지했다. 이 작업에서 AWS apply·backend 이전·state 변경·이미지 실행은 하지 않았다. 개인정보 백업은 .cache/tfvars-split-before-20261021, 입력 비교 결과는 .cache/tfvars-split-verification.json, RDS 검증은 .cache/rds-shared-input-verification.json에 보관한다. 과거 일회성 로컬 스크립트는 전체 입력을 개인 파일에서 직접 읽을 수 있어 재사용 전 로더를 확인한다.

2026-10-22 머지 검토: #40·#50·#41·#49가 반영된 main을 통합했고 README·브랜치 목록의 추가 내용을 모두 보존했다. 누락된 workload-access backend 위치 파일은 기존 초기화된 backend의 bucket·region·고유 key를 대조한 뒤 보완했다. 공유 backend 위치 파일은 총 12개이며 state key는 변경하지 않았다. 현재 열린 #56 ECS simulator PR은 별도 스택을 추가하며 공유 JSON/backend 파일과 변경 경로가 겹치지 않는다. 브랜치 목록·README는 후속 통합 시 양쪽 추가 내용을 보존한다.

실제 읽기 전용 plan 비교에서 RDS·Gold B·agent 개발 접근·network·compute는 변경 없음이었다. EKS는 기존 main의 audit 비활성화 코드와 실제 활성 상태 사이 enabled_cluster_log_types 차이만 확인했다. 이번 변경은 EKS 소스나 audit 상태를 수정하지 않는다. audit 재활성화 브랜치 반영 없이 EKS를 apply하면 다시 꺼질 수 있으므로 별도 보류 사항으로 유지한다. 검사 결과는 .cache/shared-config-plan-review.json에 보관한다.
