# Debezium Connect 이미지에 Confluent S3 Sink 플러그인을 더한다.
# 플러그인 버전과 체크섬은 Confluent Hub 매니페스트에서 가져온 값이다. 올릴 때는 둘을 함께 바꾼다.
FROM alpine:3.20 AS plugin
ARG S3_SINK_VERSION=12.1.13
ARG S3_SINK_SHA1=a7ac8bef56b2dd91fd30840acf3655af239e9bf3
RUN apk add --no-cache curl unzip \
 && curl -fsSL -o /tmp/s3-sink.zip \
      "https://hub-downloads.confluent.io/api/plugins/confluentinc/kafka-connect-s3/versions/${S3_SINK_VERSION}/confluentinc-kafka-connect-s3-${S3_SINK_VERSION}.zip" \
 && echo "${S3_SINK_SHA1}  /tmp/s3-sink.zip" | sha1sum -c - \
 && unzip -q /tmp/s3-sink.zip -d /plugin

FROM quay.io/debezium/connect:3.7.0.Final
COPY --from=plugin --chown=kafka:kafka /plugin/confluentinc-kafka-connect-s3-12.1.13 /kafka/connect/confluentinc-kafka-connect-s3
