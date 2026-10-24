# check=skip=InvalidDefaultArgInFrom
# (위 줄은 빌드 검사 설정: SPARK_IMAGE에 일부러 기본값을 두지 않는다)
# Gold B 이미지: 적재 잡(Spark 스트리밍), 재처리 잡, 파일 합치기, Bronze 지연 수집기 (pipelines/gold_b/README.md 「이미지」).
# 공통 모듈과 형식 규칙표가 Gold B 폴더 밖에 있어서 저장소 루트에서 빌드한다. 넣는 파일은 Dockerfile.dockerignore가 정한다.
#   docker build -f pipelines/gold_b/Dockerfile --build-arg SPARK_IMAGE=<팀 기본 이미지>@sha256:<digest> \
#     --build-arg CODE_REF=<main 커밋> -t <Gold B 이미지>:<태그> .
# 팀 기본 Spark 이미지(infra/platform/spark/image)에서 출발한다. 공식 apache/spark에는 Kafka 연결 jar가 없어 적재 잡이
# 돌지 않으므로 기본값을 두지 않고, 빌드할 때 Kafka 연결·S3A jar가 있는지 확인한다.
ARG SPARK_IMAGE
FROM ${SPARK_IMAGE}
USER root
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AWS_EC2_METADATA_DISABLED=true \
    AWS_DEFAULT_REGION=ap-northeast-1 \
    PYSPARK_PYTHON=/usr/bin/python3 \
    PYSPARK_DRIVER_PYTHON=/usr/bin/python3 \
    PYTHONPATH=/opt/gold_b
WORKDIR /opt/gold_b
RUN ls /opt/spark/jars/spark-sql-kafka-0-10_2.13-*.jar /opt/spark/jars/kafka-clients-*.jar \
       /opt/spark/jars/hadoop-aws-*.jar > /dev/null \
    || { echo "팀 기본 Spark 이미지가 아니다: Kafka 연결·S3A jar가 없다" >&2; exit 1; } \
    && python3 -c "import sys; assert sys.version_info[:2] == (3, 10), sys.version"
COPY pipelines/gold_b/requirements.txt /opt/gold_b/pipelines/gold_b/requirements.txt
RUN python3 -m pip install --no-cache-dir -r pipelines/gold_b/requirements.txt
COPY pipelines/ /opt/gold_b/pipelines/
COPY docs/contracts/format_rules.yaml /opt/gold_b/docs/contracts/format_rules.yaml
ARG CODE_REF=unknown
ENV GOLD_B_CODE_REF=$CODE_REF
# 머지된 main 커밋으로만 만든다. 잡 4개가 부르는 모듈이 다 들어갔는지 import로 확인한다
RUN test -n "$CODE_REF" && test "$CODE_REF" != unknown \
    && python3 -c "import pipelines.gold_b.jobs.streaming_ingest, pipelines.gold_b.jobs.reprocess, pipelines.gold_b.jobs.compact, pipelines.gold_b.collector.bronze_lag_collector, pipelines.gold_b.format_check"
USER 185:0
ENTRYPOINT ["/opt/entrypoint.sh"]
