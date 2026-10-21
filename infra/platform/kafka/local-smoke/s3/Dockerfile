# syntax=docker/dockerfile:1.7
# Derived from the existing pinned CDC image, built under this test's random tag.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
ADD --checksum=sha256:315c0ab43524d75a078cb33780adbad90cc6c8aa648fd38712e848d14efea485 https://hub-downloads.confluent.io/api/plugins/confluentinc/kafka-connect-s3/versions/12.1.13/confluentinc-kafka-connect-s3-12.1.13.zip /tmp/s3-plugin.zip
# The pinned Strimzi base already supplies unzip; no extra OS packages.
RUN mkdir -p /opt/kafka/plugins/s3 \
    && cd /opt/kafka/plugins/s3 \
    && unzip -q /tmp/s3-plugin.zip \
    && chown -R 1001:0 /opt/kafka/plugins/s3 \
    && rm /tmp/s3-plugin.zip
USER 1001
