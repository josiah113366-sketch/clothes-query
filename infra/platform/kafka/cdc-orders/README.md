# 업무 CDC 적용 안내 (sim/cdc-orders)

`RDS → Debezium → Kafka(EKS) → S3 Sink → S3 bronze/` 를 업무 토픽 5개로 띄우는 순서다. 작업 기록과 확정값은 [작업 지시서](../../../../docs/tasks/sim-cdc-orders.md)를 따른다.

**사람이 실행한다.** Claude는 이 문서와 파일을 만들고 정적 검사만 한다. 명령은 Windows PowerShell, 레포 루트 기준이다. **`aws` 명령에는 `--region ap-northeast-1`을 붙인다**(CLI 기본 리전이 다르면 다른 리전에 만들어진다). 비밀값(DB 비밀번호, RDS 주소, 계정 ID)은 이 문서·명령행·Git에 남기지 않는다.

## 이 폴더

| 파일 | 내용 |
|---|---|
| `rds.tfvars.example` | RDS 보안 그룹에 EKS(Connect)의 5432 접속 허용 |
| `network.tfvars.example` | S3 Gateway Endpoint 정책에 `s3:AbortMultipartUpload` |
| `workload-access.tfvars.example` | Connect ServiceAccount → `bronze/` 만 읽기·쓰기 하는 Pod Identity 역할 |

세 파일 모두 **비공개 `deployment.local.tfvars`에 합쳐 넣는** 값이다. 파일을 통째로 바꾸지 않는다. 비공개 입력과 `deployment.backend.hcl`이 없으면 인프라 담당자에게 받거나 담당자가 적용한다.

함께 쓰는 파일: `../cdc-orders-values.yaml`(토픽·Connect·Kafka UI), `../runtime.local.yaml`(Git 제외, Connect 이미지 digest), `connectors/cdc-prepare.sql`, `connectors/cdc-source.yaml`, `connectors/bronze-s3-sink.yaml`.

## 0. 시작 전 확인

```powershell
$env:KUBECONFIG = "$PWD\.cache\eks-kubeconfig.private"
kubectl get kafka,kafkanodepool,kafkatopic,kafkauser,kafkaconnect,pod -n kafka
helm list -n kafka
helm get values cq-kafka -n kafka
kubectl get nodes
kubectl describe node | Select-String -Context 0,8 "Allocated resources"
```

- 브로커 1대 Ready, 토픽은 `infra-smoke`뿐, KafkaConnect 없음.
- `helm get values`에 `single-node-values.yaml` + `measurement-values.yaml` 말고 다른 값이 있으면 멈추고 확인한다(upgrade 때 빠진다).
- 노드 CPU 요청량 합계에 **1.35 vCPU 이상 여유가 없으면** 멈춘다. Auto Mode는 자리가 없으면 노드를 새로 띄운다(비용 증가).

## 1. Terraform (network → rds → workload-access)

각 스택 폴더에서 예시 값을 비공개 tfvars에 합친 뒤 실행한다.

```powershell
terraform init "-backend-config=deployment.backend.hcl" "-lockfile=readonly"
terraform plan -input=false "-var-file=deployment.local.tfvars.json" "-out=$env:TEMP\<스택>.tfplan"
terraform apply "$env:TEMP\<스택>.tfplan"
```

- 비공개 입력은 JSON이면 이름이 `deployment.local.tfvars.json`이어야 한다(`.tfvars`는 HCL로 읽는다). 받은 그대로 먼저 plan해서 `No changes`를 확인한 뒤 예시 값을 합친다.
- plan 파일은 Git 제외 대상이 아니고 민감한 값이 들어갈 수 있다. **레포 밖(`$env:TEMP`)에 저장한다.**
- 순서는 network → rds → workload-access. workload-access는 network의 S3 endpoint 허용 작업을 읽어 검사하므로 network를 먼저 apply한다.

- PowerShell은 `-`로 시작하는 인자 안의 `.`에서 인자를 나눈다. **따옴표를 꼭 붙인다**(없으면 `Too many command line arguments`).
- `deployment.backend.hcl`(Git 제외)은 두 줄이다: `bucket = "clothes-query-tfstate-<계정ID>"`, `region = "ap-northeast-1"`. 키(state 경로)는 각 스택의 `backend.tf`에 있다.
- **비공개 입력 없이 plan하지 않는다.** 기본값으로 계산되어 rds에서 논리 복제 parameter group을 떼는 변경이 나온다.

- plan에 **삭제(destroy)나 교체(replace)가 하나라도 있으면 apply하지 않는다.**
- 기대하는 변경: network는 endpoint 정책 변경 1, rds는 보안 그룹 규칙 생성 1, workload-access는 역할·정책·Pod Identity association 생성.
- rds plan에 `parameter_group_name`이나 인스턴스 변경이 보이면 멈춘다(논리 복제는 이미 켜져 있다).

## 2. DB: CDC 계정과 publication

1. 비밀번호를 만들어 Secrets Manager에 저장한다(한 번만).

   ```powershell
   $pw = aws secretsmanager get-random-password --password-length 32 --exclude-punctuation --query RandomPassword --output text --region ap-northeast-1
   $tmp = New-TemporaryFile
   @{ username = "clothes_cdc"; password = $pw } | ConvertTo-Json -Compress | Set-Content -NoNewline $tmp
   aws secretsmanager create-secret --name clothes-query-dev-cdc-db --secret-string "file://$tmp" --region ap-northeast-1
   Remove-Item $tmp; Remove-Variable pw
   ```

2. 마스터 계정으로 **`postgres` DB에 접속해** `connectors/cdc-prepare.sql`을 실행한다. RDS의 업무 테이블은 `postgres` DB에 있다(`clothes`는 로컬 Docker의 DB 이름이다). publication은 DB마다 따로라서, 다른 DB에 만들면 Debezium이 `Publication autocreation is disabled`로 실패한다.
   - **psql 15 이상:** 환경 변수 `CDC_DB_PASSWORD`에 위 비밀번호를 넣고 `psql -X "<접속 문자열, sslmode=verify-full>" -f connectors/cdc-prepare.sql`.
   - **DBeaver:** `BEGIN;`부터 `COMMIT;`까지 붙여 넣고 `:'cdc_password'` 자리만 비밀번호 문자열로 바꿔 실행한다. 바꾼 SQL은 저장하지 않는다.
3. 확인: 마지막 두 SELECT가 `clothes_cdc`(연결 한도 3)와 테이블 4개(`members`, `order_items`, `orders`, `payments`)를 보여 준다. `members_archive`가 없어야 한다.

## 3. K8s Secret (`kafka` namespace)

값을 명령행에 쓰지 않도록 임시 폴더 파일을 거쳐 만들고 바로 지운다. **임시 폴더 경로에 한글이 없어야 한다.** Windows 사용자 이름이 한글이면 `$env:TEMP` 경로가 kubectl에 깨져 넘어가 `cannot find the file`이 난다.

```powershell
$cdc = aws secretsmanager get-secret-value --secret-id clothes-query-dev-cdc-db --query SecretString --output text --region ap-northeast-1 | ConvertFrom-Json
$rdsHost = aws rds describe-db-instances --db-instance-identifier clothes-query-dev-rds --query "DBInstances[0].Endpoint.Address" --output text --region ap-northeast-1
$d = New-Item -ItemType Directory -Path ("E:\cdc-tmp-" + [guid]::NewGuid())   # 레포 밖, 한글 없는 경로
Set-Content -NoNewline "$d\hostname" $rdsHost
Set-Content -NoNewline "$d\database" "postgres"   # 업무 테이블이 있는 DB (clothes 아님)
Set-Content -NoNewline "$d\username" $cdc.username
Set-Content -NoNewline "$d\password" $cdc.password
kubectl create secret generic cdc-database -n kafka --from-file="$d\hostname" --from-file="$d\database" --from-file="$d\username" --from-file="$d\password"
Invoke-WebRequest https://truststore.pki.rds.amazonaws.com/ap-northeast-1/ap-northeast-1-bundle.pem -OutFile "$d\bundle.pem"
kubectl create secret generic rds-ca -n kafka --from-file="$d\bundle.pem"
Remove-Item -Recurse -Force $d; Remove-Variable cdc, rdsHost
```

## 4. Helm upgrade (같은 release `cq-kafka`)

`runtime.local.yaml`(Git 제외)에 Connect 이미지 digest가 있어야 한다. 순서가 중요하다.

```powershell
$values = "-f", "infra/platform/kafka/single-node-values.yaml", "-f", "infra/platform/kafka/cdc-orders-values.yaml", "-f", "infra/platform/kafka/runtime.local.yaml"
helm template cq-kafka infra/platform/kafka/chart -n kafka @values > $env:TEMP\cq-new.yaml
helm get manifest cq-kafka -n kafka > $env:TEMP\cq-old.yaml
```

두 파일을 비교해서 **사라지는 것이 `infra-smoke` KafkaTopic과 `infra-smoke-client` KafkaUser뿐**인지 본다. `KafkaNodePool`(디스크)이 바뀌면 멈춘다. Kafka CR은 broker NetworkPolicy 허용 대상(`infra-probe` → `kafka-ui`)과 lag exporter 정규식만 바뀐다.

```powershell
helm upgrade cq-kafka infra/platform/kafka/chart -n kafka @values --wait --timeout 15m
kubectl wait --for=condition=Ready kafkatopic --all -n kafka --timeout=5m
kubectl wait --for=condition=Ready kafkauser --all -n kafka --timeout=5m
kubectl wait --for=condition=Ready kafkaconnect/clothes-query-dev-connect -n kafka --timeout=15m
kubectl get kafkatopic,kafkauser,kafkaconnect,pod,pvc -n kafka
kubectl get nodes
```

- 토픽 9개(업무 5 + heartbeat 1 + Connect 내부 3), 브로커 Pod 재시작 0, PVC 이름 그대로.
- `kubectl get sa clothes-query-dev-connect-connect -n kafka`가 있어야 Pod Identity가 붙는다. Connect Pod가 Terraform apply보다 먼저 떴다면 `kubectl delete pod -n kafka -l strimzi.io/kind=KafkaConnect`로 한 번 다시 띄운다.
- 플러그인 확인: `kubectl get kafkaconnect clothes-query-dev-connect -n kafka -o jsonpath="{.status.connectorPlugins[*].class}"`에 `PostgresConnector`와 `S3SinkConnector`가 보인다.

## 5. 커넥터 등록

```powershell
kubectl apply -f connectors/cdc-source.yaml
kubectl get kafkaconnector cdc-source -n kafka -w
```

회원 snapshot(10만 건)이 끝나면(Kafka UI에서 `members-events` 메시지 100,000건) Sink를 등록한다.

```powershell
kubectl apply -f connectors/bronze-s3-sink.yaml
kubectl get kafkaconnector -n kafka
```

## Kafka UI

```powershell
kubectl port-forward -n kafka svc/kafka-ui 8080:8080
```

브라우저에서 `http://localhost:8080`. 읽기 전용이다(토픽 삭제·메시지 쓰기 불가). 외부에 열지 않는다.

## 되돌리기

- 커넥터: `kubectl delete kafkaconnector bronze-s3-sink cdc-source -n kafka`. slot은 남는다. **slot을 남긴 채 오래 두지 않는다**(WAL이 쌓인다). 다시 쓰지 않으면 `cdc-prepare.sql` 아래쪽 되돌리기 SQL로 slot부터 지운다.
- Helm: `helm rollback`이나 `enabled=false`를 단순 롤백으로 쓰지 않는다(토픽과 offset이 지워진다). 무엇을 지울지 먼저 정한다.
- S3 `bronze/` 객체는 자동으로 지우지 않는다.
