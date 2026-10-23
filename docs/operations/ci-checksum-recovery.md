# CI 체크섬 실패 복구

2026-10-24 #102 검토 중 사용자가 Terraform·kafka-local 실패를 먼저 해결하도록 요청했다. AWS 자원·운영 Connect 이미지를 변경하거나 체크섬 검증을 끄지 않는다.

## Terraform

dashboard 스택은 AWS provider 6.70.0의 공식 zip 체크섬(zh)은 있었지만 h1은 Windows 것만 있었다. Linux readonly init 뒤 validate가 설치된 패키지를 검증하지 못했다. 공식 registry를 사용하는 `terraform providers lock -platform=linux_amd64 -platform=windows_amd64 registry.terraform.io/hashicorp/aws`로 HashiCorp 서명 검증을 거쳐 Linux h1을 추가했다. 버전·기존 Windows h1·zh 목록은 유지했다. CI에서 lockfile을 자동 수정하지 않는다.

CA 인증서가 있는 Linux 컨테이너에서 Terraform 1.15.8·빈 provider cache로 `init -backend=false -lockfile=readonly` 및 `validate`를 실행하고 lockfile 무변경을 확인했다. 최초 최소 Ubuntu 이미지에는 CA 인증서가 없어 TLS 연결이 거부됐고, 인증서가 포함된 기존 이미지로 바꿔 TLS 검증을 유지한 채 통과했다. 공식 절차는 [providers lock](https://developer.hashicorp.com/terraform/cli/commands/providers/lock)을 참고한다.

## Connect 플러그인

CI의 BuildKit 원격 ADD가 계산한 Debezium SHA-256은 pin과 달랐다. 원격 응답의 정확한 바이트는 실패 로그에 남지 않아 CDN 응답·cache 등의 세부 원인을 단정하지 않는다. [Maven Central의 동일 버전 파일](https://repo.maven.apache.org/maven2/io/debezium/debezium-connector-postgres/3.7.0.Final/debezium-connector-postgres-3.7.0.Final-plugin.tar.gz)을 다시 받아 게시된 SHA-512와 대조했으며 기존 SHA-256 `660673cbabd2f269da21409208ebd0f0d9977bd92e824fc9daa272f240e88e51`이 맞았다.

Dockerfile은 빌드 컨테이너의 HTTPS curl로 다운로드하고 같은 SHA-256을 검증한 뒤에만 압축을 푼다. 전송/검증이 실패하면 받은 파일을 지우고 최대 3번 새로 받으며 계속 실패하면 빌드를 중단한다. 버전·고정 해시·기반 image digest는 바꾸지 않았다.

실제 production RUN 구문으로 격리 fixture 3가지를 검사했다: 정상 파일은 1회 성공, 잘못된 파일 2회 뒤 정상 파일은 3회째 성공, 잘못된 파일 3회는 exit 1이며 플러그인을 설치하지 않음. 수정한 이미지의 실제 다운로드·빌드도 통과했다. CI와 같은 local-smoke/check.py에서 Kafka mTLS/hostname·허용/거부 ACL, 비관리자 CDC 계정의 snapshot/insert/update/delete, Connect 정지 중 변경 이어받기, Kafka 재생성 뒤 메시지/offset 보존과 CDC 재개·지표 검사를 모두 통과했다. 생성한 시험 컨테이너·네트워크·볼륨·이미지 태그는 검사기가 정리했다. 최종 원격 결과는 PR #102의 현재 head checks를 따른다.
