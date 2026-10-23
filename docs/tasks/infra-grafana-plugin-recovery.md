# Grafana Prometheus 플러그인 복구

상태: 로컬 수정 및 실환경 복구 완료, push·PR 대기

2026-10-23 사용자가 Grafana 점검과 복구를 요청했다. 서버 /api/health는 정상이었으나 데이터소스 health 및 실제 up 조회가 404 Plugin not registered로 실패했다. 시작 로그에서 이미지에 포함된 Prometheus 플러그인을 자동 갱신하다 읽기 전용 파일시스템 오류로 실패한 것을 확인했다.

GF_PLUGINS_PREINSTALL_AUTO_UPDATE=false를 chart에 추가했다. 기존 Helm values를 읽어 보존하고 기존 manifest와 렌더를 비교해 Grafana Deployment의 환경변수 하나만 바뀌는 것을 확인한 뒤 cq-monitoring을 갱신했다. 다른 모니터링 Pod의 UID는 보존됐다. 노드·Kafka·Airflow·Spark·S3 권한은 수정하지 않았다.

검증: monitoring/check.py 통과. 재기동 후 데이터소스 health HTTP 200 / OK, 실제 Grafana /api/ds/query의 up 쿼리 HTTP 200, 오류 없이 5개 frame 반환. 기존 PVC와 로그인 Secret을 유지했다. Secret 값은 출력하거나 저장소에 추가하지 않았다.

공식 설정: https://grafana.com/docs/grafana/latest/datasources/prometheus/ 의 Plugin updates 및 preinstall_auto_update 설명. 단순 업데이트 확인 옵션과 실제 시작 시 자동 설치/갱신 옵션은 별개다.
