# review-simulator/ 작업 규칙

이 문서는 `review-simulator/` 폴더 작업에 적용된다. 프로젝트 공통 규칙(Git, 문서, 보안)은 루트 `CLAUDE.md`를 따른다.

## 먼저 읽을 것

1. `docs/tasks/` 에서 지금 작업하는 브랜치의 지시서
2. `review-simulator/README.md` — 코드 구조와 실행 방법
3. `review-simulator/docs/prompt-sample.md` — 실제로 보내는 프롬프트

## 리뷰 시뮬레이터가 하는 일

가상 쇼핑몰 상품 리뷰를 Bedrock(gemma)으로 만들어 리뷰와 정답을 **따로** 내보낸다. 기본 흐름은 S3 레이크(`reviews/`, `reviews_truth/`), 실험용으로 Kafka 토픽 두 개(`reviews.raw`, `reviews.truth`)도 있다.
무엇을 쓸지(명세 = 정답 라벨)는 코드가 정하고, 문장만 LLM 이 쓴다. 검수 모델이 본문을 다시 라벨링해서 명세와 비교한다.

주문 기반 실행(`--source orders --date D`)은 결제 후 0~7일 뒤 리뷰(2026-10-21 에 1~14일 → 0~7일, 당일 포함)를 만들어 **S3 에 날짜(dt)별로 바로 쓴다**(`--sink lake`).
RDS 에는 넣지 않는다(2026-10-14 lemin 결정). 주문은 로컬 파일(`--source orders`) 또는 RDS orders 테이블(`--source rds`, 2026-10-21, 읽기만)에서 읽는다.
정답 라벨은 `reviews_truth/` 에 따로 쓴다.
직접 작성한 테스트 리뷰는 `rsim inject` 로 같은 날짜 파티션에 `part-manual-<입력 파일 이름>.jsonl` 로 넣는다(2026-10-16, `review/inject.py`).

`simulator/`(회원·행동, RDS 에 씀)와는 따로 개발·실행한다. 서로 import 하지 않고, 데이터는 레이크(S3)로 주고받는다.

## 지켜야 할 규칙

| 규칙 | 이유 |
|---|---|
| **`.local/` 의 파일(시드, 생성 리뷰, 벤치 결과)은 커밋하지 않는다.** 저장소에 리뷰 원문을 싣지 않는다(문서 예시 포함) | 시드에 AI Hub 원문(재배포 금지)이 있고, 공개 저장소다 |
| `review-analysis/private/` 자료는 어떤 경로로도 읽거나 Bedrock 으로 보내지 않는다 | 실제 후기를 받아 적은 내부 평가셋이다 |
| Bedrock API 키는 `.env` 에만 둔다. 로그·오류 메시지·문서에 넣지 않는다 | 보안 |
| **Bedrock 을 실제로 부르는 실행(`rsim run --llm bedrock`, `rsim bench --yes`, `rsim verify-eval --yes`)은 사용자가 승인한 뒤에만 한다** | 비용이 든다 |
| 난수는 `common/rng.py` 의 시드 고정 난수만 쓴다. 전역 `random`, `uuid.uuid4()` 를 직접 쓰지 않는다 | 같은 시드면 같은 명세·ID 여야 한다 |
| 속성 목록은 감성분석 라벨 가이드(v3, 11개)와 같게 둔다. 바꾸면 `taxonomy.py` 와 두 프롬프트를 같이 바꾼다 | 정답 라벨을 감성분석 모델 평가에 그대로 쓴다 |
| 프롬프트를 바꾸면 `PROMPT_VERSION`(생성) 또는 `VERIFIER_PROMPT_VERSION`(검수)을 올리고 `docs/prompt-sample.md` 를 다시 뽑는다 | 어떤 프롬프트로 만든 리뷰인지 정답 이벤트에 남는다 |
| 시각은 시간대 정보가 있는 값으로 만든다 | `simulator/` 와 같은 기준 |

ECS 실행(v0.2.0)은 `deploy/` 스크립트로 한다(`deploy/README.md`). 로컬과 같은 `rsim` 명령만 쓰고 기능 차이를 두지 않는다. 버전별 차이는 `CHANGELOG.md`.

## 개발 환경과 명령

- Python 3.12, 로컬 Kafka 는 Docker Compose 다.
- 의존성: 실행용 `boto3`(S3 저장만), `confluent-kafka`, `psycopg`(RDS 주문 읽기만, `--source rds`), `python-dotenv`, `typer` / 개발용 `moto`(가짜 S3·ECS 등, 배포 스크립트 테스트), `pytest`, `ruff`. Bedrock 호출에는 SDK 를 쓰지 않는다.

```bash
cd review-simulator
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check . && ruff format --check .
pytest                       # Bedrock·Kafka 없이 돈다
rsim run --llm fake --sink stdout --count 5
```

## 코드 작성 규칙

- 타입 힌트를 쓴다. `ruff`(check, format)를 통과해야 한다.
- 주석은 한국어로 자세히 남긴다(무엇을, 왜, 어디를 바꾸면 되는지). 조정할 수치는 파일 상단 상수나 `.env` 에 모은다.
- 생성·검수 로직은 Bedrock 없이 도는 단위 테스트를 같이 만든다(가짜 생성기·가짜 검수 호출 사용).

## 절대 하지 말 것

- `main`에 직접 커밋하지 않는다. push와 PR은 사용자 확인 후에 한다.
- 비밀값, 계정 ID, 엔드포인트, 리뷰 원문 파일을 커밋하지 않는다.
- `simulator/` 파일과 `infra/` 의 다른 스택은 이 폴더 작업에서 고치지 않는다. 리뷰 시뮬레이터 자기 AWS 리소스는 `infra/modules·stacks/ecs-review-simulator` 에 두고 담당자가 apply 한다(2026-10-18 lemin).
