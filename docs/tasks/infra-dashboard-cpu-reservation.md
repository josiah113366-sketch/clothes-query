# Dashboard CPU 예약 유지

상태: 로컬 검증 완료, main PR·배포 대기

## 결정과 범위

개발 부하에서 정상 동작을 확인한 Dashboard CPU request 25m를 배포 원본에 반영한다.
CPU limit 1코어, memory request 512Mi/limit 1Gi, 이미지·인증·접근 권한·배포 전략은 보존한다.
이번 브랜치는 최신 main 25feba2 기준이며 deploy/dashboard와 같은 기준 커밋이다.

## 배포 흐름

작업 브랜치 → main 대상 PR → 팀원 머지 → Dashboard deploy workflow → deploy/dashboard → Argo CD → EKS.

workflow는 main의 매니페스트를 사용해 deploy/dashboard를 매번 다시 만든다.
그 배포 브랜치에만 수동 커밋하면 다음 배포에서 지워지므로 영구 수정 대상은 main이다.
PR 머지 시 매니페스트 경로 변경으로 기존 이미지 빌드·배포 workflow가 자동 실행된다.
Argo CD selfHeal은 이 원본 설정을 유지한다. 적용되면 Dashboard Pod가 교체돼 기존 Streamlit 세션은 다시 접속해야 할 수 있다.

## 완료 확인

- origin/main과의 YAML 의미상 차이가 CPU request 100m → 25m 하나인지 확인한다.
- 서버 dry-run으로 현재 Deployment의 이 필드 변경이 허용되는지 확인한다.
- PR 머지 후 workflow 성공, 배포 브랜치의 CPU 25m, Argo CD Synced/Healthy, 실제 Pod CPU request·health를 확인한다.

## 작업 결과

배포 매니페스트의 CPU request 한 필드만 수정했다. 새 테스트 코드는 추가하지 않는다.
25m 운영 확인 시 Dashboard health HTTP 200, 해당 Pod Ready와 재시작 없음, 실제 낮은 CPU 사용을 확인했다.
source of truth가 main임을 workflow의 checkout/main 기준 deploy 브랜치 생성 코드로 확인했다.
최신 origin/main 대비 YAML 의미상 변경이 CPU request 한 필드뿐임을 확인했고, 현재 Deployment의 서버 dry-run도 통과했다.
현재 원격·AWS 적용과 PR 머지는 별도 단계이며 자동 머지는 설정하지 않는다.
