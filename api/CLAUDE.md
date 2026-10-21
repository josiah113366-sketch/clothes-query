# api/ 작업 규칙

이 문서는 `api/`(업무 API, WAS) 작업에 적용된다. 프로젝트 공통 규칙(Git, 문서, 보안)은 루트 `CLAUDE.md`를 따른다.

## 먼저 읽을 것

1. `docs/tasks/`에서 지금 브랜치의 지시서 (첫 작업: `docs/tasks/api-mvp.md`)
2. `docs/design/api.md` — API 설계 (결정/제안/미정)
3. `api/README.md` — 실행·배포 방법

**설계 문서의 "결정"만 구현한다.** "제안"과 "미정"은 작업 지시서가 기본값을 정해 준 경우만 만든다.

## API가 하는 일

시뮬레이터가 보낸 가입·주문·결제·상태 변경을 **검증해 RDS에 저장**하고, 클릭을 **Kafka `clickstream`에 발행**한다. **얇은 API**다: ID·시각·결제 결과는 시뮬레이터가 정해 보내고 API는 정하지 않는다.

## 지켜야 할 규칙

| 규칙 | 이유 |
|---|---|
| **요청 본문·PII(이름, 이메일, 전화, 생년월일, 비밀번호 해시)를 로그·오류 응답·지표 라벨에 남기지 않는다.** 422 응답도 필드 위치와 오류 종류만 준다 | 레이크와 로그로 PII가 나가지 않는다는 약속 |
| 지표 라벨은 경로 **템플릿**(`/v1/orders/{order_id}`)만 쓴다. ID를 라벨에 넣지 않는다 | 카디널리티·정보 노출 |
| DB 오류는 sqlstate·제약 이름으로만 분류한다 | 값이 오류 메시지에 섞이지 않게 |
| 멱등: 같은 ID에 같은 내용은 200, 다른 내용은 409 `ID_CONFLICT` | 시뮬레이터 재시도 안전 + 버그 노출 |
| 검증은 DB 제약(`db/schema/`)과 같게 한다. DDL은 바꾸지 않는다 | DB가 마지막 방어선 |
| 시각은 시간대가 있는 값만 받고, 응답·Kafka는 UTC `…Z` | Bronze UTC 규칙 |
| 접속 정보(DB, Kafka, 인증서 경로)는 환경 변수·Secret으로만 받고 출력하지 않는다 | 보안 |

## 폴더 구조

```
api/
├── CLAUDE.md, README.md
├── pyproject.toml          # 의존성 버전 고정
├── Dockerfile              # 베이스 digest 고정, 비root
├── src/clothes_api/        # main(앱·로그·지표), config, errors, schemas, store(DB), kafka, cursor, metrics, routes/
├── tests/                  # 단위(가짜 Store), 통합(로컬 Docker), chart 렌더
└── deploy/
    ├── chart/              # Helm: Deployment, Service, 내부 ALB(IngressClassParams·IngressClass·Ingress)
    └── sql/app-account.sql # DB 앱 계정 clothes_app
```

## 명령

```bash
cd api
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest                    # 단위 + chart 렌더(Helm 있으면)
.venv/bin/pytest -m integration     # 로컬 Docker Postgres·Kafka 필요
```

## 하지 말 것

- `db/schema/`를 바꾸지 않는다. 인증·탈퇴·리뷰 API는 설계가 정해질 때까지 만들지 않는다.
- 이미지 태그를 덮어쓰지 않는다(ECR IMMUTABLE). Helm에는 digest로만 넣는다.
- 비밀값, 계정 ID, 엔드포인트를 커밋하지 않는다(`runtime.local.yaml`은 Git 제외).
