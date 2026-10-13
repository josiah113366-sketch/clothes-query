# Connect image vulnerability scan

상태: 검사·분류 완료 / 취약점 조치 미완료. 이 문서는 2026-10-14 한국 시간의 로컬 검사 스냅샷이다. 실제 이미지 ECR 배포 검사는 아니며 아래 image ID는 레지스트리 digest를 대신하지 않는다.

UTC: 2026-10-13T18:49:39.776066+00:00
Scanner: Trivy 0.75.0 (digest pinned)
Image ID: `sha256:d81fc79eb8583febe06038dfd54e45f70c5e0a5b67a487db5664efc1bf42d9ac`

Raw findings: 511; unique CVE/package/version findings: 511.

| Severity | Findings | Listed fixed version |
|---|---:|---:|
| CRITICAL | 1 | 1 |
| HIGH | 73 | 49 |
| MEDIUM | 297 | 73 |
| LOW | 133 | 6 |
| UNKNOWN | 7 | 6 |

## First 15 critical/high package findings

수정 버전 표시는 scanner DB의 메타데이터다. 이 프로젝트와의 업데이트 호환성 또는 실제 공격 가능성을 보증하지 않는다.

| CVE | Package | Installed | Listed fix | Severity |
|---|---|---|---|---|
| CVE-2026-75595 | io.netty:netty-handler | 4.1.118.Final | 4.2.17.Final, 4.1.137.Final | CRITICAL |
| CVE-2024-13009 | org.eclipse.jetty:jetty-server | 9.4.56.v20240826 | 9.4.57.v20241219 | HIGH |
| CVE-2024-29371 | org.bitbucket.b_c:jose4j | 0.9.4 | 0.9.6 | HIGH |
| CVE-2024-47554 | commons-io:commons-io | 2.11.0 | 2.14.0 | HIGH |
| CVE-2025-12183 | org.lz4:lz4-java | 1.8.0 | 1.8.1 | HIGH |
| CVE-2025-55163 | io.netty:netty-codec-http2 | 4.1.110.Final | 4.2.4.Final, 4.1.124.Final | HIGH |
| CVE-2026-10050 | org.eclipse.jetty:jetty-security | 12.0.34 | 9.4.63, 10.0.31, 11.0.31, 12.0.36, 12.1.10 | HIGH |
| CVE-2026-10050 | org.eclipse.jetty:jetty-security | 9.4.56.v20240826 | 9.4.63, 10.0.31, 11.0.31, 12.0.36, 12.1.10 | HIGH |
| CVE-2026-106451 | at.yawk.lz4:lz4-java | 1.10.2 | 1.11.4 | HIGH |
| CVE-2026-2332 | org.eclipse.jetty:jetty-http | 9.4.56.v20240826 | 12.1.7, 12.0.33, 11.0.29, 10.0.28, 9.4.60 | HIGH |
| CVE-2026-33870 | io.netty:netty-codec-http | 4.1.110.Final | 4.1.132.Final, 4.2.10.Final | HIGH |
| CVE-2026-33871 | io.netty:netty-codec-http2 | 4.1.110.Final | 4.1.132.Final, 4.2.11.Final | HIGH |
| CVE-2026-35554 | org.apache.kafka:kafka-clients | 4.0.0 | 3.9.2, 4.0.2, 4.1.2 | HIGH |
| CVE-2026-42579 | io.netty:netty-codec-dns | 4.1.110.Final | 4.2.13.Final, 4.1.133.Final | HIGH |
| CVE-2026-42583 | io.netty:netty-codec | 4.1.118.Final | 4.1.133.Final | HIGH |

A listed fix is advisory metadata, not proof of compatibility or exploitability.
No findings are suppressed. This scan records results; it does not approve a release or change dependencies.
Full local report and database timestamps are in report.json and summary.json.

## 조치 분류와 한계

- **수정 버전 정보 있음:** Critical 1 / High 49. 기반 이미지·플러그인 등 실제 포함 위치를 확인하고 호환되는 공식 릴리스 후보로 업데이트한 뒤 전체 TLS/CDC/보존 검사를 다시 실행해야 한다.
- **수정 버전 정보 없음:** High 24 등. 배포판 advisory·실제 경로·완화/업스트림 상태를 별도 확인한다. 미수정 항목을 검사에서 제외하지 않았다.
- **Critical 상세:** `CVE-2026-75595`, `io.netty:netty-handler:4.1.118.Final`은 `opt/cruise-control/libs/netty-handler-4.1.118.Final.jar`에서 발견됐다. 현재 Kafka chart에 Cruise Control 활성 설정은 없으나 포함된 패키지 취약점과 실제 도달 가능성은 별개 검토다.
- Trivy는 위 항목을 Critical로 분류했다. 확인 당시 [Netty 공급자 advisory](https://github.com/netty/netty/security/advisories/GHSA-c4c3-7fpv-j4q5)는 High로 표시하고, 특정 SNI fallback·mTLS 구성 조건을 설명한다. scanner 원본 집계를 임의로 바꾸지 않았고 실제 Kafka listener가 이 공격 경로라는 주장도 하지 않는다.
- 이미지에는 현재 Connect에서 사용하지 않는 도구도 포함되어 있다. 패키지 존재 검사는 실행 경로 증명이나 침해 확인이 아니다. 배포 준비 완료·무취약 이미지로 표시하지 않는다.
- 현재 작업은 검사·분류 범위다. 업스트림 이미지/플러그인 변경이나 jar 강제 교체는 수행하지 않았다. 재실행은 [로컬 검사 안내](../../../infra/platform/kafka/image-security/README.md)를 따른다.

## Database metadata

```json
{
  "vulnerability": {
    "Version": 2,
    "NextUpdate": "2026-10-14T13:06:33.602530891Z",
    "UpdatedAt": "2026-10-13T13:06:33.602531196Z",
    "DownloadedAt": "2026-10-13T18:43:05.98991227Z"
  },
  "java": {
    "Version": 1,
    "NextUpdate": "2026-10-16T01:09:47.998142983Z",
    "UpdatedAt": "2026-10-13T01:09:47.998143143Z",
    "DownloadedAt": "2026-10-13T18:46:09.093303192Z"
  }
}
```

## Component counts

| Component | Critical | High | Medium | Low | Unknown |
|---|---:|---:|---:|---:|---:|
| Base OS | 0 | 22 | 224 | 126 | 0 |
| Bundled Cruise Control | 1 | 34 | 45 | 5 | 0 |
| Kafka/Connect libraries | 0 | 13 | 21 | 1 | 0 |
| Other bundled component | 0 | 4 | 7 | 1 | 7 |
