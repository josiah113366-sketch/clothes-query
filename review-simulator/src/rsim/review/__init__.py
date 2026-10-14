"""리뷰 생성 흐름.

1. seeds.py      : 말투 예시(시드) 리뷰를 .local/seeds.jsonl 에서 읽는다. (rsim seeds 가 미리 만든 파일)
2. catalog.py    : 리뷰를 달 상품 목록을 만든다. (지금은 시드의 상품명, 나중에 H&M 상품 마스터로 교체)
3. scenario.py   : "어떤 상품에, 몇 점짜리, 어떤 속성을 어떤 감성으로" 쓸지 리뷰 명세(spec)를 만든다.
                   이상 상황(incident)을 켜면 특정 기간·상품에 불만 리뷰가 몰리게 한다.
4. generator.py  : 명세 + 시드 예시를 프롬프트로 묶어 Bedrock(Converse, gemma)에 보내고 리뷰 본문을 받는다.
   verifier.py   : 본문만 다시 라벨링해서 명세와 비교한다(검수 루프). bedrock.py 는 실제 HTTP 호출.
5. sinks.py      : 완성된 리뷰 이벤트를 Kafka / 콘솔 / 파일로 보낸다.
6. run.py        : 위 단계를 묶은 실행 함수 (rsim run ...)
"""
