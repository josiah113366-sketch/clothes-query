# Kafka 배포 전 검증 마무리

상태: 진행 중

사용자가 승인한 순서: 로컬 TLS/ACL → Kafka 재생성 데이터 보존 → Connect 이미지 취약점 검사 → 자동 검증 연결.

기존 준비 브랜치를 별도 worktree로 이어받는다. 실제 AWS/state/원격 push/PR/이미지 업로드는 수행하지 않는다. 검증은 임시 인증서·정수 데이터·실행별 고유 Docker project에 한정한다. 플랫폼 사양/업무 토픽/노드 상한은 변경하지 않는다.

## 완료 확인

- [x] 정상 TLS/ACL 및 인증서·토픽/group 권한 거부 실제 확인
- [x] Kafka container 재생성 후 메시지·Connect offset·CDC 이어받기 확인
- [x] 고정 Connect 이미지 취약점 검사와 실제 결과/한계 기록
- [ ] 기존 Terraform CI 초안과 Helm/로컬 검사 연결·로컬 검증
- [ ] 단계별 로컬 커밋·임시 자원 정리·남은 실배포 범위 기록

## 1단계 결과

고정 Kafka 4.3.1/Connect 이미지에서 임시 CA·server/Connect/reader 인증서와 StandardAuthorizer를 사용했다. Connect의 실제 CDC 쓰기와 reader의 읽기/group 접근은 mTLS·hostname 검증을 통과했다. 인증서 없음·다른 CA 인증서는 TLS 오류, 허용하지 않은 토픽/group은 각각 Topic/GroupAuthorizationException으로 거부됐다. 기존 CDC 변경/재시작·지표 검사도 통과하고 project `cq-cdc-750ee19ca3`를 정리했다.

인증서와 CA 키는 임시 디렉터리에만 생성하며 workload별 mount를 분리했다. Windows의 stdin 줄바꿈 변환을 방지하도록 Docker 입력을 bytes로 전달한다. 로컬 관리/controller/exporter용 평문 superuser 예외는 이 테스트 내부에만 존재하며 EKS에 적용하지 않는다. Strimzi 인증서 발급/회전·Kubernetes NetworkPolicy·RDS TLS는 미검증이다.

## 2단계 결과

Kafka KRaft/log를 실행별 named volume에 두었다. Connect를 정지한 뒤 Kafka를 force-recreate하여 container ID가 바뀌고 동일 volume이 재사용되는지 확인했다. 업무 토픽 end offset과 Connect offset 토픽의 최종 partition/offset 값이 재생성 전후 동일했다. 저장된 Connector config로 재시작한 뒤 중단 중 추가한 ID 4가 snapshot `r`이 아닌 변경 `c`로 전달됐고 이전 snapshot/insert/update/delete/ID 3도 남아 있었다.

TLS/ACL·CDC·재시작·지표 검사를 함께 통과하고 project `cq-cdc-a547910afa`의 자원을 정리했다. Docker local volume의 재생성 내성 검증이며 EBS/PVC·AZ 장애·강제 crash·백업 복구 보장은 아니다.

## 3단계 결과

digest 고정 Trivy 0.75.0으로 현재 Dockerfile의 Connect 이미지를 빌드·tar 검사했다. OS/Java/포함 도구 전체를 대상으로 ignore 없이 검사했고 익명 사용 데이터 전송은 비활성화했다. scanner에는 Docker socket을 전달하지 않았다.

CVE/package/설치 버전 기준 511개: Critical 1, High 73, Medium 297, Low 133, Unknown 7. 수정 버전 정보가 있는 항목은 각각 1/49/73/6/6개다. [검사 시점·이미지 ID·DB·주요 결과](../design/infra/connect-image-security-2026-10-14.md)를 기록했다. 실제 exploitability·업데이트 호환성을 확정하지 않았다. 라이브러리를 임의 교체하거나 취약점을 무시하지 않았다.

Critical로 분류된 Netty는 이미지에 포함된 Cruise Control jar에서 발견됐다. 현재 runtime은 Cruise Control을 활성화하지 않지만 이 사실만으로 위험을 제외하지 않는다. 공급자 advisory의 severity와 scanner 분류도 구분했다. 임시 scanner/container/image tag/tar 정리 완료, DB와 로컬 보고서는 `.cache/connect-security`에 보존한다.
