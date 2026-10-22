상태: 구현 완료 · 이미지 빌드·운영 배포 검증 대기 · 브랜치: `pipelines/runtime`

# Silver·Gold A 운영 실행 연결

## 승인 범위

- 사용자 승인: 기존 계산 코드를 호출하는 처리 이미지·S3 실행기·수동 Airflow DAG 구현.
- 최신 main에서 브랜치를 만들고 선행 Gold A #67 코드를 로컬에 포함했다. #67 main 반영 후 이 브랜치도 main과 동기화한다.
- 공통 입력 규약·계산 규칙은 변경하지 않는다. 새로운 분석·Spark 전환·Kafka 소비·인프라 apply·이미지 push·운영 실행은 포함하지 않는다.
- namespace·ServiceAccount·ECR 이미지 digest·노드 배치는 인프라가 공급한다. 기존 agent 신원을 재사용하지 않는다.

## 구현 계획과 파일

- pipelines/batch.py: 입력 목록/ETag 고정·크기 제한·다운로드, 기존 회원/상품/거래/클릭/리뷰 Silver와 Gold A 호출, 고정 S3 참조 변환과 결과 공개.
- pipelines/Dockerfile 및 Dockerfile.dockerignore: Python 실행 이미지와 원문·캐시·자격증명 제외. requirements.txt에 boto3·pyarrow 고정.
- infra/platform/airflow/dags/silver_gold_a.py: 수동 작업 선택, digest·실행 신원 검사, 별도 Pod, 단일 실행·재시도 0회.
- pipelines/tests/test_batch.py: 기존 계산 시나리오를 재사용해 실제 어댑터의 경로 변환·품질/R6·저장 실패 경계를 검증. 운영 경계 검증을 한 파일에 모은다.
- 기존 README와 브랜치 대장에 실행·설정·후속 연결을 기록한다.

## 완료 확인

- 가짜 S3로 실제 Silver → Gold A 판매·퍼널·리뷰 점수 실행. 모든 출력 참조가 존재하고 로컬 임시 경로가 남지 않는지 확인.
- 금액 MISMATCH도 Silver 완료 기록과 R6 상세에 보존하며 Gold A 최신 결과를 유지.
- 다운로드 누락·입력 변경·크기 초과·업로드 실패가 정상 완료로 공개되지 않는지 확인.
- 전체 pipelines 회귀·Ruff·DAG 구문 검사·가능하면 이미지 빌드. 운영 검증과 로컬 검증을 구분한다.

## 작업 결과

- 처리 이미지 정의·S3 실행기·수동 DAG를 구현했다. 거래/퍼널/리뷰/회원 작업 선택, ETag 입력 고정·기본 128MiB 제한, 실행별 S3 참조 치환, Silver 검사와 Gold A 완료 공개 분리, current의 조건부 쓰기를 제공한다. 원문·정적 AWS 키는 로그나 이미지에 포함하지 않는다.
- 운영 어댑터 시험 8개 통과: 실제 판매·퍼널·리뷰 점수·회원 실행, 금액 MISMATCH의 R6 보존, 이전 Gold A 유지, 원본 변경/누락/크기 초과, Gold 업로드 실패, UTC/KST 리뷰 범위와 Windows 긴 경로 참조. 가짜 S3를 사용했으며 실제 운영 데이터 처리 검증이 아니다.
- 전체 pipelines 115개 통과(17.19초), 변경 Python Ruff·구문 검사·git diff --check 통과, 로컬 pip check 통과.
- Windows 로컬 Airflow 실행은 os.register_at_fork 미지원으로 실패했다. 실행 중인 EKS Airflow 3.3.2 DAG processor에서 소스를 메모리로만 파싱해 DAG ID/두 태스크/선행 관계·수동 단일 실행·Pod 신원 설정·BATCH_CONFIG JSON 템플릿을 확인했다. DAG 파일 저장·배포·Trigger·업무 Pod 생성은 하지 않았다.
- 처음에는 Docker Linux 엔진이 꺼져 빌드하지 못했으나 설치된 Docker Desktop을 백그라운드로 시작해 로컬 이미지 빌드에 성공했다. 빌드 컨텍스트의 .local·캐시·테스트 제외를 명시적으로 보완하고 Git 커밋 없는 빌드를 거부한다. Linux 컨테이너에서의 계산 확인 후 결과를 추가 기록한다. 이미지 push·namespace·ServiceAccount·Pod Identity/S3 권한·ECR 저장소·DAG 마운트는 아직 생성하지 않았다.
- 상품 기준정보 JSONL 스냅샷의 실제 S3 위치, 실제 Bronze 크기·형식·완전성, 모델 결과 완료 범위, 실제 R6 판정 소비, 정기·부분 재처리·A/B 대조 연결은 후속이다. 현재 실행기는 전체 입력 스냅샷 방식이며 기존 범위별 보류·부분 병합을 자동 호출하지 않는다.
