# review-analysis

의류 후기를 **속성별 점수(−2~+2)**로 분석하는 모델의 학습·평가·배치 실행 코드다. 속성은 11개(재질·촉감, 사이즈·핏, 색상·디자인, 품질·내구성, 가격·가성비, 냄새, 세탁·관리, 활용성·사용감, 배송, 포장, 교환·환불·CS)이고, 기준은 `docs/absa-label-guide.md`(v3)다.
모델은 EXAONE-3.5-2.4B-Instruct에 LoRA를 붙인 것이다. 3분류(긍정·부정·중립) 버전과 점수 버전을 모두 만들었고, 이후 기준 모델은 **점수 버전**이다.

## 의존하는 것
- `review-simulator/`가 만드는 리뷰의 정답 라벨은 이 폴더의 라벨 가이드(v3, 11개 속성)와 같아야 한다. 속성 목록은 `review_analysis/schema3.py`.
- 로컬 GPU(학습·평가). 배치 실행은 AWS SageMaker Processing Job(`deploy/`). 인프라(Terraform)는 이 폴더에 두지 않고 `infra/` 규칙에 따라 따로 올린다.

## 이 저장소에 없는 것 (로컬 전용, `private/` 등)
- 실제 후기를 받아 적은 평가셋·수집 후기, 학습된 어댑터, 합친 모델(약 5GB)은 올리지 않는다.
- AI Hub 원본(`aihub_dataset/`)과 그 파생물(`aihub_work/`)은 재배포할 수 없어 올리지 않는다.
- 후기 원문이 나오는 노트북 출력, 원문 샘플(parquet), 화면(HTML)도 올리지 않았다. 그 내용을 설명한 목록은 `archive/README.md`에 있다.

## 폴더
| 위치 | 내용 |
|---|---|
| `review_analysis/` | 라벨 스키마(`schema3.py`), 점수 규칙(`score.py`), 합성 데이터(`absa_synth*.py`), AI Hub 변환(`aihub.py`), 반어 보정(`synth_relabel.py`), 평가셋 분할(`heldout.py`) |
| `lora_train.py`, `lora_train_score.py` | 3분류 / 점수 LoRA 학습 |
| `eval_v3.py`, `evaluate_score.py` | 3분류 / 점수 평가 (`--holdout`으로 학습에 쓴 수집 후기 제외) |
| `deploy/` | 점수화 배치 스크립트(`score_batch.py`), 프롬프트 검사, 모델 업로드, SageMaker 작업 실행 |
| `docs/` | 라벨 가이드 v3, AI Hub 라벨 비교, MLflow 검토, GPU 머신 실행 안내 |
| `data/absa_pilot/` | 학습·평가가 읽는 합성 데이터와 Gemini 재추출 캐시 |
| `archive/` | 지난 시험 결과 보관과 시간순 목록 |
| `docs/legacy-pipeline-README.md` | 초기 파이프라인(번역·별점 분류) 설명 |

## 실행 (GPU 머신)
```bash
python -m venv .venv-llm && .venv-llm/Scripts/python -m pip install -r requirements-llm.txt
HF_HUB_OFFLINE=1 python lora_train_score.py --aihub 3000 --tag s2c --relabel --collected-train
HF_HUB_OFFLINE=1 python evaluate_score.py --models 2.4b_score_s2c --sets human --holdout
python deploy/check_prompt.py                      # 배포 프롬프트가 학습·평가용과 같은지 확인
python deploy/score_batch.py --model-dir <합친 모델 폴더> --input 후기.csv --output 점수.csv
```
- 입력 CSV는 `review_id,text`, 출력은 `review_id,aspect,score`(속성별 한 행)다.
- 학습·평가에는 `private/`의 평가셋이 필요하다. 이 저장소에는 없으므로 담당자에게 받는다.

## 측정 결과 요약 (평가 전용 99건, 2026-10-15 기준)
- 점수 모델 s2c: 탐지 F1 0.870, MAE 0.256, QWK 0.918.
- 3분류 모델 v3c: 탐지 F1 0.859, 감성 일치율 92.5%.
- 평가셋이 99건이라 작은 차이는 우연일 수 있다. 배송·포장·교환·환불·CS는 평가셋의 정답 수가 적어 재현율이 낮게 나온다.
- SageMaker(ml.g4dn.xlarge, 도쿄)에서 합성 후기 1,000건을 점수화하는 데 작업 전체 약 27분이 걸렸다(고정 시간 약 5분 포함). 정확도 검증이 아니라 시간 측정이다.
