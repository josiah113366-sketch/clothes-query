# 허용 IP 제한 공유 ALB (dashboard / Airflow / Kafka UI)

EKS Auto Mode의 `eks.amazonaws.com/alb`로 internet-facing ALB 1개를 만들고, 허용 IP만 접속하게 제한한다. [ingress.yaml](ingress.yaml)은 구조만 담은 템플릿이다.

## 현재 구성 (임시: 도메인·인증서 없음, HTTP)
ALB 기본 DNS 주소(`<이름>.ap-northeast-1.elb.amazonaws.com`)로 접속하고 포트로 서비스를 나눈다. 숫자 IP로는 접속하지 않는다(ALB의 IP는 여러 개이고 바뀐다).

| 주소 | 서비스 |
|---|---|
| `http://<ALB 주소>:80` | dashboard |
| `http://<ALB 주소>:8080` | Airflow |
| `http://<ALB 주소>:8081` | Kafka UI |

**주의: HTTP라서 비밀번호(대시보드 로그인, Airflow)가 암호화되지 않고 인터넷을 지난다.** 허용 IP는 다른 사람의 접속은 막지만 중간 구간 도청은 막지 못한다. 시험 단계에서만 쓰고, 운영 전에 도메인과 ACM 인증서로 HTTPS(443) + host 분기로 바꾼다. 대시보드의 `local` 로그인을 운영에 쓰려면 HTTPS가 선행 조건이다.

## 정해야 하는 값 (공개 파일에 쓰지 않는다)
- 허용 CIDR(팀 네트워크의 공인 IP/대역). 필수. 접속 위치가 여러 곳이면 모두 넣고, 유동 IP면 바뀔 때마다 갱신한다. Kafka UI는 `AUTH_TYPE=DISABLED`, Airflow는 개발용 Simple Auth라 대역 제한 없이 열지 않는다.

`ingress.yaml`의 `<ALLOWED_CIDR>`는 공개 repo에 실제 IP를 남기지 않으려고 비워 둔다. 파일을 따로 복사하지 않고 apply할 때 치환한다(아래). 포트·경로 등은 `ingress.yaml`만 고치면 된다.

## 적용 순서
1. namespace 라벨: `kubectl label ns airflow kafka dashboard clothes-query/ingress=shared` (IngressClassParams가 이 라벨이 있는 namespace만 받는다)
2. 허용 IP를 치환해서 검증 후 apply (PowerShell)
   ```powershell
   $cidr = "<내 공인 IP>/32"
   (Get-Content ingress.yaml -Raw) -replace '<ALLOWED_CIDR>', $cidr | kubectl apply --dry-run=server -f -
   (Get-Content ingress.yaml -Raw) -replace '<ALLOWED_CIDR>', $cidr | kubectl apply -f -
   ```
   bash라면 `sed "s#<ALLOWED_CIDR>#$CIDR#" ingress.yaml | kubectl apply -f -`
3. `kubectl get ingress -A`의 ADDRESS(ALB 기본 주소)로 접속
4. 허용 IP 안/밖에서 각각 접속해 보고(밖에서는 막혀야 한다), 세 target group이 healthy인지 확인

## 알아둘 것
- Service는 세 곳 모두 ClusterIP, target type은 `ip`라 Pod IP로 직접 연결한다.
- 대시보드의 namespace·Service 이름·포트(8501)는 배포 작업(`infra/platform/dashboard/`)에서 확정되면 맞춘다.
- 포트를 바꾸면 `ingress.yaml`을 고치고 위 명령으로 다시 apply한다. 반영이 안 되면 `kubectl get ingress -A -o yaml | grep listen-ports`로 클러스터 값을 확인한다.
- 한 ALB 그룹에서 Ingress마다 다른 `listen-ports`를 쓰는 구성과 헬스체크 경로(Airflow `/api/v2/monitor/health`, Kafka UI `/actuator/health`, Streamlit `/_stcore/health`)는 실제로 확인하지 않았다. 배포 후 listener·target 상태로 검증한다.
- Kafka 브로커 외부 LoadBalancer·평문 listener와 Airflow API 내부 주소는 계속 공개하지 않는다. Airflow 승인 백엔드는 클러스터 내부 주소를 쓴다.
- ALB는 기존 WEB/WAS용(`infra/modules/apps`) ALB와 별개다. 같은 ALB를 Terraform과 Ingress 양쪽에서 관리하지 않는다.
