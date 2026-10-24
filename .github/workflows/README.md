# 인프라 자동 검사

모니터링 Helm 렌더·격리 범위, Prometheus 설정·경보 동작 검사도 포함한다. 고정 Prometheus 이미지로 검사하며 AWS 배포 권한은 사용하지 않는다. [모니터링 안내](../../infra/platform/monitoring/README.md)를 따른다.

[infra-checks.yml](infra-checks.yml)은 Terraform/mock, Kafka Helm, 일회성 로컬 TLS/CDC/보존/지표, Connect 이미지 취약점 보고를 실행한다. AWS/클러스터 인증·배포·이미지 push는 없다. 실행 방법과 한계는 [검사 안내](../../infra/checks/README.md)를 따른다.

`runtime-preparation` 작업은 Gold B 계정·S3/Kafka 권한·Spark 배치 설정, Airflow 업무 설정의 기존 값 보존과 이미지 digest 검증, Bronze 지연 수집기 배치 설정을 검사한다. 기존 단위 검사를 GitHub에서도 실행하며 실제 AWS·Kafka·Airflow에는 접속하지 않는다. 세 검사 묶음은 각각 별도 Python 프로세스로 실행해 모듈 이름 충돌을 피한다.

```sh
python -m pip install -r infra/platform/spark/requirements.txt
python -m unittest discover -s infra/platform/gold-b -p 'test_*.py' -v
python -m unittest discover -s infra/platform/airflow -p 'test_*.py' -v
python -m unittest discover -s infra/platform/bronze-lag-collector -p 'test_*.py' -v
```

앱 업무 계산·이미지 빌드 CI와 실제 클러스터 연결 검증은 이 작업에 포함되지 않는다.
