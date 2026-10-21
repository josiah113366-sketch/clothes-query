# 패치노트 (review-simulator)

버전은 `src/rsim/__init__.py` 의 `__version__` 이다. ECS 이미지 태그는 `<버전>-<커밋 7자리>` 이고(`deploy/deploy.py`),
같은 태그로 다시 올릴 수 없다. 기능이 바뀌면 버전을 올리고 여기에 한 칸을 추가한다.
프롬프트 버전(`PROMPT_VERSION`, `VERIFIER_PROMPT_VERSION`)과 예시 세트(`EXAMPLES_VERSION`)는 따로 올리고, 바뀌면 여기에도 적는다.

| 구분 | 뜻 |
|---|---|
| 추가 | 새 기능·명령·스크립트 |
| 변경 | 같은 입력에 결과가 달라지는 변경 (리뷰 분포, 프롬프트, 기본값) |
| 실행 환경 | 기능은 같고 어디서·어떻게 도는지만 바뀜 |

## 0.3.0 (2026-10-21)

- 추가: `rsim run --source rds` — 리뷰 시뮬레이터가 **RDS orders 테이블**을 읽는다(lemin 결정).
  업무 API 가 RDS 에 저장한 주문 중 결제가 끝난 주문(상태 PAID·SHIPPED·DELIVERED, 결제 SUCCESS)의 **주문 항목 하나에 리뷰 하나**를 단다.
  결제 후 1~7일 규칙과 날짜(UTC) 파티션 덮어쓰기는 `--source orders` 와 같다.
- 추가: 프롬프트를 RDS 값으로 만든다. 상품명(prod_name), 상품 종류(product_type_name), 색상(colour_group_name), 무늬(graphical_appearance_name)는
  `product_info` 로(p5.7 형식 그대로, `PROMPT_VERSION` 변경 없음), 회원 연령대(members.age_band)는 `age_group` 으로 들어간다.
  리뷰의 order_id·member_id·product_id 가 RDS 값(uuid, article_id)이라 레이크에서 거래 데이터와 바로 조인된다. 리뷰 컬럼(review.v2)은 그대로다.
- 추가: 설정 `ORDERS_DATABASE_URL`(.env 또는 ECS Secret), 의존성 `psycopg[binary]`. 개인정보 컬럼(이름·이메일·전화)은 읽지 않는다.
- 그대로: `--source orders`(JSONL 가짜 주문)와 `random` 은 결과가 바뀌지 않는다.
- 아직: ECS 태스크는 여전히 가짜 주문으로 돈다. ECS 에서 `--source rds` 로 돌리려면 RDS 로 가는 네트워크(보안 그룹)와 접속 주소 Secret 이 필요하다.

## 0.2.1 (2026-10-21)

- 변경: 결제 후 리뷰까지 기간 기본값을 1~14일에서 **1~7일**로 좁힘(`REVIEW_DELAY_MAX_DAYS` 14 → 7, lemin 결정: 프로젝트 기간에 맞춤).
  같은 주문이라도 리뷰 날짜가 달라지므로, 이미 만든 날짜를 다시 돌리면 그 날짜에 걸리는 주문이 바뀐다.
  `.env` 에 `REVIEW_DELAY_MAX_DAYS=14` 를 직접 적어 두었다면 그 값이 우선한다.

## 0.2.0 (2026-10-18, 브랜치 sim/review-ecs)

로컬과 같은 기능을 AWS ECS Fargate 에서 돌린다. **리뷰를 만드는 방식은 0.1.0 과 같다** (지시서 특례: 기능 변경 없음).

- 실행 환경: ECS Fargate 태스크로 하루치 실행. 가짜 주문(`rsim orders-fake`) → 어제(UTC) 리뷰(`rsim run --source orders --sink lake`)
  → 팀 S3 `bronze/reviews/year=/month=/day=/`. 진입점 `deploy/container/entrypoint.sh`.
  가짜 주문은 고정 시작일(2026-10-01)부터 만들어서 같은 날짜를 다시 돌려도 같은 주문·같은 리뷰 ID 로 덮어쓴다.
- 실행 환경: AWS 리소스(ECR, ECS 클러스터, IAM 역할, Secret, 꺼진 예약 실행, 로그, 대시보드)는 `infra/stacks/ecs-review-simulator`.
- 추가: 배포·운영 스크립트 `deploy/` (secret, deploy, onoff, switch, status, run_incident, run_inject, check_access).
- 추가: Windows PowerShell 스크립트 `scripts/*.ps1` (같은 기능을 PowerShell 에서 호출, Terraform init·plan·apply 포함).
- 추가: `INCIDENTS_PATH` 에 `s3://버킷/키` 를 줄 수 있다(읽기 경로만 넓힘. 로컬 경로 동작은 그대로).
- 추가: 관제. CloudWatch 대시보드(실행별 리뷰 수·토큰·추정 비용, 태스크 종료 기록, 오류), `deploy/status.py`.
- 차이: ECS 에서는 정답 라벨(`reviews_truth`)을 S3 에 쓰지 않는다(컨테이너 안에만 쓰고 버림). 2026-10-18 lemin 결정: 차후 개선.
- 차이: ECS 첫 배포의 리뷰 작성 비율은 `REVIEW_RATE=0.1`(하루 약 100건). `deploy/switch.py high` 로 1,000건.

## 0.1.0 (2026-10-13 ~ 2026-10-18, sim/review-baseline · sim/review-product-import)

로컬(Windows + Docker Kafka) 기준 첫 버전.

- 추가: 코드가 명세(상품·별점·속성·감성 = 정답 라벨)를 정하고 Bedrock `google.gemma-3-12b-it`(도쿄)이 문장만 쓴다.
  검수 모델이 다시 라벨링해 다르면 1번 재생성, 그래도 다르면 버린다.
- 추가: 주문 기반 실행(결제 후 1~14일 뒤 리뷰, 날짜별 덮어쓰기), S3 레이크 저장(Hive 날짜 파티션), Kafka 토픽 2개(실험용).
- 추가: `rsim inject`(직접 쓴 테스트 리뷰), 이상 상황(incidents: 특정 상품·카테고리 불만 급증), 상품 정보 프롬프트 반영.
- 추가: `rsim bench`·`rsim scorecard`(예시 세트 성능 점검표), 예시 세트 파일화(`data/examples/ex-vN.md`).
- 변경: 생성 프롬프트 p5.8, 기본 예시 세트 ex-v1(2026-10-18), 중립 감성 비율 약 5%(2026-10-16).
