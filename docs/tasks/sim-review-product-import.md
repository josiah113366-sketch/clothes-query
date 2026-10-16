# 작업 지시서: sim/review-product-import

> 상태: 진행 중 · 브랜치: `sim/review-product-import` · 다음 작업: `(미정)`

## 목표

실제 상품 정보(product_id 로 가져오는 상품 데이터)를 리뷰 생성에 연결해, 그 상품에 어울리는 리뷰를 만든다.
그리고 현재 많이 늘어난 프롬프트 규칙 지시사항(13건의 Rule)을 줄여 성능을 늘린다.


## 먼저 읽을 것

- 루트 `CLAUDE.md`, `review-simulator/CLAUDE.md`
- `docs/tasks/sim-review-baseline.md` (이전 브랜치)
- `review-simulator/README.md`, `review-simulator/docs/prompt-sample.md`, `review-simulator/docs/review-columns.md`

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 상품 정보는 프롬프트에만 쓰고 리뷰 컬럼(review.v2)은 늘리지 않는다 (2026-10-16)
- category 는 받지 않는다. 상품 정보만으로 리뷰를 쓴다 (2026-10-16)
- 사이즈(option_size)는 추후 order 테이블 값을 쓴다. 지금은 추정값 (2026-10-16)
- 프롬프트의 규칙 지시사항 중 병합 가능한 부분이 있으면 병합하여 지시사항을 줄이고 최대한 예시로 보여줄 수 있는 부분으로 대체한다.

## 시작 전 확인 (Claude가 한다)

- 브랜치 `sim/review-product-import`, 선행 커밋 `d414f8f`(상품 정보 프롬프트 준비, p5.7)
- (필요한 도구·데이터는 lemin 작성)

## 만드는 것

### 1. 지시사항 다이어트
- 지시사항 중 병합 가능한 부분을 확인하여 줄임
- 규칙 간의 충돌을 점검하여 성능을 떨어뜨리는 부분이 없는 지 점검

### 2. 예시 구성
- 현재 구성되어 있는 예시를 더 명확하고 각 상황을 잘 설명할 수 있는 리뷰 예시 구성(사람이 직접 가상의 리뷰를 작성)
- 예시 구성 별 버전관리 및 성능 점검표 정리

## 만들지 않는 것
- git commit (무조건 사람의 확인을 받고 commit 단위가 되었다고 판단될 경우 commit 메시지 제안만 진행)
- Bedrock API 활용한 리뷰 예시 생성 (기존에 생성 요청하여 만들었던 예시 대신 사람이 직접 작성하도록 변경)

## 작업 순서

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다**
2. (단계)
3. "완료 확인"을 실행하고 결과 보고

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다.

- [ ] `ruff check . && ruff format --check .`
- [ ] `pytest`
- [ ] (확인 항목)

## README 갱신

- `review-simulator/README.md`
- (갱신할 README 목록)
