# 로컬 S3 저장 fixture

로컬 시험 전용이다. 기존 CDC 이미지에 체크섬 고정 Confluent S3 Sink 12.1.13을 추가하고 Moto 5.1.15의 S3 API에 JSON을 저장한다. AWS 계정·IAM·실제 S3에 접속하지 않는다. 호스트 포트를 공개하지 않고 Docker 내부 네트워크만 사용한다.

저장소 루트에서 실행:

```powershell
python -X utf8 infra/platform/kafka/local-smoke/check.py --compact --s3
```

`--s3` 없는 기존 CDC 시험에는 영향을 주지 않는다. DB에는 id/value 정수만 사용한다. schema envelope를 이해하는 JsonConverter를 거쳐 변경 이벤트를 JSON으로 저장한다. 삭제 이벤트는 저장하고 후속 null tombstone은 무시한다. 업무 현재값 테이블을 만드는 처리가 아니다.

snapshot·추가·수정·삭제, Connect 재시작 중 변경의 저장, 지정 prefix 밖으로 출력하지 않는 것을 확인한다. 중복은 허용하며 exactly-once 증명이 아니다. 한 건당 한 파일 설정은 연결 확인 전용으로 업무 적재 설정에 그대로 쓰지 않는다.

Moto는 실제 AWS IAM·TLS·Pod Identity·Gateway Endpoint 검증을 대신하지 않는다. 실행 보고서는 Git에서 무시되는 `.cache/kafka-pipeline-report.json`이다. 시험 종료 때 해당 무작위 Compose project의 container/network/volume과 시험 image tag만 삭제한다.

근거: [Confluent S3 설정](https://docs.confluent.io/kafka-connectors/s3-sink/current/configuration_options.html), [Moto server mode](https://docs.getmoto.org/en/latest/docs/server_mode.html).
