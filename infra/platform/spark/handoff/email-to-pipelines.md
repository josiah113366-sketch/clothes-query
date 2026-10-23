제목: Silver·Gold A Spark 실행 준비 현황과 남은 연결 정보 요청

안녕하세요. 보내주신 명세 확인했고, 먼저 준비할 수 있는 인프라 작업을 진행했습니다.

Spark 4.2.0 / Python 3.10.12 / Java 21 / Hadoop·S3A 3.5.0 기준으로 요청하신 PyYAML 6.0.3, boto3 1.43.71, PyArrow 25.0.1, tzdata 2026.3을 설치했습니다. 로컬 이미지에서 패키지 로딩·Parquet 저장/읽기·KST 시간대·Spark 합성 실행까지 확인했습니다. 실제 업무 코드와 AWS S3 입출력 검증은 별도로 진행해야 합니다.

계정 이름은 아래로 준비했습니다. AWS 실행 역할은 Driver·Executor에 각각 분리하고, 제출기는 Kubernetes 제출 권한만 사용하는 기준입니다.

- 제출기: silver-gold-a-submitter
- Driver: silver-gold-a-driver
- Executor: silver-gold-a-executor

요청 JSON은 pipelines/requests/, 입력 목록은 pipelines/input-manifests/ 기준으로 준비했습니다. 최초 거래 권한은 기존 Bronze 주문·주문상품·결제 읽기, silver/runtime/trade/와 gold_a/runtime/trade/ 읽기·쓰기 및 multipart 조회/중단입니다. 삭제는 실행별 데이터셋 아래 __magic_job-* 작업 객체로 제한하는 안으로 만들었습니다. 정상 결과·완료 기록 삭제 권한은 추가하지 않습니다.

기본 이미지와 업무 이미지용 ECR 저장소·18번 개발자 push 권한은 코드와 plan 검토까지 준비했습니다. 아직 AWS 적용·원격 이미지 발행 전이므로 실제 사용 가능한 저장소 주소와 digest는 발행 완료 후 전달드리겠습니다. namespace 미확정 상태에서 실행 권한이나 Spark 노드를 먼저 올리지는 않았습니다.

연결을 마무리하려면 아래 정보만 추가로 부탁드립니다.

1. Gold B 담당자와 확인한 namespace 공유 여부
   pipelines 공유로 최종 확정됐는지 알려주세요. 공유하지 않으면 사용할 namespace를 알려주시면 됩니다. 계정 이름은 위 이름으로 맞춰주시면 됩니다.

2. 업무 코드가 올라간 원격 브랜치 또는 PR 주소
   현재 이 저장소 원격에서는 커밋 908c252가 조회되지 않습니다. 소스를 받아야 진입점·이미지 COPY 경로·공통 YAML/지문 함수 포함·실제 Spark/S3A 설정을 대조할 수 있습니다.

3. 첫 거래 시험용 고정 요청 JSON과 입력·기대값
   실제로 읽을 Bronze 객체 목록 또는 입력 manifest URI, 상품 디자인/변형 기준정보의 S3 위치와 필요한 버전·날짜 범위를 부탁드립니다. 실행 요청 JSON의 고정 URI도 함께 주세요. 성공 기준은 주문 수·성공 결제 금액·상품별 판매 수량과 품질 PASS/갱신 차단 여부를 사례별로 적어주시면 됩니다. 대략적인 파일 수·전체 크기도 자원 검증에 도움이 됩니다.

4. 최종 커미터 설정과 실제 작업 객체 경로 예시
   fs.s3a.committer.abort.pending.uploads 등 실제 적용할 S3A/Spark 설정과 runs/<run_id>/<dataset>/ 아래 생성되는 작업 객체 경로 예시를 부탁드립니다. 기본 설정에 따라 목적지의 진행 중 업로드 목록 조회가 필요할 수 있어, ListBucketMultipartUploads까지 필요한지 코드 기준으로 확인하려고 합니다. __magic_job-* 밖에서도 삭제가 필요한 객체가 있으면 경로와 이유만 추가로 알려주세요.

5. Glue·Athena 최종 공개 명세
   DB·표·뷰 이름, 컬럼/타입·파티션·실제 데이터 위치와 완료 실행 공개 방식을 부탁드립니다. 지표와 refresh_holds가 같은 run_id를 읽는 조건도 함께 필요합니다. R6용 silver_runs·order_amount_checks는 completed_at 구현 후 최종 DDL과 읽을 역할(R6 판정 잡/조사 에이전트 각각 필요한 표·S3 경로)을 알려주세요. current.json만 바꿔 Athena 조회 대상이 바뀐다고 가정하지 않겠습니다.

우선 1~4번이 준비되면 Glue 공개와 분리해 거래 S3 입출력 수동 검증부터 진행할 수 있습니다. 기본 이미지·ECR 정보를 전달드린 다음 업무 이미지를 빌드·push해서 digest와 최종 실행 명령을 주시면 연결하겠습니다. funnels/reviews는 해당 입력·출력 경로가 확정된 뒤 추가 권한을 맞추겠습니다.

감사합니다.
