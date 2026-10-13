# syntax=docker/dockerfile:1.7
# Strimzi 1.3.0 / Kafka 4.3.1 multi-platform manifest, verified from quay.io.
FROM quay.io/strimzi/kafka@sha256:1f189b1f0f32684302d8b018b1d21b411e2469a9c465fbdc18fa3599cb5bbdad
USER root
# Maven Central artifact also checked against its published SHA-512 during preparation.
ADD --checksum=sha256:660673cbabd2f269da21409208ebd0f0d9977bd92e824fc9daa272f240e88e51 https://repo.maven.apache.org/maven2/io/debezium/debezium-connector-postgres/3.7.0.Final/debezium-connector-postgres-3.7.0.Final-plugin.tar.gz /tmp/postgres-plugin.tar.gz
RUN mkdir -p /opt/kafka/plugins/postgres \
    && tar -xzf /tmp/postgres-plugin.tar.gz -C /opt/kafka/plugins/postgres --strip-components=1 \
    && chown -R 1001:0 /opt/kafka/plugins/postgres \
    && rm /tmp/postgres-plugin.tar.gz
USER 1001
