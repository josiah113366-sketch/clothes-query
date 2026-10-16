# 작업 지시서: sim/product-seed

> 상태: 진행 전 · 브랜치: `sim/product-seed` · 이전 작업: `sim/member-baseline` (같은 방식) · 다음 작업: 트랜잭션 시뮬레이터(주문이 상품을 참조)

## 목표

이미 만들어 둔 **상품 시드 Parquet 2개**를 **로컬 PostgreSQL의 `product_design`, `product_variant` 테이블에 적재**하는 `sim product load` 명령과, 적재 결과를 확인하는 `sim product verify` 명령을 만든다.

```
S3 hm-ecommerce-data/seed_v2/product_design/product_design.parquet   ┐
S3 hm-ecommerce-data/seed_v2/product_variant/product_variant.parquet ┴→ sim product load → Postgres (product_design, product_variant)
```

상품은 회원과 성격이 다르다. **새로 생성하지 않는다.** 팀이 EDA로 정리한 값(Unknown 제외, 가격 지정 완료)이 이미 Parquet에 들어 있고, 이 명령은 **그 파일을 그대로 DB에 옮기고, 옮겨진 것이 원본과 같은지 확인**한다. 랜덤도 시드도 없다.

이 브랜치가 끝나면 `docker compose up -d` → `sim product load` → `sim product verify`로 **상품 2개 테이블이 채워진 로컬 DB**가 생긴다. 같은 명령을 나중에 RDS에도 쓴다 (이번에는 로컬만).

이 지시서는 **자기 완결형**이다. `docs/design/`의 상품 문서(`README_articles`)가 레포에 있으면 함께 읽되, **이 지시서와 어긋나면 추측하지 말고 묻는다.**

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- **커밋하지 않는다.** 파일만 만들고 테스트까지 진행한다. 커밋, push, PR은 사용자가 확인한 뒤 직접 한다.
- 이번에는 **로컬 DB에만** 쓴다. RDS에는 접속하지 않는다.
- **S3는 읽기만 한다.** 쓰기·삭제 코드를 만들지 않는다. AWS 리소스(IAM, 버킷 설정)는 건드리지 않는다. **AWS 계정 ID를 레포의 어떤 파일에도 쓰지 않는다.**
- Python 3.12 가상환경(`simulator/.venv`, WSL)과 WSL Docker를 쓴다. `psql`이 없으므로 DB 확인은 `docker compose exec postgres psql -U sim -d clothes`로 한다.
- 줄바꿈(CRLF/LF)만 바뀐 기존 파일은 건드리지 않고, 필요한 파일만 git 기준(LF)으로 편집한다.
- 로컬 DB의 기존 데이터(회원 10만 명 등)를 건드리지 않는다. 이번 작업은 **새 테이블 2개만 추가**한다.
- 끝난 뒤 상품 테이블을 지울지 남길지 사용자에게 묻는다. 임의로 `down -v` 하지 않는다.

## 시작 전 확인 (Claude가 한다)

- 현재 브랜치가 `sim/product-seed`이고 최신 `main`에서 만들어졌는지, `simulator/`, `db/schema/`가 있는지 확인한다. 아니면 만들지 말고 알린다.
- 이 지시서가 저장소 루트에 있으면 `docs/tasks/sim-product-seed.md`로 옮긴다.
- **Parquet 파일이 어디 있는지 확인한다.** 사용자가 받아 둔 로컬 경로가 기본이다: `simulator/.local/seed_v2/product_design.parquet`, `simulator/.local/seed_v2/product_variant.parquet`. 없으면 만들지 말고 아래 "원본 파일"의 방법을 안내하고 멈춘다.
- `docker compose up -d`로 로컬 Postgres가 떠 있고 `member` 계열 테이블이 그대로인지 확인한다.
- **두 Parquet의 스키마(컬럼 이름·타입)와 행 수를 읽어서 계획에 적는다.** DDL은 이 스키마에서 만든다 (아래 "DDL").

## 원본 파일

| 항목 | 값 |
|---|---|
| 버킷 / 리전 | `hm-ecommerce-data` / `ap-northeast-1` (팀 버킷, 도쿄) |
| 경로 | `seed_v2/product_design/product_design.parquet`, `seed_v2/product_variant/product_variant.parquet` |
| 성격 | 팀 결정이 이미 반영된 시드 (Unknown 제외, 가격 지정, 설명문·이미지 없음). **이 명령은 값을 고치지 않는다** |
| 레포에 커밋 | **하지 않는다.** 원본은 S3가 기준이다. `simulator/.local/`은 `.gitignore`에 있다 |

**로컬 파일이 기본 입력이다.** 사용자가 AWS 콘솔이나 `aws s3 cp`로 받아서 `simulator/.local/seed_v2/`에 둔다 (파일을 받는 일은 사용자가 한다. 이 명령이 자동으로 받지 않는다). 나중에 ECS에서 쓸 때를 위해 `s3://` 주소도 읽을 수 있게 하되, 이번에 **실제 S3 읽기까지 확인하는 것은 선택**이다 (이 사용자 계정에 그 버킷의 읽기 권한이 없을 수 있다. 막히면 알리고 로컬 파일로 진행한다).

## 이번 작업에서 확정된 값

| 항목 | 값 | 출처 |
|---|---|---|
| 테이블 | `product_design`(디자인), `product_variant`(변형). 이름은 Athena의 `hm_seed_v2`와 같다 | 팀 결정 |
| 키 | `product_design.product_code`(bigint), `product_variant.article_id`(**문자열**), `product_variant.product_code`(→ design) | 팀 결정 (기준 키는 번호) |
| 보이는 컬럼 (design) | `product_code, product_type_no, product_type_name, product_group_name, garment_group_no, garment_group_name, index_group_no, index_group_name, design_price` (+ 스크린샷에 안 보이는 컬럼이 더 있으면 Parquet 기준) | Athena 스키마 |
| 보이는 컬럼 (variant) | `article_id, product_code, prod_name, ...` (나머지는 Parquet 기준. 팀 결정상 색은 `colour_group_*`, 무늬·의류 그룹 유지) | Athena 스키마 |
| 적재 범위 | **Parquet의 모든 행·모든 컬럼을 그대로.** 걸러내거나 값을 바꾸지 않는다 | 지시서 기본값 |
| 가격 | `design_price`(원화, bigint)는 시드의 값을 그대로. 규칙(참고): 가장 가까운 …900원으로 반올림, 하한 5,900원 | 팀 결정 |
| 적재 방식 | 두 테이블을 **한 트랜잭션**에서 (design 먼저, variant 나중). 하나라도 실패하면 전체 롤백 | 지시서 기본값 |
| 빈 테이블 규칙 | 테이블에 행이 있으면 **아무것도 넣지 않고 멈춘다.** 삭제·`TRUNCATE` 옵션은 만들지 않는다 | member baseline과 같은 규칙 |

## 만드는 것

### 1. DDL (`db/schema/003_product.sql`)

**Parquet 스키마에서 만든다.** 계획에 컬럼·타입 매핑 표를 적어 사용자 확인을 받는다.

| Parquet 타입 | PostgreSQL 타입 |
|---|---|
| `int64` (bigint) | `BIGINT` |
| `string` | `TEXT` |
| `double` | `DOUBLE PRECISION` |
| `bool` | `BOOLEAN` |
| `timestamp` | `TIMESTAMPTZ` (시간대 없는 `TIMESTAMP`는 쓰지 않는다) |
| 그 밖의 타입 | **임의로 정하지 말고 알린다** |

제약: `product_design.product_code` PRIMARY KEY, `product_variant.article_id` PRIMARY KEY, `product_variant.product_code`는 `product_design.product_code`를 가리키는 FOREIGN KEY, 모든 컬럼 NOT NULL (Parquet에 NULL이 있는 컬럼은 그 컬럼만 NULL 허용으로 하고 알린다). 인덱스는 PK/FK 외에 **추가하지 않는다** (주문 설계 뒤에 필요해지면 그때).

- **이 파일은 `docker-entrypoint-initdb.d`에 마운트되어 있지만, 이미 만들어진 볼륨에서는 다시 실행되지 않는다.** 그래서 지금 DB에는 직접 적용한다: `docker compose exec -T postgres psql -U sim -d clothes < ../db/schema/003_product.sql`. 이 방법을 README에 적는다. (새 볼륨에서는 자동 적용된다.)
- Parquet에 **설명문·이미지·한국어 현지화 컬럼**(예: `detail_desc`)이 있으면 팀 결정(쓰지 않음)과 어긋나므로 **만들지 말고 알린다.**
- 기존 `db/schema/001_*`, `002_*`는 수정하지 않는다.

### 2. 파이썬 (`src/sim/product/`)

| 파일 | 내용 |
|---|---|
| `params.py` | 테이블 이름, 기본 원본 경로, S3 리전(`ap-northeast-1`), 허용 타입 매핑, 확인 기준(가격 규칙 등) |
| `source.py` | Parquet 읽기. 로컬 경로 또는 `s3://` 주소를 받는다 (S3는 `boto3` **읽기만**). 배치(예: 5,000행)로 읽는다. 스키마·행 수를 돌려주는 함수 |
| `load.py` | 적재: 빈 테이블 확인 → 한 트랜잭션 → design `COPY` → variant `COPY`. 요약 반환 |
| `verify.py` | 적재 결과 확인 (아래) |
| `cli.py` | `typer` 하위 앱 `product` (`load`, `verify`). `sim/cli.py`에서 `app.add_typer(product_app, name="product")`로 연결 |

**의존성 추가:** `pyarrow`를 실행용 의존성에 추가한다 (Parquet 읽기). 이 지시서가 허용한 **유일한** 추가다 (`boto3`는 이미 있다). `pyproject.toml`과 `simulator/CLAUDE.md`의 의존성 줄을 함께 고친다. `pandas`는 쓰지 않는다.

**설정 추가:** `SEED_DIR`(기본 `.local/seed_v2`, `simulator/` 기준 상대 경로)을 `common/config.py`와 `.env.example`(더미 값)에 추가한다.

### 3. CLI

```
sim product load   [--source <디렉터리 또는 s3://버킷/seed_v2>] [--dry-run] [--yes]
sim product verify [--source <디렉터리 또는 s3://버킷/seed_v2>]
```

**`load`**
1. 원본 파일 2개를 읽을 수 있는지, 스키마가 DDL과 같은지 확인한다. 다르면 어떤 컬럼이 다른지 알리고 멈춘다.
2. 대상 DB를 `호스트:포트/DB이름`으로만 출력한다. `--yes`가 없으면 `계속할까요? [y/N]`을 묻는다. `--dry-run`이면 DB에 접속하지 않고 **파일 스키마와 행 수만** 보여 주고 끝낸다 (질문 없음).
3. 두 테이블이 모두 비어 있는지 확인한다. 하나라도 행이 있으면 **아무것도 넣지 않고** 이유를 알리고 멈춘다 (로컬이면 "`docker compose down -v` 후 다시" 안내. 단 **회원 데이터도 함께 지워지므로 주의**라는 문장을 포함한다).
4. 한 트랜잭션에서 design → variant 순서로 적재하고 커밋한다.
5. 요약(테이블별 행 수, 소요 시간)을 출력한다. 값(상품 이름 등)은 출력하지 않는다.

**`verify`** (읽기 전용): 항목별 통과/실패 표를 보여 주고 하나라도 실패하면 종료 코드 1. 원본 Parquet와 DB를 **둘 다 읽어서 비교한다.**

| # | 확인 | 기준 |
|---|---|---|
| 1 | 행 수 | 두 테이블 모두 Parquet의 행 수와 같다 |
| 2 | 키 | `product_code`, `article_id` 중복 0, NULL 0 |
| 3 | 참조 무결성 | 모든 variant의 `product_code`가 design에 있다 (고아 0). design 중 variant가 없는 것의 개수는 **보고만** 한다 |
| 4 | `article_id` 형식 | 숫자로만 이뤄지고 길이가 모두 같다 (앞자리 0이 살아 있다) |
| 5 | Unknown 제외 | 이름·그룹 컬럼(`*_name`)에 `Unknown`(대소문자 무시)이 0건 |
| 6 | 가격 규칙 | `design_price` ≥ 5,900 이고 천 단위 나머지가 900. 어긋나는 행 수를 보고하고 0이 아니면 실패 (규칙이 다르게 정해져 있었다면 임의로 고치지 말고 알린다) |
| 7 | 원본과 같은 값 | 컬럼별 집계(숫자 컬럼의 합, 문자 컬럼의 서로 다른 값 개수, 그룹별 행 수)가 Parquet와 DB에서 같다 |
| 8 | 샘플 대조 | 무작위 1,000행(두 테이블 각각)의 모든 컬럼 값이 Parquet와 같다 |

**출력 규칙:** 실패해도 상품 값 전체를 쏟아내지 않는다. 컬럼 이름, 건수, 최대 5개의 키(`product_code`/`article_id`)만 보여 준다.

## 테스트

**단위 테스트 (DB 없이 돈다, 기본 `pytest`에 포함):** 테스트용 작은 Parquet를 `pyarrow`로 임시 폴더에 만들어 쓴다 (실제 시드 파일을 쓰지 않는다).
- Parquet 타입 → PostgreSQL 타입 매핑, 모르는 타입은 오류
- 스키마가 DDL과 다르면(컬럼 추가·누락·타입 다름) 어떤 컬럼인지 알리고 실패
- 허용하지 않는 컬럼(설명문 계열)이 있으면 실패
- `verify` 확인 로직(순수 함수): 정상 → 전부 통과 / 고아 variant → 3번 실패 / `Unknown` → 5번 실패 / 가격 5,800원 또는 끝이 900이 아님 → 6번 실패 / `article_id` 길이 섞임 → 4번 실패 / 값이 하나 다름 → 7·8번 실패
- `--dry-run`은 DB에 접속하지 않는다 (DB 접속 함수를 가짜로 바꿔 호출되지 않음을 확인)

**통합 테스트 (`@pytest.mark.integration`, 로컬 DB 필요):** member baseline과 같은 방식. `DATABASE_URL` 호스트가 `localhost`가 아니면 건너뛴다. **임시 스키마**를 만들고 `db/schema/*.sql`을 적용한 뒤 테스트용 Parquet(수백 행)를 적재하고 `verify`가 통과하는지, 비어 있지 않은 테이블에는 적재를 거부하는지, 중간에 실패하면 **두 테이블 모두 비어 있는지(롤백)** 확인하고 스키마를 지운다.

## 만들지 않는 것

- 상품 데이터 **생성·가공** (가격 계산, Unknown 제거 등). 이미 시드에 반영되어 있다
- 가격 변동·재고, 주문·결제 테이블 (→ 트랜잭션 시뮬레이터)
- Debezium 대상에 상품 테이블 추가, Kafka 토픽, S3 Sink 변경 (**상품 변화를 CDC로 레이크에 보낼지는 팀이 정한 뒤 별도 작업**)
- RDS 접속, Terraform, S3 쓰기
- 테이블 삭제·초기화 옵션, 인덱스 추가 (PK/FK 외)
- 설계 문서 수정

## 작업 순서

**커밋하지 않는다.** 각 단계가 끝나면 그 단계의 테스트를 돌려 확인하고 다음 단계로 간다.

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다.** 계획에 두 Parquet의 스키마·행 수와 DDL 타입 매핑 표를 적는다
2. `db/schema/003_product.sql` + 단위 테스트(타입 매핑·스키마 비교) + `pyarrow` 추가
3. `source.py`, `load.py`, `cli.py`의 `load`(`--dry-run` 포함) + 테스트
4. `verify.py`, `verify` 명령 + 단위·통합 테스트
5. `simulator/README.md`에 `## 상품 적재` 절 추가, `simulator/CLAUDE.md` 의존성 줄에 `pyarrow` 추가
6. "완료 확인"을 **실제로 실행**해서 결과 보고

## 완료 확인

- [ ] `pip install -e ".[dev]"`, `ruff check .`, `ruff format --check .`, `pytest`(단위) 통과
- [ ] 로컬 DB에 `003_product.sql`을 적용 (`\dt`에 `product_design`, `product_variant`가 보이고, 회원 테이블과 행 수 100,000이 그대로)
- [ ] `sim product load --dry-run`이 두 파일의 컬럼·행 수를 보여 주고 DB에 접속하지 않는다
- [ ] `sim product load --yes` 성공. 테이블별 행 수와 소요 시간 보고. 행 수가 Parquet와 같다
- [ ] `sim product verify` → **8개 항목 전부 통과** (3번의 "variant 없는 design 수"는 보고)
- [ ] `sim product load --yes`를 한 번 더 실행하면 **아무것도 넣지 않고 멈춘다**
- [ ] `docker compose exec postgres psql -U sim -d clothes`로 확인: `SELECT count(*) FROM product_design;`, `SELECT count(*) FROM product_variant;`, 그리고 variant를 design과 조인한 개수가 variant 행 수와 같다
- [ ] `pytest -m integration` 통과
- [ ] **(선택)** `--source s3://hm-ecommerce-data/seed_v2`로 실제 S3에서 읽어 같은 결과가 나온다 (권한이 없으면 건너뛰고 알린다)
- [ ] `git status`에 `simulator/.local/`, `.env`, Parquet 파일이 없다. 줄바꿈만 바뀐 기존 파일을 건드리지 않았다. **커밋하지 않았다**
- [ ] 끝나면 **상품 테이블을 남길지 사용자에게 묻는다**

## README 갱신

- `simulator/README.md`: `## 상품 적재` 절 (한 줄 요약, 원본 위치와 로컬로 받는 방법, DDL 적용 방법(기존 볼륨 포함), `load`·`verify` 사용법, 빈 테이블 규칙, 상품은 생성이 아니라 시드 이전이라는 점)
- `simulator/CLAUDE.md`: 의존성 줄에 `pyarrow` 추가 (이 한 줄만)

## 참고: 사용자가 나중에 커밋할 때의 제안 메시지

(Claude는 커밋하지 않는다.)

1. `feat(product): 상품 테이블 DDL 추가`
2. `feat(product): 상품 시드 적재 명령 추가`
3. `feat(product): 상품 적재 결과 확인 명령 추가`
4. `docs(product): 상품 적재 README 갱신`

## 막히면

- 이 지시서의 내용끼리, 또는 설계 문서와 어긋나 보이면 **추측하지 말고 묻는다.**
- 이 지시서에 없는 파일·명령·컬럼이 필요해 보이면 만들지 말고 먼저 이유를 설명한다.
- Parquet의 타입·컬럼이 가정과 다르면(예: 시간대 없는 timestamp, 중첩 타입) **임의로 대안을 정하지 말고** 실제 스키마와 함께 알린다.
- 원본의 값이 팀 결정과 어긋나 보이면(예: `Unknown`이 남아 있음, 가격 규칙 위반) **값을 고치지 말고** 개수와 함께 알린다. 시드를 고치는 일은 이 작업의 범위 밖이다.