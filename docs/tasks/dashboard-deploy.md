# 작업 지시서: dashboard/deploy

> 상태: 진행 중 · 브랜치: `dashboard/deploy` · 앞 작업: [dashboard-baseline.md](dashboard-baseline.md)

## 목표

baseline 대시보드를 EKS에 올리고, 팀이 허용 IP에서 접속할 수 있게 한다. 대시보드 이미지 저장소(ECR), 컨테이너 이미지, k8s 배포 파일, 대시보드·Airflow·Kafka UI가 함께 쓰는 ALB 템플릿을 만든다.
실데이터(Athena) 연결, 도메인·HTTPS, 운영용 계정 정책은 하지 않는다.

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `infra/CLAUDE.md`, `infra/DEPLOYMENT_CONFIG.md` (공유 배포 설정 규칙)
- [dashboard-baseline.md](dashboard-baseline.md), `dashboard/README.md`, `dashboard/TODO.md` (E·F 영역)
- `infra/platform/airflow/README.md`, `infra/platform/kafka/README.md` (기존 접근 방침: port-forward)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 외부 접속은 **ALB 기본 DNS 주소 + HTTP + 허용 IP 제한**의 임시 구성이다. 도메인·ACM 인증서가 없고, 서비스는 포트로 나눈다(dashboard 80, Airflow 8080, Kafka UI 8081). 도메인을 정하면 HTTPS + host 분기로 바꾼다.
- ALB는 대시보드·Airflow·Kafka UI가 **하나를 공유**한다(EKS Auto Mode, IngressClass 그룹). 허용 IP는 공개 파일에 쓰지 않고 apply할 때 치환한다.
- 대시보드 로그인은 `AUTH_MODE=local` 고정 계정 3개다. 비밀번호를 **아이디와 같게** 만들 수 있다(`make_test_accounts.py --same-as-id`, 사용자 결정). 보호는 허용 IP와 로그인 실패 잠금뿐이다.
- namespace는 `dashboard`, 파드는 1개(로그인 잠금이 파드별), 데이터는 `DATA_SOURCE=dummy`다.
- 대시보드 ECR 저장소는 기존 `ecr` 스택에 넣지 않고 **별도 `dashboard` 스택**(state 분리)으로 만든다.
- 기존 문서의 "Airflow·Kafka UI는 외부 노출 안 함" 문구는 이 구성에 맞게 고친다. Kafka 브로커 외부 LoadBalancer·평문 listener와 Airflow API 내부 주소는 계속 공개하지 않는다.
- Claude는 **AWS·클러스터에 apply하지 않고, git commit·push·PR도 하지 않는다.** 실행은 사용자가 한다. commit이 필요하면 메시지만 제안한다.
- 코드 주석은 한국어로 자세히 쓴다.

## 시작 전 확인 (Claude가 한다)

- 브랜치가 최신 `main`에서 만들어졌는지, `docs/BRANCHES.md`에 이 브랜치 한 줄이 있는지
- 저장소(`infra/stacks/ecr` 등)의 현재 state·계정이 `deployment.auto.tfvars.json`과 맞는지

## 만드는 것

| 위치 | 내용 |
|---|---|
| `infra/stacks/dashboard/` | ECR 저장소 `clothes-query-dev/dashboard` 하나. 태그 변경 불가·push 스캔·삭제 보호. 별도 state |
| `infra/platform/dashboard/` | `Dockerfile`, `Dockerfile.dockerignore`, `k8s/`(namespace, deployment, service), 배포 순서 `README.md`. 계정 파일은 Secret 마운트, 이미지에는 제외 |
| `infra/platform/ingress/` | 공유 ALB 템플릿 `ingress.yaml`(IngressClassParams, IngressClass, Ingress 3개)과 적용 순서 `README.md` |
| `dashboard/make_test_accounts.py`, `dashboard/README.md` | `--same-as-id` 옵션, 배포 설명을 `local` 기준으로 수정 |
| `infra/README.md`, `infra/stacks/README.md`, `infra/platform/{airflow,kafka}/README.md` | 스택 목록 추가, 외부 노출 문구 수정 |

## 만들지 않는 것

- Athena/S3 읽기용 Pod Identity 역할과 실데이터 조회 → Gold A·B 연결 작업(`dashboard/TODO.md` A·B·F3)
- 도메인, ACM 인증서, HTTPS, Route 53
- 계정 파일·비밀번호·허용 IP·이미지 digest 등 실제 값을 공개 파일에 넣는 것 (digest를 채운 `deployment.yaml`은 사용자가 필요할 때 로컬에서 쓴다)
- replicas 확장, 세션 만료, 개인별 접속 기록
- 실제 AWS apply와 클러스터 배포 (사용자가 직접)

## 작업 순서

1. 시작 전 확인을 하고 계획을 사용자에게 보인다
2. `stacks/dashboard`와 배포 파일을 만든다
3. 사용자가 stack plan(저장소 1개 추가)을 검토해 apply한다
4. 이미지 빌드·push 후 digest를 `deployment.yaml`에 채우고 배포한다
5. 공유 ALB를 적용하고 접속을 확인한다
6. "완료 확인"을 실행하고 결과를 아래에 기록한다

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다. (사용자가 실행하는 항목은 결과를 알려 준다)

- [ ] `terraform fmt -check`, `terraform validate` (`infra/stacks/dashboard`), `infra/checks`의 정적 검사
- [ ] `terraform plan`에 저장소 1개 추가만 나오고 기존 저장소 교체·삭제가 없는지
- [ ] `docker build -f infra/platform/dashboard/Dockerfile ... dashboard/` 성공, 이미지에 `.local/`·`make_test_accounts.py`가 없는지
- [ ] `kubectl apply --dry-run=server` 통과, 파드 Running, `kubectl port-forward`로 로그인 성공
- [ ] ALB 적용 후 허용 IP에서 세 주소(80/8080/8081)가 열리고, 허용 IP 밖에서는 막히는지
- [ ] 세 target group 헬스체크 통과 (경로: Streamlit `/_stcore/health`, Airflow `/api/v2/monitor/health`, Kafka UI `/actuator/health`는 아직 미확인)

## README 갱신

- `infra/platform/dashboard/README.md`, `infra/platform/ingress/README.md`, `infra/stacks/dashboard/README.md`
- `docs/BRANCHES.md` (브랜치 대장에 한 줄)

## 작업 결과 (머지 전에 작성한다. 사람과 AI가 나중에 이 브랜치가 무엇을 했는지 읽는 곳이다)

- **한 줄 요약:** 대시보드 ECR 스택, 이미지·k8s 배포 파일, 허용 IP 제한 공유 ALB 템플릿을 추가했다.
- **무엇을 만들었나:** 위 "만드는 것" 표 참고
- **왜 그렇게 했나:** 도메인이 없어 ALB 기본 주소와 포트 분리를 택했고, 허용 IP가 유일한 접속 보호라 공개 파일에 값을 두지 않고 apply 때 치환한다. ECR은 다른 스택의 state를 건드리지 않도록 별도 스택으로 분리했다.
- **입력과 출력:** 입력은 `expected_account_id`(공유 파일), 이미지 digest, 허용 CIDR(apply 때), 계정 Secret `dashboard-accounts`. 출력은 ECR 저장소 URL과 ALB 주소.
- **확인한 결과:** (머지 전에 "완료 확인" 결과로 채운다. 세션 중에는 코드·문서만 작성했고 terraform·docker·kubectl은 실행하지 못했다.)
- **알려진 한계·남은 일:**
  - HTTP라서 비밀번호가 암호화되지 않고 인터넷을 지난다. 운영 전에 도메인과 HTTPS로 바꾼다.
  - 비밀번호를 아이디와 같게 쓰면 접속 보호는 허용 IP와 로그인 잠금뿐이다. 허용 IP가 유동이면 바뀔 때마다 갱신한다.
  - 한 ALB 그룹에서 Ingress마다 다른 `listen-ports`를 쓰는 구성과 헬스체크 경로는 실제로 확인하지 않았다.
  - 이 브랜치는 `dashboard/`(`make_test_accounts.py`, README)와 `infra/`를 함께 바꾼다. "PR 하나에 영역 하나" 규칙의 예외다. 파일 하나(`--same-as-id` 옵션)를 위해 브랜치를 따로 여는 부담이 커서 사용자가 한 PR로 묶기로 했다(2026-10-23).
  - 실데이터 연결과 Pod Identity는 다음 작업이다.
