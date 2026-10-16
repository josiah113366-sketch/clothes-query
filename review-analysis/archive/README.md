# 지난 시험 결과 보관 (archive)

이전 시험에서 나온 **HTML 화면, CSV 표, 후기 원문 샘플, 번역 결과**를 시험별 폴더에 모아 둔 곳이다. 지금 쓰는 모델(EXAONE LoRA 점수 모델)의 학습·평가에는 필요하지 않다. 코드나 새 결과가 이 파일들에 의존하지 않도록 정리했고, 다시 돌려 볼 필요가 있을 때만 참고한다.

**날짜 읽는 법.** 폴더 이름 앞의 날짜는 파일이 git에 처음 올라간 날(최초 커밋일)이다. `2026-10-08` 폴더의 시험은 Colab 노트북에서 그 전에 실행한 것이라 실제 실행일은 이보다 이를 수 있고, 정확한 날짜 기록은 남아 있지 않다. 파일 수정 시각은 저장소를 내려받은 시각이라 쓰지 않았다.

## 시간순 목록

| 순서 | 폴더 | 한 줄 요약 | 만든 코드 |
|---|---|---|---|
| 1 | `2026-10-08_en-star-rating/` | 영어 아마존 후기로 별점 5단계 분류 모델 비교 | 노트북 `amazon_sentiment_finetune.ipynb`, `run.py report` |
| 2 | `2026-10-08_ko-translation-compare/` | 영→한 번역 모델 비교와 번역 결과 | `run.py translate / compare`, `review_analysis/mt_compare.py` |
| 3 | `2026-10-08_ko-star-rating/` | 한국어 번역문으로 같은 별점 분류를 다시 학습·비교 | 노트북 `amazon_ko_translate_sentiment_v2.ipynb`, `run.py report / overview` |
| 4 | `2026-10-08_absa-pilot-v1/` | 속성 기반 감성분석(ABSA) 첫 시험: 영어 vs 번역문 일관성, 합성 후기 불일치 | `run.py absa lang / synth` |
| 5 | `2026-10-08_absa-synth-small-runs/` | 합성 후기를 소량(100~300건)으로 Gemini 재추출해 본 시험 | `run.py absa synth --n ...` |
| 6 | `2026-10-11_absa-eval-and-en-labels/` | 사람 평가 11건 채점 캐시, 영어 아마존 후기 1,000건 라벨 | `run.py absa eval`, `run.py absa-train --en` |
| 7 | `2026-10-12_absa-synth-v2/` | 합성 후기 v2 1,000건과 재추출 결과 | `review_analysis/absa_synth2.py` |
| 8 | `2026-10-12_lora-vs-gemini/` | LoRA(EXAONE 2.4B)와 Gemini 비교 화면 | `llm_compare_report.py` |
| 9 | `2026-10-13_score-synth-v1/` | 점수(−2~+2) 방식의 첫 합성 데이터(초기 점수 규칙). 이후 v2로 교체 | `review_analysis/absa_synth_score.py` |

## 1. `2026-10-08_en-star-rating/` — 영어 별점 5단계 분류

아마존 의류 후기(영어)에서 별점 1~5를 맞히는 사전학습 감성 모델을 비교한 첫 시험이다. 데이터 출처는 `McAuley-Lab/Amazon-Reviews-2023`이다(`review_analysis/config.py`의 `DATA_BASE_URL`). 기간은 2020-10-01~2023-10-01이고, Fashion과 Clothing·Shoes 두 범주에서 별점마다 2,600건씩 뽑았다.

| 파일 | 내용 |
|---|---|
| `sample_raw.parquet` | 샘플링한 후기 원문 26,000건(영어). 이후 번역·학습의 입력이다 |
| `sample_stats.csv` | 범주별 훑은 줄 수, 기간 내 별점 분포, 추출 건수 |
| `metrics_summary.csv` | 영어 모델별 정확도, Macro-F1, ±1점 정확도, MAE, 감성 정확도, 학습 시간 |
| `metrics_by_item.csv` | 모델별·항목별 세부 지표 |
| `predictions_test.csv` | 테스트 3,001건의 모델별 예측 |
| `dashboard.html` | 위 결과를 한 화면으로 본 보고서(혼동행렬, 원래값/예측값 표) |

## 2. `2026-10-08_ko-translation-compare/` — 영→한 번역 후보 비교

영어 후기를 한국어로 옮길 번역 모델을 비교했다. 감성이 유지되는지, 극성이 뒤집히는지, 역번역 품질, 속도, 실패율을 종합 점수로 냈다.

| 파일 | 내용 |
|---|---|
| `mt_compare.csv` | 번역 모델 9개 비교표. 종합 점수: Gemini-3.5-FlashLite 70.0, NHNDQ-NLLB-en2ko 65.9, NLLB-1.3B 65.8, Gugugo-7B 65.7, NLLB-600M 63.1, M2M100-1.2B 62.9, Qwen2.5-7B 60.5, M2M100-418M 59.1, Rosetta-4B 36.8 |
| `mt_samples.csv` | 후보별 원문과 번역문 예시 |
| `translations/*.parquet` | 번역 결과 캐시(열: `review_id`, `ko`). `NHNDQ-NLLB-en2ko`와 `NLLB-1.3B`는 2만 건 전체, 나머지는 비교용 300건. `OPUS-MT-big`은 비교에서 빠진 후보의 300건 |
| `translations/_speed.json` | 후보별 번역 속도 기록 |

이 시험에서 한국어 별점 모델 학습(3번)은 `NHNDQ-NLLB-en2ko` 번역문을 썼다. NLLB 계열은 비상업 라이선스다(`config.py`의 `license` 항목).

## 3. `2026-10-08_ko-star-rating/` — 한국어 번역문으로 별점 분류

2번의 번역문으로 한국어 모델을 학습해서, 영어 원문 결과(1번)와 비교했다.

| 파일 | 내용 |
|---|---|
| `metrics_summary.csv` | 영어(EN)·한국어(KO) 모델 9개의 정확도, Macro-F1, MAE 등 |
| `metrics_by_item.csv` | 모델별·항목별 세부 지표 |
| `metrics_en_vs_ko.csv` | 같은 모델에서 영어 원문과 번역문의 정확도·감성 정확도 변화. 예: nlptown-mBERT 정확도 58.1 → 53.5(−4.6%p) |
| `predictions_test.csv` | 테스트 3,001건의 영어 원문, 한국어 번역, 모델별 예측 |
| `dashboard.html` | 별점 모델 상세 화면 |
| `overview.html` | 전체 결과 한 화면(번역 비교, 감성 모델, ABSA 시험, 추후 진행사항). 실제 후기 원문은 없다 |

## 4. `2026-10-08_absa-pilot-v1/` — ABSA 첫 시험 (Gemini 추출)

속성 기반 감성분석을 Gemini로 시험한 첫 결과다. 속성을 먼저 뽑고(`absa.py`), 영어 원문과 번역문의 결과가 같은지 비교했다.

| 파일 | 내용 |
|---|---|
| `consistency.csv` | 영어 원문 대 번역문 일관성. 예: EN vs NHNDQ-NLLB-en2ko는 탐지 F1 0.846, 감성 일치율 0.933 |
| `synth_review_queue.v1.csv` | 합성 한글 후기를 Gemini로 다시 뽑았을 때 지시한 속성과 추출 결과가 달랐던 51건 목록 |

## 5. `2026-10-08_absa-synth-small-runs/` — 합성 후기 소량 재추출

합성 한글 후기를 100·200·300건씩 만들어 Gemini로 다시 뽑아 보고, 지시한 속성과 추출 결과가 얼마나 일치하는지 본 초기 시험이다. 지금 학습에 쓰는 재추출 캐시는 1,000건짜리(`data/absa_pilot/synth_pred_1000.v2.json` 등)라서 이 소량 결과는 쓰지 않는다.

| 파일 | 내용 |
|---|---|
| `synth_pred_200.json`, `synth_pred_300.v1.json` | 프롬프트 v0·v1 시기의 200·300건 재추출 결과 |
| `synth_pred_100.v2.json`, `synth_pred_300.v2.json` | 프롬프트 v2(규칙 R1~R21 확정 후)의 100·300건 재추출 결과 |

## 6. `2026-10-11_absa-eval-and-en-labels/` — 평가 채점 캐시와 영어 라벨

| 파일 | 내용 |
|---|---|
| `human_eval_11_329b4c72.v1.json`, `.v2.json` | 사람이 라벨한 평가 11건을 Gemini로 추출한 채점 캐시(v1·v2 프롬프트). 라벨만 있고 후기 원문은 없다 |
| `train_en_1000.v2.json` | 영어 아마존 후기 1,000건에 Gemini가 붙인 속성·감성 라벨. 작은 모델(KLUE-RoBERTa) 증류와 `--en` 학습 옵션용(지금은 쓰지 않음) |

## 7. `2026-10-12_absa-synth-v2/` — 합성 후기 v2

| 파일 | 내용 |
|---|---|
| `synth_v2_review.csv` | 실제 후기 특성(구어체, 짧은 길이, 구매정보 등)을 반영해 만든 합성 후기 1,000건. 각 건에 정답, Gemini 재추출, 학습 사용 여부(O 685건, X(불일치) 315건), 말투·길이 설정이 있다 |

## 8. `2026-10-12_lora-vs-gemini/` — LoRA 대 Gemini 비교

| 파일 | 내용 |
|---|---|
| `llm_compare.html` | 로컬 LoRA(EXAONE 2.4B)와 Gemini의 비교 화면. 저장된 결과만 읽어 만든 것이라 GPU·API 없이 다시 만들 수 있다(`llm_compare_report.py`) |

## 9. `2026-10-13_score-synth-v1/` — 점수 방식 첫 합성 데이터

3분류 대신 −2~+2 점수로 매기는 방식(score 모델)을 처음 시험할 때 만든 합성 데이터다. 약한 만족·불만의 점수 규칙이 사람 라벨과 달라서(예: 일반 칭찬은 +2여야 함) 규칙을 고치고 v2로 다시 만들었고, 지금은 v2만 쓴다.

| 파일 | 내용 |
|---|---|
| `synth_score.v1.json` | 학습용 합성 후기와 점수 정답(초기 점수 규칙) |
| `synth_score_eval.v1.json` | 평가용 합성 후기와 점수 정답 |
| `synth_score_pred.v1.json`, `synth_score_eval_pred.v1.json` | 위 두 파일을 Gemini로 다시 뽑은 재추출 결과(정답과 일치하는 후기만 학습에 쓰는 데 사용) |

## 다시 돌릴 때 알아둘 것

- 번역 캐시와 샘플 원본은 이 폴더 안으로 옮겼고, `review_analysis/config.py`의 `TRANS_DIR`, `SAMPLE_DIR`가 이 위치를 가리킨다. `check_split.py`와 샘플 불러오기가 정상 동작하는 것을 확인했다.
- `run.py report`, `overview`, `llm_compare_report.py`는 결과를 예전 위치(`voc_amazon_ko/`, `voc_amazon_finetune/`)에 다시 쓴다. 그 결과는 이 보관본과 따로 생기며, 입력으로 읽는 표(`metrics_*.csv` 등)는 이 보관본에서 가져오도록 경로를 아직 바꾸지 않았다. 다시 만들려면 파일을 원래 자리로 복사하거나 경로를 고쳐야 한다.
- 영어·한국어 별점 모델의 결과 JSON(`results/`, `metrics_full.json`)과 번역 Gemini 별점 판정(`mt_llm_star.json`)도 각 시험 폴더로 옮겼다. 지금 학습·평가가 읽는 합성 데이터와 재추출 캐시는 `data/absa_pilot/`에 있다. `voc_amazon_finetune/`, `voc_amazon_ko/` 폴더는 비웠고 옛 명령을 다시 돌리면 그 위치에 새로 생긴다.
- 5·6번 폴더의 파일은 현재 학습·평가 코드가 읽지 않는다. 옛 명령(`absa eval` 등)을 다시 돌리면 캐시가 없어 Gemini를 다시 부르게 되므로, 필요하면 파일을 `data/absa_pilot/`로 되돌린 뒤 실행한다.
- 후기 원문 샘플(`sample_raw.parquet`)과 번역 결과는 Amazon Reviews 2023 데이터에서 나온 것이다. 외부 저장소에 올리기 전에 재배포 조건을 확인해야 한다(아직 확인하지 못했다).
