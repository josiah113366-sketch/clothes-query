# api/ — 업무 API (WAS)

시뮬레이터가 보낸 **가입·주문·결제·상태 변경을 검증해 RDS(`postgres` DB)에 저장**하고, **클릭을 Kafka `clickstream`에 발행**하는 FastAPI 앱이다. EKS `api` namespace에 Pod로 뜨고, VPC 안에서만 닿는 **내부 ALB(HTTP 80)** 뒤에 있다. Pod는 **API 전용 노드 풀**(`clothes-query-dev-api`, t3a.medium 1대, taint로 API만)에 올라가며, Kafka가 있는 기존 노드 풀은 건드리지 않는다. 설계는 `docs/design/api.md`, 작업 기록은 `docs/tasks/api-mvp.md`.

```
시뮬레이터 ─HTTP─▶ 내부 ALB ─▶ api Pod ─▶ RDS postgres DB ─(Debezium)─▶ Kafka ─▶ S3 bronze/
                                    └─▶ Kafka clickstream ─────────────────────▶ S3 bronze/clickstream/
```

**얇은 API**다. ID·시각·결제 결과는 시뮬레이터가 정해 보내고, API는 검증하고 저장·발행만 한다.

## 엔드포인트

| 메서드·경로 | 하는 일 | 주요 응답 |
|---|---|---|
| `POST /v1/members` | 가입 1건 (`status=ACTIVE`, `created_at`은 DB) | 201 / 200 같은 내용 / 409 `ID_CONFLICT`·`PHONE_TAKEN`·`EMAIL_TAKEN` / 422 |
| `GET /v1/members/signup-count?from=` | `signup_at >= from`인 회원 수 (`member live` 시작 위치) | 200 |
| `GET /v1/members/active?cursor=` | 활성 회원 `member_id` (1만 건씩), 첫 페이지에 `changes_cursor` | 200 |
| `GET /v1/members/changes?after=` | 커서 이후 가입한 회원 (10초 겹쳐 읽음, 최대 5천 건) | 200 |
| `GET /v1/catalog?cursor=` | 상품 `article_id`, `price` (1만 건씩) | 200 |
| `POST /v1/orders` | 주문 + 항목 한 트랜잭션. 회원 `ACTIVE`·합계·중복 상품 검사 | 201 / 200 / 404 `MEMBER_NOT_FOUND` / 409 `MEMBER_NOT_ACTIVE`·`ID_CONFLICT` / 422 |
| `POST /v1/orders/{order_id}/payments` | 결제 시도 1건 | 201 / 200 / 404 / 409 / 422 |
| `PATCH /v1/orders/{order_id}` | 상태 전이 (같은 상태 재요청은 200) | 200 / 404 / 409 `INVALID_TRANSITION` / 422 |
| `POST /v1/events/clicks` | 클릭 최대 500건 → `clickstream` (키 `session_id`) | 202 `{accepted, failed}` / 413 |
| `GET /healthz`, `/readyz`, `/metrics` | 살아 있음 / DB·Kafka 준비 / Prometheus | 200 / 503 |

허용 전이: `PLACED → PAID | PAYMENT_FAILED | CANCELLED`, `PAID → SHIPPED | CANCELLED`, `SHIPPED → DELIVERED`, `DELIVERED → REFUNDED`.
오류 응답: `{"error": "<코드>", "detail": "<PII 없는 설명>"}`. DB 연결을 2초 안에 못 받으면 503 `DB_BUSY`.

## 로컬 개발

```bash
cd api
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest                    # 단위 테스트 + Helm chart 렌더
# 로컬 Docker (simulator/docker-compose.yml) 가 떠 있을 때
.venv/bin/pytest -m integration
# 로컬 실행 (로컬 Docker Postgres·Kafka)
DATABASE_URL=postgresql://sim:sim@localhost:5432/clothes KAFKA_BOOTSTRAP=localhost:29092 \
  .venv/bin/uvicorn clothes_api.main:app --port 8000
```

시뮬레이터를 이 API로 돌리기: `simulator/README.md`의 "업무 API로 쓰기".

## 환경 변수

| 변수 | 기본 | 설명 |
|---|---|---|
| `DATABASE_URL` | (없음) | 없으면 libpq 표준 변수(`PGHOST`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSSLMODE`, `PGSSLROOTCERT`)를 쓴다. EKS는 이 방식 |
| `API_DB_POOL_MIN` / `API_DB_POOL_MAX` / `API_DB_POOL_TIMEOUT` | 1 / 10 / 2초 | DB 연결 풀 |
| `KAFKA_BOOTSTRAP` | (필수) | EKS: `clothes-query-dev-kafka-kafka-bootstrap.kafka.svc:9093` |
| `KAFKA_SECURITY_PROTOCOL`, `KAFKA_SSL_CA_FILE`, `KAFKA_SSL_CERT_FILE`, `KAFKA_SSL_KEY_FILE` | `PLAINTEXT` | EKS는 `SSL`(mTLS) |
| `CLICK_TOPIC` | `clickstream` | |
| `LOG_LEVEL` | `INFO` | 로그는 stdout JSON 한 줄(본문·PII 없음) |

## EKS 배포 (사용자가 실행, Windows PowerShell, 레포 루트)

먼저 관리자 kubeconfig를 쓴다. **새 PowerShell 창마다 다시 설정한다**(없으면 IAM 사용자 권한이라 `forbidden`). 처음 1~7단계는 같은 창에서 한다(`$repo`·`$digest` 등 변수를 이어 쓴다). Windows PowerShell 5.1의 `>`는 UTF-16으로 저장하므로 비교용 파일은 `Set-Content -Encoding utf8`로 쓴다. **`aws` 명령에는 `--region ap-northeast-1`을 붙인다.** 임시 파일은 레포 밖·한글 없는 경로(`E:\…`)에 `[IO.File]::WriteAll*`로 쓰고 바로 지운다(cdc-orders에서 겪은 PowerShell 함정).

```powershell
$env:KUBECONFIG = "$PWD\.cache\eks-admin-kubeconfig.private"
kubectl create namespace api
```

### 1. DB 앱 계정 (DBeaver, 마스터, `postgres` DB)

```powershell
$pw = aws secretsmanager get-random-password --password-length 32 --exclude-punctuation --query RandomPassword --output text --region ap-northeast-1
$tmp = "E:\api-db-" + [guid]::NewGuid() + ".json"
[IO.File]::WriteAllText($tmp, (@{ username = "clothes_app"; password = $pw } | ConvertTo-Json -Compress))
aws secretsmanager create-secret --name clothes-query-dev-api-db --secret-string "file://$tmp" --region ap-northeast-1
Remove-Item $tmp; $pw | Set-Clipboard; Remove-Variable pw
```

`api/deploy/sql/app-account.sql`의 `BEGIN;`~`COMMIT;`을 DBeaver에 붙이고 `:'api_password'` 자리에 클립보드 값을 넣어(따옴표는 남긴다) 실행한다. 확인 쿼리 세 개로 계정(연결 한도 15), 테이블 권한, `members.status` UPDATE(주문 생성의 행 잠금용)를 본다.

### 2. K8s Secret (`api` namespace)

```powershell
$db = aws secretsmanager get-secret-value --secret-id clothes-query-dev-api-db --query SecretString --output text --region ap-northeast-1 | ConvertFrom-Json
$rdsHost = aws rds describe-db-instances --db-instance-identifier clothes-query-dev-rds --query "DBInstances[0].Endpoint.Address" --output text --region ap-northeast-1
$d = New-Item -ItemType Directory -Path ("E:\api-tmp-" + [guid]::NewGuid())
[IO.File]::WriteAllText("$d\host", $rdsHost)
[IO.File]::WriteAllText("$d\database", "postgres")
[IO.File]::WriteAllText("$d\username", $db.username)
[IO.File]::WriteAllText("$d\password", $db.password)
Invoke-WebRequest https://truststore.pki.rds.amazonaws.com/ap-northeast-1/ap-northeast-1-bundle.pem -OutFile "$d\bundle.pem"
kubectl create secret generic api-database -n api --from-file="$d\host" --from-file="$d\database" --from-file="$d\username" --from-file="$d\password"
kubectl create secret generic rds-ca -n api --from-file="$d\bundle.pem"
Remove-Item -Recurse -Force $d; Remove-Variable db, rdsHost, d
kubectl describe secret api-database rds-ca -n api   # password 32 bytes
```

### 3. Kafka 계정 `api` (같은 `cq-kafka` release)

`infra/platform/kafka/cdc-orders-values.yaml`에 KafkaUser `api`(`clickstream` 쓰기만)와 `clientNamespaces: [api]`가 들어 있다.

```powershell
$values = "-f", "infra/platform/kafka/single-node-values.yaml", "-f", "infra/platform/kafka/cdc-orders-values.yaml", "-f", "infra/platform/kafka/runtime.local.yaml"
helm template cq-kafka infra/platform/kafka/chart -n kafka @values | Set-Content -Encoding utf8 E:\cq-new.yaml
helm get manifest cq-kafka -n kafka | Set-Content -Encoding utf8 E:\cq-old.yaml
git diff --no-index E:\cq-old.yaml E:\cq-new.yaml
```

비교해서 **추가: KafkaUser `api`, 변경: Kafka CR listener 허용 대상에 `api` namespace**뿐이어야 한다. 브로커·NodePool이 바뀌면 멈춘다.

```powershell
helm upgrade cq-kafka infra/platform/kafka/chart -n kafka @values --wait --timeout 10m
kubectl wait --for=condition=Ready kafkauser/api -n kafka --timeout=3m
Remove-Item E:\cq-old.yaml, E:\cq-new.yaml
```

### 4. Kafka 인증서 복사 (`kafka` → `api`)

Strimzi는 인증서 Secret을 `kafka` namespace에만 만든다. WAS가 쓰는 세 파일만 꺼내 `api`의 `kafka-client`로 만든다(값은 출력하지 않는다).

```powershell
$u = kubectl get secret api -n kafka -o json | ConvertFrom-Json
$c = kubectl get secret clothes-query-dev-kafka-cluster-ca-cert -n kafka -o json | ConvertFrom-Json
$d = New-Item -ItemType Directory -Path ("E:\kafka-tmp-" + [guid]::NewGuid())
[IO.File]::WriteAllBytes("$d\user.crt", [Convert]::FromBase64String($u.data.'user.crt'))
[IO.File]::WriteAllBytes("$d\user.key", [Convert]::FromBase64String($u.data.'user.key'))
[IO.File]::WriteAllBytes("$d\ca.crt",   [Convert]::FromBase64String($c.data.'ca.crt'))
kubectl create secret generic kafka-client -n api --from-file="$d\ca.crt" --from-file="$d\user.crt" --from-file="$d\user.key"
Remove-Item -Recurse -Force $d; Remove-Variable u, c, d
```

**만료일 확인**(기본 1년, Strimzi가 만료 약 30일 전 갱신):

```powershell
$u = kubectl get secret api -n kafka -o json | ConvertFrom-Json
([System.Security.Cryptography.X509Certificates.X509Certificate2]::new([Convert]::FromBase64String($u.data.'user.crt'))).NotAfter
Remove-Variable u
```

갱신되면 `kafka-client`를 지우고(`kubectl delete secret kafka-client -n api`) 위 복사를 다시 한 뒤 `kubectl rollout restart deploy/api -n api`. 복사본이 옛 인증서면 클릭 발행만 실패하고(지표 `api_kafka_produced_total{result="failed"}`) 주문 저장은 계속된다.

### 5. 이미지 (ECR `clothes-query-dev/was`, IMMUTABLE)

```powershell
$acct = aws sts get-caller-identity --query Account --output text
$repo = "$acct.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/was"
$tag = "api-" + (git rev-parse --short HEAD)
aws ecr get-login-password --region ap-northeast-1 | docker login --username AWS --password-stdin "$acct.dkr.ecr.ap-northeast-1.amazonaws.com"
docker build --platform linux/amd64 -t "${repo}:$tag" api
docker push "${repo}:$tag"
$digest = aws ecr describe-images --repository-name clothes-query-dev/was --image-ids imageTag=$tag --query "imageDetails[0].imageDigest" --output text --region ap-northeast-1
docker logout "$acct.dkr.ecr.ap-northeast-1.amazonaws.com"
```

태그는 덮어쓸 수 없으므로 커밋마다 새 태그다. Helm에는 digest로 넣는다.

### 6. Helm 설치

`api/deploy/chart/runtime.local.yaml`(Git 제외)을 만든다.

```powershell
[IO.File]::WriteAllText("api\deploy\chart\runtime.local.yaml", "image: `"${repo}@$digest`"`ningress:`n  inboundCIDRs: [`"10.70.0.0/16`"]`n")
helm template api api/deploy/chart -n api -f api/deploy/chart/runtime.local.yaml | Set-Content -Encoding utf8 E:\api-render.yaml   # 열어서 확인 후 지운다
helm upgrade --install api api/deploy/chart -n api -f api/deploy/chart/runtime.local.yaml --wait --timeout 5m
kubectl get pod,svc,ingress -n api
kubectl get nodes
```

- `inboundCIDRs`는 처음엔 VPC 대역(`10.70.0.0/16`)이다. `sim/ecs-image`에서 ECS 태스크 대역이 정해지면 좁힌다.
- Ingress `ADDRESS`가 **`internal-`**로 시작해야 한다(내부 ALB). public이면 바로 `helm uninstall api -n api`하고 알린다. ALB가 뜨는 데 2~3분 걸린다.
- 노드는 **2대가 정상**이다: 기존 풀 1대(Kafka 등) + API 전용 풀 1대(t3a.medium). `kubectl get nodes -L karpenter.sh/nodepool`로 풀을 본다. 전용 노드는 Pod가 생기면 1~2분 안에 뜬다. 전용 풀은 CPU 한도 2라 **2대 이상 생기지 않는다**(비용 상한). Kafka 쪽 Pod(`kubectl get pod -n kafka`)는 재시작 0이어야 한다.

### 7. 확인

```powershell
# VPC 안에서 ALB로 /readyz (임시 Pod)
$alb = kubectl get ingress api -n api -o jsonpath="{.status.loadBalancer.ingress[0].hostname}"
kubectl run curl -n api --rm -i --restart=Never --image=curlimages/curl:8.10.1 -- curl -s "http://$alb/readyz"
# 내 PC → API (port-forward)
kubectl port-forward -n api svc/api 8000:80
```

port-forward를 켠 채로 다른 창(WSL)에서 시뮬레이터를 짧게 돌린다(`simulator/README.md` "업무 API로 쓰기"). 주문까지 보려면 `--max-visits`가 아니라 `--duration`으로 끊는다(방문 300은 4초 만에 끝나 예약된 주문·결제가 실행되지 않는다). 주문이 RDS에 들어가고 CDC로 `bronze/orders` 등에, 클릭이 `bronze/clickstream/`에 15분 안에 쌓인다. Kafka UI에서 `clickstream` 메시지 수가 늘어나는지 본다.

## 되돌리기

- API만 내리기: `helm uninstall api -n api` (내부 ALB와 **API 전용 노드 풀·노드도** 지워진다). Secret과 DB 계정은 남는다.
- DB 계정: `api/deploy/sql/app-account.sql` 아래쪽 되돌리기 SQL.
- Kafka 계정: `cdc-orders-values.yaml`에서 `clients`의 `api`와 `clientNamespaces`를 빼고 `cq-kafka` upgrade.
