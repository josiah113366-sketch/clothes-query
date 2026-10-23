# Supply reviewed, digest-pinned images; no floating defaults.
# Context: infra/platform/spark/image
ARG SPARK_BASE_IMAGE=spark:4.2.0-scala2.13-java21-python3-ubuntu@sha256:d283f4305f6b307a7b1effce4fce9f6866f4b536b168809ddbaadb6aea793694
ARG MAVEN_BUILD_IMAGE=maven:3.9.16-eclipse-temurin-21@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320
FROM ${MAVEN_BUILD_IMAGE} AS dependencies
WORKDIR /build
COPY pom.xml ./pom.xml
RUN mvn --batch-mode --no-transfer-progress \
    org.apache.maven.plugins:maven-dependency-plugin:3.8.1:copy-dependencies \
    -DincludeScope=runtime -Dmdep.useRepositoryLayout=true -DoutputDirectory=/deps

FROM ${SPARK_BASE_IMAGE}
USER root
COPY --from=dependencies /deps /tmp/spark-dependencies
COPY install_jars.py /tmp/install_jars.py
# Validate the upstream distribution instead of silently mixing Hadoop versions.
RUN test -f /opt/spark/jars/spark-core_2.13-4.2.0.jar \
    && test -f /opt/spark/jars/hadoop-client-api-3.5.0.jar \
    && python3 /tmp/install_jars.py /tmp/spark-dependencies /opt/spark/jars \
    && rm -r /tmp/spark-dependencies /tmp/install_jars.py \
    && mkdir -p /opt/jobs \
    && chown 185:185 /opt/jobs
ENV AWS_REGION=ap-northeast-1 AWS_DEFAULT_REGION=ap-northeast-1
USER 185
# Preserve upstream Spark entrypoint. No job, endpoint or credentials embedded.
