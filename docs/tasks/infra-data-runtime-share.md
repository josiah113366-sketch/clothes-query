# 데이터·Airflow 연결 작업 통합 공유

상태: 초안 PR #74 공유 완료, Airflow 본체 노드 고정 제거 실제 적용·사후 확인 완료, 업무 연결 대기

## 범위

사용자 승인으로 최신 main `0312bad`에서 `infra/agent-runtime-connections` `444418c`, `infra/gold-b-catalog` `7499681`, `infra/live-code-audit` `01ec915`와 현황 문서를 묶는다. 원본 브랜치는 보존한다. 앱·DAG·업무 SQL 구현, AWS 적용·업무 실행은 이번 작업에 포함하지 않는다.

## 작업 결과

공통 대장·README·배포 안내 충돌은 양쪽 내용을 보존해 해결했다. 점검 안내서의 '현재 values가 ConfigMap 방식' 문구를 통합 후 GitDagBundle 설정과 맞췄다. Secret과 runtime override는 기존 비공개 공급을 유지한다. 확정된 JP Haiku 모델·남은 에이전트 업무 연결·Spark Streaming 인지 사항은 현황 문서에만 반영했고 미적용 Bedrock 정책을 활성화하지 않았다. 과거 작업 지시서는 적용·점검 당시 근거로 보존한다.

## 완료 확인

- [x] 최신 main에서 새 브랜치, 기존 원본 보존.
- [x] 카탈로그·권한·Git 공급·DAG 안내·현황 문서 통합.
- [x] Terraform fmt 통과, backend·자격증명 없는 격리 복사본에서 dashboard-access/gold-b-catalog/gold-b-access 및 test root validate 통과, mock plan 7개 통과.
- [x] Airflow chart schema/render 통과: Deployment 3개·Git bundle·paused 기본값·이전 DAG ConfigMap 미마운트·새 PVC/Ingress/노드 미생성 확인.
- [x] 공통 문서 추가 위치를 조정한 뒤 세 공유 브랜치를 합치는 임시 tree 검사 통과. 원본 브랜치 커밋 불변·민감 파일 제외·diff 검사 확인.
- [x] 초안 PR #74 공유 완료. 팀원 검토·승인·머지는 대기.

## 후속: 특정 노드 hostname 고정 제거

사용자가 노드 장애 후 재배치가 막히는 설정의 수정을 요청했다. 읽기 전용 조회에서 API·scheduler·DAG processor 3개가 기존 compute 노드 hostname에 고정된 것을 확인했다. 비공개 로컬 runtime 파일에서 hostname을 제거하고 공용 compute 노드풀은 유지한다. 해당 파일은 커밋하지 않는다. 설치 확인용 Pod도 노드풀을 선택한다. 최종 렌더 검사는 hostname·nodeName·개별 노드를 지정한 필수 affinity를 거부한다. 차트 schema가 null selector를 거부하므로 null overlay 대신 원본 키 삭제·완전한 runtime 입력·--reset-values 방식으로 안내한다.

이 후속은 코드·로컬 설정 준비다. 클러스터의 hostname 고정은 아직 유지되며 Helm 재배포 후 제거 여부를 확인해야 한다. 노드/Pod 강제 종료·업무 DAG 실행·AWS/Helm 적용은 하지 않는다.

위 문단은 코드 준비 당시 상태다. 이후 사용자가 현재 작업이 없는 시점에 실제 반영을 요청해 아래처럼 적용했다.

검증: 실제 로컬 runtime 입력으로 Helm 렌더한 4개 workload의 노드풀 배치를 통과했다. 수정 전 고정은 거부하고 nodeName·필수 hostname affinity도 거부했다. 본체 Deployment 3개는 nodeSelector 외 Pod spec이 동일함을 비교했다. 설치 확인용 DAG의 KPO도 노드풀 선택만 사용하는 것을 AST로 확인했다. 실제 노드 장애 복구·실행 중 클러스터 변경을 시험한 결과는 아니다.

### 실제 적용 결과 (2026-10-22 20:21 KST 사후 확인)

- 현재 Helm user values를 비공개 보존하고 hostname 한 키만 제거한 후보를 만들었다. 이전/후보 렌더의 모든 객체를 비교해 해당 nodeSelector 외 변경이 없음을 확인하고 서버 dry-run을 통과했다. 배포 직전 DAG 모두 paused·실행/대기 작업 0건·values/revision 불변을 재확인했다.
- 동일 chart 1.22.0·Airflow 3.3.2·이미지·인증·Git bundle·S3/DB 설정에서 Helm upgrade --reset-values --atomic을 수행했다. revision 3→4 deployed. 마이그레이션 확인 Job 성공, 본체 3개 Ready/restart 0, 실제 selector에 hostname 없음. 재시작 중 일시 중단은 있었다.
- API health HTTP 200, metadatabase/scheduler/dag_processor healthy, Git 설치 확인용 DAG 2개 paused·import error 0, 실행/대기 작업 0건. 기존 노드 2대 동일, WAS·Kafka·모니터링·Argo CD의 기존 활성 Deployment 정상과 Kafka broker Ready 확인.
- 설치 확인용 DAG의 KPO 변경은 PR #74 main 머지 후 공급된다. 현재 main의 과거 probe는 paused로 유지한다. 업무 DAG·Bedrock·업무 표·이미지를 적용한 결과는 아니며 강제 노드 장애 시험도 하지 않았다.
- 상세 values·렌더·관측 결과는 Git 제외 .cache/airflow-placement-*.private.* 및 airflow-after-placement-health.private.json에 보관한다. 인증 값·state·plan은 커밋하지 않는다.
