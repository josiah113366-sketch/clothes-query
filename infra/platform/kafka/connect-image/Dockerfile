# syntax=docker/dockerfile:1.7
# Strimzi 1.3.0 / Kafka 4.3.1 multi-platform manifest, verified from quay.io.
FROM quay.io/strimzi/kafka@sha256:1f189b1f0f32684302d8b018b1d21b411e2469a9c465fbdc18fa3599cb5bbdad
USER root
# Connect does not start Cruise Control or Kafka Exporter. Keep the JMX agent.
# Fixed paths only; the Kafka broker/exporter continue using the original image.
RUN rm -rf /opt/cruise-control /opt/kafka-exporter \
    && microdnf --setopt=install_weak_deps=0 --setopt=tsflags=nodocs install -y \
        curl-minimal-7.76.1-40.el9_8.8.x86_64 \
        libcurl-minimal-7.76.1-40.el9_8.8.x86_64 \
        pcre2-10.40-7.el9_8.x86_64 \
        pcre2-syntax-10.40-7.el9_8.noarch \
    && microdnf clean all
# Maven Central artifact also checked against its published SHA-512 during preparation.
# Download inside the build container, not BuildKit's HTTP ADD cache. Retry a
# failed transfer/checksum together; never extract bytes that failed the pin.
RUN set -eu; \
    for attempt in 1 2 3; do \
        if curl --proto '=https' --proto-redir '=https' --fail --location --silent --show-error \
            --connect-timeout 15 --max-time 60 \
            --output /tmp/postgres-plugin.tar.gz \
            https://repo.maven.apache.org/maven2/io/debezium/debezium-connector-postgres/3.7.0.Final/debezium-connector-postgres-3.7.0.Final-plugin.tar.gz \
            && printf '%s  %s\n' 660673cbabd2f269da21409208ebd0f0d9977bd92e824fc9daa272f240e88e51 /tmp/postgres-plugin.tar.gz | sha256sum -c -; then \
            break; \
        fi; \
        rm -f /tmp/postgres-plugin.tar.gz; \
        if [ "$attempt" -eq 3 ]; then exit 1; fi; \
        sleep "$attempt"; \
    done \
    && mkdir -p /opt/kafka/plugins/postgres \
    && tar -xzf /tmp/postgres-plugin.tar.gz -C /opt/kafka/plugins/postgres --strip-components=1 \
    && chown -R 1001:0 /opt/kafka/plugins/postgres \
    && rm /tmp/postgres-plugin.tar.gz
USER 1001
