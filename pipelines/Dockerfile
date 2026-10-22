ARG SPARK_IMAGE=apache/spark:4.2.0
FROM ${SPARK_IMAGE}
USER root
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AWS_EC2_METADATA_DISABLED=true \
    AWS_DEFAULT_REGION=ap-northeast-1 \
    JAVA_HOME=/opt/java/openjdk \
    SPARK_HOME=/opt/spark \
    PYSPARK_PYTHON=/usr/bin/python3 \
    PYSPARK_DRIVER_PYTHON=/usr/bin/python3 \
    PYTHONPATH=/opt/pipelines \
    PATH=/opt/java/openjdk/bin:/opt/spark/bin:$PATH
WORKDIR /opt/pipelines
COPY pipelines/requirements.txt /opt/pipelines/pipelines/requirements.txt
RUN python3 -m pip install --no-cache-dir -r pipelines/requirements.txt \
    && python3 -c "import sys; assert sys.version_info[:3] == (3, 10, 12), sys.version"
ADD https://repo.maven.apache.org/maven2/org/apache/hadoop/hadoop-aws/3.5.0/hadoop-aws-3.5.0.jar /opt/spark/jars/
ADD https://repo.maven.apache.org/maven2/software/amazon/awssdk/bundle/2.35.4/bundle-2.35.4.jar /opt/spark/jars/
ADD https://repo.maven.apache.org/maven2/software/amazon/s3/analyticsaccelerator/analyticsaccelerator-s3/1.3.1/analyticsaccelerator-s3-1.3.1.jar /opt/spark/jars/
ADD https://repo.maven.apache.org/maven2/org/wildfly/openssl/wildfly-openssl/2.2.5.Final/wildfly-openssl-2.2.5.Final.jar /opt/spark/jars/
ADD https://repo.maven.apache.org/maven2/org/apache/spark/spark-hadoop-cloud_2.13/4.2.0/spark-hadoop-cloud_2.13-4.2.0.jar /opt/spark/jars/
RUN chmod a+r /opt/spark/jars/*.jar
COPY pipelines/ /opt/pipelines/pipelines/
COPY docs/contracts/format_rules.yaml /opt/pipelines/docs/contracts/format_rules.yaml
ARG CODE_REF=unknown
ENV PIPELINE_CODE_REF=$CODE_REF
RUN test -n "$CODE_REF" && test "$CODE_REF" != unknown
USER 185:0
ENTRYPOINT ["/opt/entrypoint.sh"]
