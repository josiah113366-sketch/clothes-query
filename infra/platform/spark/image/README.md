# Spark 기본 이미지 — 빌드 전 준비

사용자 선택은 Spark **4.2.0**이다. 기본 후보는 Docker Official Image의 `spark:4.2.0-scala2.13-java21-python3-ubuntu`(amd64)다. Spark 소스 POM의 Hadoop 3.5.0에 맞춰 S3A를 준비하고, Kafka SQL 커넥터는 Spark 4.2.0/Scala 2.13, PostgreSQL JDBC는 42.7.14로 고정한다. 업무 코드·인증 정보·실제 데이터 경로는 포함하지 않는다.

빌드한 기본 이미지에서 `python3 --version`으로 확인한 Python은 **3.10.12**다. 후속 EKS 합성 계산과 Executor 1→2→1 동적 할당도 통과했다. 실제 업무 패키지 호환성·저장소 접속·업무 데이터 성능까지 검증한 것은 아니다.

## 현재 검증 수준

2026-10-22 사용자 승인에 따라 짧은 합성 시험을 진행했다. Spark·Maven 공식 이미지 digest를 확인해 Dockerfile에 고정했고 기본 이미지 빌드 및 네트워크를 끈 로컬 Spark 계산·S3A/AWS 자격증명 provider/PostgreSQL/Kafka 클래스 로딩에 성공했다. 앞선 HTTP 401은 registry 인증 scope의 경로 구분자 오류였으며 수정했다. 실제 S3/DB/Kafka 접속은 시험하지 않았다. 클라우드 시험 결과와 정리는 상위 작업 기록에 별도로 남긴다.

Maven의 실제 속성 `mdep.useRepositoryLayout`을 사용한다. 공식 Spark 이미지에 이미 포함된 Scala·LZ4·SLF4J·Snappy 버전과 전이 의존성이 달라 POM dependencyManagement로 맞췄다. 추가 jar 10개의 버전·체크섬은 [dependencies.lock.json](dependencies.lock.json)에 기록했다. 로컬 기본 이미지 크기는 약 **2.07GB(비압축)**이며 첫 노드의 pull 시간이 실제 기동 지연에 포함된다.

## 빌드 전 채울 값

- `SPARK_BASE_IMAGE`: 위 공식 Spark 이미지의 검증된 `@sha256:...` 참조. 현재 Dockerfile 기본값에 고정했다.
- `MAVEN_BUILD_IMAGE`: Maven 3.9.16·Java 21 빌드 이미지의 검증된 `@sha256:...` 참조. 현재 Dockerfile 기본값에 고정했다.
- Maven runtime 전이 의존성을 함께 해결한다. `install_jars.py`는 기본 Spark 이미지에 동일 artifact의 다른 버전이 있으면 빌드를 중단한다. 충돌을 검토하고 POM을 맞춰야 하며 기존 jar를 무조건 덮어쓰지 않는다. 배포 전 해결된 전체 의존성 목록·체크섬과 두 기본 이미지 digest를 고정해야 한다.
- 이미지 크기와 최초 pull 시간도 측정한다. AWS SDK 전이 의존성 때문에 이미지가 커질 수 있다.

명시적으로 다른 검증 digest를 사용할 때는 아래 변수를 지정한다. 생략하면 Dockerfile의 고정 기본값을 사용한다. 합성 시험 이미지 `Dockerfile.smoke`는 가짜 숫자 데이터만 계산하며 업무 저장소에 접속하지 않는다.

```powershell
docker build --platform linux/amd64 `
  --build-arg "SPARK_BASE_IMAGE=$SparkBaseImage" `
  --build-arg "MAVEN_BUILD_IMAGE=$MavenBuildImage" `
  -t clothes-query-spark-base:4.2.0-prep infra/platform/spark/image
```

## 팀원에게 전달할 계약

검증된 기본 이미지가 발행되면 팀원은 그 **digest**를 FROM으로 참조하고 업무 코드와 필요한 Python 패키지를 추가한다. 진입 파일은 예를 들어 `/opt/jobs/main.py`에 넣고 `spark-submit local:///opt/jobs/main.py`로 제출한다. 기본 이미지의 Spark entrypoint를 유지하며 Driver와 Executor에 같은 업무 이미지 digest를 사용한다. 일반 Python 코드가 자동으로 Spark 코드로 변환되지는 않는다.

S3는 작업 코드에서 Hadoop S3A를 사용할지 별도 Python SDK를 쓸지 확정해야 한다. 이 이미지는 boto3를 추가하지 않는다. Pod Identity·인증서·Secret 마운트·읽기 권한은 아직 미연결이며, 연결 설정 예시 파일도 자동 소비하지 않는다. RDS 읽기 동시 연결 수와 Kafka 인증/offset 및 출력·checkpoint 계약은 팀원과 별도로 맞춘다.

## 공식 근거

- [공식 이미지 정의](https://github.com/docker-library/official-images/blob/master/library/spark)
- [Spark 4.2.0 Hadoop 의존성](https://github.com/apache/spark/blob/v4.2.0/pom.xml)
- [Kafka 커넥터 배포](https://spark.apache.org/docs/4.2.0/streaming/structured-streaming-kafka-integration.html)
- [PostgreSQL JDBC](https://jdbc.postgresql.org/download/)
