# 데이터 파이프라인

이 브랜치는 `pipelines/silver/`의 정제 코드와 `pipelines/gold_a/`의 비즈니스 지표 코드를 담는다. Gold A는 선행 Silver 결과를 입력으로 쓴다.

## 공통 결제 지문

`pipelines/payment_fingerprint.py`의 payment_fingerprint(payment)가 결제 업무 필드 9개를 정규화해 payment_content_hash/fingerprint_version을 반환한다. 호출/입력/버전 계약은 [공통 계약](../docs/contracts/README.md#결제-내용-지문-규약--payment-contentv1)을 따른다. 순수 표준 라이브러리 함수이며 추가 패키지는 없다. Silver는 공통 입력 검사 후 원본 시각 문자열로 호출해 정상 결제 결과에 해시·버전을 저장한다. Gold B의 호출·적재 연결은 후속 작업이다.

- 입력과 실행 방법은 `pipelines/silver/README.md`를 따른다.
- 거래 Silver는 펼쳐진 CDC와 공통 YAML 업무 규칙을 지원한다. 실제 AWS 데이터 검증은 별도다.
- Gold A의 입력과 실행 방법은 `pipelines/gold_a/README.md`를 따른다.
- Gold B의 관제용 원장 DDL과 후속 구현 범위는 `pipelines/gold_b/README.md`를 따른다.

공통 YAML 검사기는 `pipelines/format_rules.py`, 규칙 원본은 `docs/contracts/format_rules.yaml`이다. 실행 의존성은 `python -m pip install -r pipelines/requirements.txt`로 설치한다. 거래·회원·클릭 Silver가 연결돼 있으며 실행별 규칙 버전·내용 해시와 격리 rule_id를 기록한다. 리뷰·상품은 자체 검사를 유지한다. Gold B 실행 연결은 별도 담당 범위다.
