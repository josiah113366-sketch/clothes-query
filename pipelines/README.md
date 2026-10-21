# 데이터 파이프라인

이 브랜치는 `pipelines/silver/`의 정제 코드와 `pipelines/gold_a/`의 비즈니스 지표 코드를 담는다. Gold A는 선행 Silver 결과를 입력으로 쓴다.

- 입력과 실행 방법은 `pipelines/silver/README.md`를 따른다.
- 거래 Silver는 펼쳐진 CDC와 공통 YAML 업무 규칙을 지원한다. 실제 AWS 데이터 검증은 별도다.
- Gold A의 입력과 실행 방법은 `pipelines/gold_a/README.md`를 따른다.

공통 YAML 검사기는 `pipelines/format_rules.py`, 규칙 원본은 `docs/contracts/format_rules.yaml`이다. 실행 의존성은 `python -m pip install -r pipelines/requirements.txt`로 설치한다. 현재 연결은 거래 Silver뿐이며 Gold B/리뷰에 자동 적용하지 않는다.
