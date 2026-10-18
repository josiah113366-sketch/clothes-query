# 생성 프롬프트 예시 세트 (ex-vN)

리뷰 생성 시스템 프롬프트의 "예시" 칸을 버전별 파일로 둔다 (`src/rsim/review/examples.py`).
버전별 성능은 `docs/examples-scorecard.md` 에 적는다.

| 파일 | 내용 |
|---|---|
| ex-v0.md | p5.8 때 규칙에서 옮긴 예시 (비교 기준) |
| ex-v1.md | lemin 이 직접 쓴 예시, Gemini 합성 말투 예시 제외. **기본값** (2026-10-18) |

## 형식

- 첫 번째 ```` ```text ```` 코드블록 안의 줄이 프롬프트에 그대로 들어간다. 밖의 글은 메모다.
- 코드블록 밖에 `seed_sources: aihub, handwritten` 처럼 쓰면 명세 앞 말투 예시(.local/seeds.jsonl)를
  그 출처에서만 뽑는다. 없으면 전체(aihub, synth, handwritten).
- 코드블록에 `____` 가 남아 있으면 읽지 않는다(덜 쓴 예시로 Bedrock 비용이 나가지 않게).

## 새 버전 만들기

1. 마지막 파일을 복사해 `ex-v2.md` 처럼 번호를 올리고 고친다. 이미 bench 를 돌린 버전 파일은 고치지 않는다.
2. `rsim bench --yes --n 100 --examples ex-v2` (같은 `--seed` 면 명세가 같아 버전끼리 비교된다)
3. 끝에 나오는 점검표 한 줄을 `docs/examples-scorecard.md` 에 붙인다. 지난 실행은 `rsim scorecard` 로 다시 볼 수 있다.
4. 결과가 좋으면 `.env` 의 `EXAMPLES_VERSION` 을 바꿔 시뮬레이터 기본값으로 쓴다.

실제 쇼핑몰 후기를 옮겨 적은 글은 넣지 않는다. 공개 저장소에 올라가고 Bedrock 으로 전송된다.
