# review-analysis/ 작업 규칙

프로젝트 공통 규칙(Git, 문서, 보안)은 루트 `CLAUDE.md`를 따른다. 이 문서는 이 폴더에만 적용된다.

## 지켜야 할 규칙

| 규칙 | 이유 |
|---|---|
| `private/`, `aihub_dataset/`, `aihub_work/` 는 커밋하지 않고, 외부 API(Gemini, Bedrock 등)로도 보내지 않는다 | 실제 후기를 받아 적은 평가셋과 AI Hub 원본(재배포 금지)이 있다 |
| 후기 원문(실제·AI Hub·번역 샘플)을 문서 예시를 포함해 저장소에 올리지 않는다 | 공개 저장소다 |
| 속성 목록(11개)과 점수 척도(−2~+2)는 `docs/absa-label-guide.md`(v3)와 같게 둔다. 바꾸면 `review_analysis/schema3.py`, `score.py`, `deploy/score_batch.py`의 프롬프트를 같이 바꾸고 `python deploy/check_prompt.py`로 일치를 확인한다 | 학습·평가·배치의 프롬프트가 어긋나면 결과가 달라진다 |
| 평가용 후기와 학습용 후기를 섞지 않는다. 학습에 쓴 수집 후기 ID는 `private/collected_half_split.json`에 있고 평가는 `--holdout`으로 뺀다 | 평가 점수가 부풀려진다 |
| AWS 계정 ID, 키, 버킷 이름, 엔드포인트를 코드·문서에 넣지 않는다 | 공개 저장소다 |
| Terraform은 이 폴더에 두지 않는다. `infra/` 규칙(스택, state)을 따라 따로 작성한다 | 한 PR에는 한 영역만 담는다 |
