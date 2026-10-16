# 로컬 검증

Helm lint/template, 고정된 Strimzi 1.3.0 공식 CRD의 OpenAPI 스키마, 기본 비활성화, 잘못된 입력 거부, ACL/스토리지/운영자 연결을 검증한다. 최초 실행은 checksum이 고정된 공식 CRD와 운영자 chart를 `.cache/kafka-verify/`로 내려받는다. 이후 캐시만으로 실행할 수 있다. AWS나 Kubernetes API를 호출하지 않는다.

CDC 실제 토픽/리소스 이름 분리, 선택적 JMX ConfigMap 참조·lag exporter, 예약된 내부 토픽 resourceName과 profile/복제 수 조합을 포함한 잘못된 입력 25개 거부 및 standard의 두 AZ 배치 조건과 scrape 예시의 YAML/대상 선택도 확인한다. single-node 후보의 RF/min ISR·업무/내부 토픽·1536/1024 MiB 설정·운영자 포함 memory 예산·프로필 단독 비활성도 검증한다. 실제 agent/lag 노출과 축소 자원에서의 CDC/재시작 동작은 별도 [로컬 smoke 검사](../local-smoke/README.md)에서 확인한다.

저장소 루트에서 Python 3.12와 Helm 3를 사용한다:

```powershell
python -m venv .cache/kafka-venv
.cache/kafka-venv/Scripts/python.exe -m pip install -r infra/platform/kafka/verify/requirements.txt
.cache/kafka-venv/Scripts/python.exe infra/platform/kafka/verify/check.py --helm <helm.exe 경로>
```

CRD의 Kubernetes CEL 검증·admission·권한·실제 scheduling·영구 볼륨 연결·플러그인 로딩은 실제 클러스터에서 별도 확인한다. 로컬 스키마 검증 통과는 실행 성공을 의미하지 않는다. [인프라 workflow](../../../../.github/workflows/infra-checks.yml)의 kafka-helm job에 연결했으며 실제 GitHub 실행은 미확인이다.
