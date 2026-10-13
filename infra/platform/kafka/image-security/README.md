# Connect 이미지 취약점 검사

저장소 루트에서 Docker Desktop Linux와 Python 표준 라이브러리로 실행한다:

```powershell
python -X utf8 infra/platform/kafka/image-security/check.py
```

현재 고정 Dockerfile로 이미지를 빌드해 임시 tar로 내보내고, digest 고정 Trivy 0.75.0 컨테이너가 읽는다. scanner에는 Docker socket·AWS 자격증명·업무 데이터·개인 폴더를 전달하지 않는다. 실제 로그인/push/API 배포는 하지 않는다. scanner의 익명 사용 데이터 전송을 비활성화한다. 공개 이미지/OS·Java 취약점 DB 다운로드에는 인터넷이 필요하다. DB는 실행 시 최신 제공 데이터를 쓰므로 재검사 결과가 달라질 수 있다.

결과는 무시되는 `.cache/connect-security/`의 `report.json`, `summary.json`, `summary.md`에 저장한다. OS/Java 전체 심각도를 검사하고 ignorefile·미수정 항목 제외를 사용하지 않는다. 중복은 CVE/package/설치 버전으로 집계하며 원본 개수도 보존한다. summary에는 실제 이미지 ID·scanner digest·Dockerfile hash·DB 시각을 기록한다. 임시 image tag·tar·scanner container만 정리하며 DB와 이미지 레이어 캐시는 남는다.

취약점이 있어도 검사 자체가 끝나면 결과를 기록한다. 배포 허용 정책이나 취약점 무시를 의미하지 않는다. 공급처의 수정 버전 표시는 해당 조합에서 안전하게 교체할 수 있다는 보증이 아니다. 기반 Strimzi/Kafka와 Debezium 플러그인의 업데이트는 호환 버전 확인·TLS/CDC/재생성 검증 후 별도 변경한다. 이번 작업은 검사/분류이며 라이브러리 강제 덮어쓰기를 하지 않는다.

공식 근거: [Trivy image/archive 검사](https://trivy.dev/docs/latest/target/container_image/), [고정 scanner 릴리스](https://github.com/aquasecurity/trivy/releases/tag/v0.75.0).
