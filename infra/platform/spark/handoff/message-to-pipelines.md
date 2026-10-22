# Silver·Gold A 담당자에게 전달할 문안

명세 확인했습니다. 이 기준으로 인프라 연결 준비를 진행하겠습니다.

Spark 제출은 spark-submit 방식입니다. 기본 환경은 Spark 4.2.0 / Python 3.10.12 / Java 21 / Scala 2.13 / Hadoop·S3A 3.5.0 / AWS SDK bundle 2.35.4입니다. 연결 라이브러리를 포함한 기본 이미지는 빌드·합성 실행을 검증했고, 영구 ECR 주소와 이미지 digest는 발행 후 전달드리겠습니다. 추가 Python 패키지가 필요하면 업무 이미지 의존성 목록에 같이 적어주세요.

전용 노드는 t3a.large 한 대분으로, Driver 1개와 Executor 초기 1개·최대 2개의 동적 할당을 준비했습니다. EKS 합성 계산과 Executor 1→2→1 증감은 통과했고 시험 리소스는 내렸습니다. 업무 데이터 성능과 S3 쓰기·Pod Identity는 별도 검증이 필요합니다. 요청 자원은 Driver 250m/1GiB, Executor마다 500m/1.5GiB, 제출기 250m/0.5GiB로 최대 합계 1.5 CPU/4.5GiB입니다. Executor CPU limit/계산 슬롯은 각각 1이며 CPU를 독점 보장하는 것은 아닙니다.

| Pod | CPU request / limit | 메모리 request / limit |
|---|---|---|
| Driver | 250m / 1 | 1GiB / 1GiB |
| Executor 각각 | 500m / 1 | 1.5GiB / 1.5GiB |
| 제출기 | 250m / 500m | 0.5GiB / 1GiB |

Bronze의 orders/, order-items/, payments/는 읽기 전용으로, 제안하신 silver/runtime/trade/와 gold_a/runtime/trade/는 읽기·쓰기로 준비하겠습니다. manifest·완료 기록·current.json은 각 출력 루트 안에 포함하는 것으로 이해했습니다. Bronze 쓰기, 과거 정상 결과 삭제, ground_truth/ 접근은 추가하지 않겠습니다. 쓰기 권한은 덮어쓰기도 가능하므로 run_id별 불변 저장과 공개 참조 갱신은 실행기에서 지켜주세요.

현재 Airflow의 DAG 공급 경로는 main의 infra/platform/airflow/dags/이고 약 60초마다 갱신을 확인합니다. 신규 DAG는 기본 일시정지입니다. 다른 원본 경로를 원하시면 bundle 연결을 먼저 맞추겠습니다. 첫 검증은 수동·동시 1개로 진행하고 Driver 최종 상태·manifest·품질 상태까지 확인하는 방향으로 연결하겠습니다. DAG의 품질 분기·Gold A 갱신 차단·재실행 로직은 담당 코드로 준비 부탁드립니다.

추가로 아래 값이 정리되면 실제 연결을 마무리할 수 있습니다.

1. Gold B와 pipelines namespace 공유 여부와 ServiceAccount 이름. 제출기·Driver·Executor는 역할을 나누는 기준입니다.
2. --config-uri가 가리킬 실행 요청 JSON의 저장 prefix와 첫 고정 객체 경로. 읽기 권한 연결에 필요합니다.
3. 최종 업무 이미지·진입 파일·인자와 Python 패키지 목록. pipelines/spark_batch.py는 구현 전 제안으로 기록했습니다.
4. S3 커미터, 임시 객체 경로와 필요한 삭제·멀티파트 정리 권한.
5. 상품 스냅샷 위치, 첫 검증의 고정 입력 객체/manifest, 기대 건수·금액.
6. Glue 데이터베이스·테이블·뷰 명세와 실행별 공개 방식. current.json만으로 Athena 조회 대상이 바뀌지 않는다는 전제에 동의하며, R6와 조사 에이전트 권한은 따로 연결하겠습니다.

ECR push 담당 계정은 전달해 주신 arn:aws:iam::827913617635:user/de-ai-18로 기록했습니다. Spark Driver·Executor의 S3 접근은 별도 ServiceAccount·Pod Identity 역할로 분리합니다. 추후 개발자 권한을 줄이거나 다른 ARN으로 교체할 수 있고, 계정 교체 시 새 계정의 push 확인 후 기존 권한을 회수하겠습니다. 현재는 계정 확정만 반영했으며 ECR push 권한을 추가 적용한 상태는 아닙니다.

Spark S3 입출력 검증과 Glue/Athena 최종 조회 연결은 나눠 진행할 수 있습니다. 지금은 새 노드를 상시로 올리거나 업무를 실행하지 않고 연결 코드부터 준비하고 있습니다.
