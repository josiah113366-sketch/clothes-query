"""clothes-query 리뷰 시뮬레이터 (rsim).

가상 쇼핑몰 상품 리뷰를 Amazon Bedrock(google.gemma-3-12b-it)으로 만들어 S3 레이크(지금은 로컬 폴더)나 Kafka 로 보낸다.
무엇을 쓸지(상품·별점·속성·감성)는 코드가 정하고, 문장만 LLM 이 쓴다. 그래서 모든 리뷰에 정답 라벨이 붙는다.

패키지 구성
-----------
common/  설정(.env), 시드 고정 난수
review/  리뷰 명세 → 생성 → 검수 → 전송 (실행 흐름은 review/run.py)
bench/   소량 실행으로 비용·검수 결과 확인, 검수 모델 정확도 측정
seeds_prep.py  말투 예시(시드) 파일 만들기
cli.py   rsim 명령 진입점
"""

__version__ = "0.1.0"

# 리뷰 메시지 스키마 버전. 이벤트 JSON 구조를 바꾸면 이 값을 올려서
# 소비자(컨슈머) 쪽이 버전별로 다르게 처리할 수 있게 한다.
# v2 (2026-10-14): order_id, purchased_at, option_size, option_color, has_photo, emitted_at 추가
SCHEMA_VERSION = "review.v2"

# 정답(학습·채점용) 메시지의 스키마 버전. 리뷰 메시지와 따로 관리한다.
# v2 (2026-10-14): order_id 추가
TRUTH_SCHEMA_VERSION = "review_truth.v2"
