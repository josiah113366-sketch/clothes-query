# 데이터 파이프라인

이 브랜치는 `pipelines/silver/`의 정제 코드와 `pipelines/gold_a/`의 비즈니스 지표 코드를 담는다. Gold A는 선행 Silver 결과를 입력으로 쓴다.

- 입력과 실행 방법은 `pipelines/silver/README.md`를 따른다.
- 거래 Silver는 합의된 컬럼으로 계산 규칙만 구현했다. 실제 주문·결제 Bronze 연결은 샘플 확인 후 진행한다.
- Gold A의 입력과 실행 방법은 `pipelines/gold_a/README.md`를 따른다.
