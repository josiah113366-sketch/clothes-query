상태: 완료

# Silver 파이프라인 통합

브랜치: `silver/pipelines`. `main`을 기준으로 이미 검증한 회원·리뷰·거래 Silver 파일만 모은다. Gold A 코드와 테스트는 `gold-a/metrics` 브랜치로 분리한다.

## 입력과 남은 연결

- 회원: 실제 초기 Bronze 스냅샷으로 `members_current` 생성 확인. 이후 변경·탈퇴 이벤트 검증은 남았다.
- 리뷰: 운영 `reviews/` JSONL을 KST 작성일별로 정제하고 날짜 범위 재처리한다.
- 거래: 합의된 주문·주문상품·결제 컬럼의 순수 계산 규칙을 구현했다. 실제 CDC 봉투와 S3 Bronze 연결은 샘플 확인 후 진행한다.

## 완료 확인

`python -m pytest pipelines/silver/tests -q -p no:cacheprovider --basetemp pipelines/silver/.local/pytest-branchsplit`로 기존 Silver 동작을 확인한다. 거래 계산은 Gold A 브랜치의 연결 테스트에서 함께 확인한다.
