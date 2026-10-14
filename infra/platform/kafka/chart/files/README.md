# JMX 규칙 파일

chart의 metrics ConfigMap과 로컬 smoke test가 같은 YAML을 사용한다. Kafka/Connect/CDC의 aggregate 지표만 선택한다. 실행·수집·보안·검증 범위는 [지표 안내](../../metrics/README.md)를 따른다. 파일 수정 시 Helm 검사와 로컬 metrics 검사를 다시 실행한다.
