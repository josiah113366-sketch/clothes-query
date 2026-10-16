# 아마존 리뷰 감성 + 영→한 번역 실험 (노트북 → 로컬 프로젝트)

> **2026-10-16 정리.** `voc_amazon_finetune/`, `voc_amazon_ko/`의 HTML·CSV·결과 JSON·원문 샘플·번역 결과는 `archive/`로 옮겼고(`archive/README.md` 참고), 지금 학습·평가가 읽는 합성 데이터와 재추출 캐시는 `data/absa_pilot/`에 있다. 아래의 옛 파이프라인(번역·별점 분류) 설명에서 두 폴더는 지금은 비어 있고, 해당 명령을 다시 돌리면 그 위치에 새로 생긴다.


Colab 노트북 `amazon_sentiment_finetune`, `amazon_ko_translate_sentiment_v2`를 모듈과 CLI로 옮긴 것이다.
출력 폴더 구조(`voc_amazon_finetune/`, `voc_amazon_ko/`)는 노트북과 같아서 기존 결과를 그대로 쓴다.

## 폴더 구조와 설명
작업 위치는 `C:\workspace\e-commerce\review-analysis`이다(워크스페이스 `C:\workspace\e-commerce` 아래 폴더 하나). 표의 **git** 열은 원격 저장소(`origin`)에 올라가는지를 뜻한다.

| 위치 | 무엇이 있나 | git |
|---|---|---|
| `review_analysis/` | **소스 패키지.** 모든 로직이 여기 있다 (아래 표) | 올림 |
| `run.py` | 명령줄 진입점. `sample`, `check`, `translate`, `compare`, `train`, `report`, `absa`, `absa-train`, `overview` | 올림 |
| `check_env.py` | 큰 모델 시험용 환경 점검(패키지·장치·메모리·디스크·키 설정 여부. 모델을 받지 않음) | 올림 |
| `check_split.py` | 데이터 분할이 노트북과 같은지 확인하는 작은 스크립트 | 올림 |
| `docs/` | 문서. `absa-label-guide.md`(속성 라벨 가이드, 규칙 R1~R21), `korean-review-crawling-legal-notes.md`(크롤링 법적 검토와 문의 메모), `absa_eval_template.csv`(평가셋 템플릿, 지어낸 예시) | 올림 |
| `templates/` | `dashboard_ko.html`: 별점 모델 대시보드의 HTML 템플릿 | 올림 |
| `voc_amazon_finetune/` | **영어 실험 결과**(노트북 `amazon_sentiment_finetune`의 출력). `sample_raw.parquet`(아마존 리뷰 샘플 원본 26,000건), `sample_stats.csv`, `results/`(모델별 JSON), `metrics_*.csv/json`, `predictions_test.csv`, `dashboard.html` | 올림 |
| `voc_amazon_ko/` | **한국어 실험 결과**(노트북 v2의 출력과 이후 작업). 아래 표 | 올림 |
| `archive/` | **지난 시험 결과 보관.** 영어·한국어 별점 모델, 번역 비교, 첫 ABSA 시험의 HTML·CSV, 후기 원문 샘플, 번역 결과를 시험별·날짜순으로 정리. 목록은 `archive/README.md` | 올림 |
| `private/` | **내부 자료.** 실제 후기를 받아 적은 사람 평가셋과 원문이 든 결과·화면. 외부에 올리거나 공유하지 않는다 | **제외** |
| `.env`, `.env.example` | 키(`GEMINI_KEY` 등)와 그 예시. `.env`는 비밀값이라 올리지 않는다 | `.env`만 제외 |
| `.venv/` | 이 프로젝트의 파이썬 가상환경 | 제외 |
| `_nb_code/` | 노트북 코드 셀을 `.py`로 뽑아 둔 **참고용**. 코드를 옮길 때 원본을 대조하려고 만든 것 | 제외 |
| `*.ipynb` (3개) | 포팅 원본 Colab 노트북: `amazon_sentiment_finetune`(영어), `amazon_ko_translate_sentiment`(한국어 v1), `amazon_ko_translate_sentiment_v2`(한국어 v2). `amazon_llm_test_gemini`는 아직 가져오지 않았다 | 올림 |
| `requirements.txt` / `requirements-gpu.txt` / `requirements-llm.txt` | 로컬(CPU) / 번역·파인튜닝용 GPU / 큰 모델 시험용 패키지 목록 | 올림 |
| `.git/`, `.gitignore`, `__pycache__/` | git 정보, 제외 규칙, 파이썬 캐시 | - |

**`review_analysis/` 안**
| 파일 | 역할 |
|---|---|
| `config.py` | 모든 설정(노트북 '1. 실험 설정' 셀과 같은 값): 경로, 번역 후보, 학습 하이퍼파라미터, 비밀값 읽기 |
| `data.py` | 원본 샘플링, 학습/검증/테스트 분할(영어 실험과 같은 시드), 영어 결과 불러오기 |
| `text.py` | 번역 입력 정리, 덩어리 나누기, 번역 실패 판정(한자·가나 혼입 포함) |
| `translators.py` | 번역기(NLLB·M2M100·LLM·Gemini·Papago), 번역 캐시, 디스크 정리 |
| `mt_compare.py` | 번역 후보 비교(감성 유지, 역번역 chrF, Gemini 별점 판정) |
| `classify.py` | 별점 5단계 분류 모델 학습·평가 |
| `metrics.py` | 정확도, F1, 혼동행렬 등 지표 |
| `report.py` | 별점 모델 요약표, 예측표, `dashboard.html` 생성 |
| `absa.py` | 속성 기반 감성분석: Gemini 추출 프롬프트(R1~R21), 합성 리뷰 생성·검증, 평가셋 채점 |
| `absa_train.py` | 작은 모델(KLUE-RoBERTa) 다중 헤드 증류 학습 |
| `overview.py` | 전체 결과 한 화면 `overview.html`(공유용)과 내부용 화면 생성 |

**`voc_amazon_ko/` 안**
| 위치 | 내용 |
|---|---|
| `translations/` | 번역 후보별 번역 캐시 `후보이름.parquet`(review_id, ko). `NHNDQ-NLLB-en2ko`와 `NLLB-1.3B`는 2만 건 전체, 나머지는 비교용 300건. `_speed.json`은 속도 기록 |
| `results/` | 한국어 번역문으로 학습한 감성 모델별 결과 JSON(예측, 확률, 학습 기록) |
| `mt_compare.csv`, `mt_samples.csv`, `mt_llm_star.json` | 번역 후보 비교표, 원문·번역 예시, Gemini 별점 판정 |
| `metrics_summary.csv`, `metrics_by_item.csv`, `metrics_en_vs_ko.csv`, `metrics_full.json`, `predictions_test.csv`, `failed_models.json` | 감성 모델 지표, 영어-한국어 비교, 테스트 예측, 실패 기록 |
| `dashboard.html` | 별점 모델 상세 화면(혼동행렬, 원래값/예측값 표) |
| `overview.html` | **전체 결과 한 화면(공유용, 원문 없음)** |
| `absa_pilot/` | 속성 기반 분석 시험 결과. `{이름}.{v1·v2}.json` Gemini 추출 캐시(버전별), `synth_ko.v1.json` 한글 합성 리뷰, `synth_pred_*`/`synth_review_queue.v1.csv` 합성 리뷰 재추출과 불일치 목록, `train_en_*.json` 영어 아마존 학습 라벨, `human_eval_*.json` 평가셋 채점 캐시(라벨만, 원문 없음), `small_model_runs.json` 작은 모델 실행 기록 |

## 큰 모델 시험 환경
```bash
.venv/Scripts/python -m pip install -r requirements-llm.txt   # 이미 설치됨(torch CPU, transformers 4.53.3, accelerate, peft 등)
python check_env.py                                           # 점검: 모델을 받거나 원격 코드를 실행하지 않는다
```
- transformers는 EXAONE 3.5 원격 코드 호환을 위해 `<4.54`로 고정했다(현재 4.53.3). EXAONE 로딩이 되는지는 모델을 받아 봐야 알 수 있어서 아직 확인하지 못했다.
- 이 PC: CPU 전용(GPU 없음), RAM 약 32GB(작업 중 사용 가능 12~20GB 정도라 7~8B bf16 약 16GB를 올릴 때는 다른 프로그램을 닫는다), 디스크 여유 충분. 7B 이상은 사람 평가셋 11건 같은 소량 확인에만 쓰고, 학습과 대량 추론은 Colab(GPU)에서 한다. `bitsandbytes`(4비트)는 Windows·CPU에서 쓸 수 없다.
- 모델 캐시는 `C:\Users\<사용자>\.cache\huggingface`에 쌓인다(7~8B 모델 하나가 약 16GB).

## 설치
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt        # 로컬(CPU): 평가·리포트·Gemini
.venv/Scripts/python -m pip install -r requirements-gpu.txt    # GPU 머신/Colab: 번역 모델·파인튜닝
```
비밀값은 `.env`(`.env.example` 참고)에 둔다: `GEMINI_KEY`, `PAPAGO_CLIENT_ID/SECRET`, `HF_TOKEN`.

## 실행
```bash
python run.py check                       # 분할 재현, 번역 캐시 상태 (빈 번역 많은 후보 표시)
python run.py translate --model Rosetta-4B --limit 5   # 소량 검증 (translations_smoke/에 저장, GPU)
python run.py compare                     # 캐시된 번역으로 비교표 (--translate면 없는 후보도 번역)
python run.py train --only KcELECTRA --limit 200       # 소량 학습 검증 (GPU)
python run.py report                      # 요약표, 예측표, dashboard.html (GPU 불필요)
```
설정은 `review_analysis/config.py` 하나에 모았다(노트북 '1. 실험 설정' 셀과 같은 값).

## 노트북 v2 문제의 처리
| 문제 | 원인(노트북 로그 기준) | 처리 |
|---|---|---|
| Rosetta 빈 출력 | 300건 전부 빈 문자열. 원인은 미확정이나 Gemma 계열 fp16 불안정이 유력 | 후보 설정 `dtype='bf16'`, 빈 출력이면 원본 생성 문자열을 로그로 남김, 빈 번역은 캐시로 인정하지 않고 재번역 |
| EXAONE 로드 실패 | `create_causal_mask(input_embeds)` TypeError, 원격 코드와 새 transformers 불일치 | `requirements-gpu.txt`에서 transformers 상한 `<4.54` (GPU에서 미검증) |
| iris/llama3 로드 실패 | `No space left on device` (Colab 디스크) | 모델 하나가 끝날 때마다 HF 캐시 삭제, 받기 전 남은 디스크 경고 |
| 역번역 chrF 없음 | M2M100-1.2B 다운로드 중 디스크 부족 | 위 디스크 대응 + 빈 번역은 `.`로 대체해 역번역 |
| 중국어 혼입 미검출 | 한글 비율 50%만 검사 | `text.failure_reason`에 한자·가나 검사 추가(한글 비율 검사보다 먼저) |

## 현재 상태
- GPU가 없는 PC라서 번역 모델 실행과 파인튜닝은 아직 돌려 보지 못했다. 분할 재현, 요약표·비교표·대시보드 재생성은 기존 결과와 일치함을 확인했다.
- `amazon_llm_test_gemini.ipynb`는 아직 옮기지 않았다.

## 추후 고려사항
- **Gemini API 번역을 일 1회/시간 단위 배치로 운영할 때**: 현재 설정(20건 묶음, 요청 간 4초 대기)에서 2만 건은 대기만 약 67분. 주기당 물량, 요금제(무료 등급 요청 제한), 모델 이름 고정과 변경 점검, 자사 리뷰 사용 시 외부 전송 검토가 필요하다. 번역만 Gemini로 하고 감성 분류는 로컬 모델로 두면 API 호출이 줄어든다. 결정은 보류했고, 필요해지면 새 리뷰만 번역하는 증분 배치 명령을 `run.py`에 추가한다.
- **번역 모델**: v2는 NHNDQ-NLLB-en2ko를 사용했다(NLLB 계열은 비상업 라이선스). 서비스용이면 M2M100-1.2B, Gugugo-7B, Gemini 중에서 다시 정한다.

## 속성 기반 감성분석(ABSA) 시험 (의류 한정, 3단계, Gemini)
```bash
python run.py absa lang     # 영어 원문 vs 한글 번역문의 속성·감성 일관성 (300건)
python run.py absa rerun    # 같은 영어 입력을 두 번 넣어 Gemini 자체 흔들림 측정
python run.py absa synth    # 한글 합성 리뷰 200건 생성 + 정답 대비 정확도 (낙관적 수치)
```
- 라벨 기준과 평가셋 작성법: `docs/absa-label-guide.md`, 템플릿 `docs/absa_eval_template.csv`(지어낸 예시), 실제 평가셋은 `private/`
- 결과 파일: `data/absa_pilot/` (Gemini 호출 결과 캐시)
- 한계: 번역문·합성 리뷰 기준이라 실제 한국인 리뷰에서의 성능은 아직 모른다. 직접 작성·검수한 평가셋이 필요하다.

### ABSA 후속 (1차 확정 반영)
```bash
python run.py absa synth --n 300        # 합성 한글 리뷰 생성 + 재추출 검증, 불일치 항목은 data/absa_pilot/synth_review_queue.v1.csv
python run.py absa eval --csv 경로.csv   # 사람이 작성한 평가셋(docs/absa_eval_template.csv 형식)을 Gemini 추출과 비교
python run.py absa-train --en 2000       # (GPU/Colab) KLUE-RoBERTa 다중 헤드 증류. 이 PC에서는 미검증
```
- 프롬프트가 바뀌면 `review_analysis/absa.py`의 `VERSION`을 올린다(캐시 파일 이름에 버전이 붙는다). v0 파일은 가이드 확정 전 시험 결과다.

## 전체 결과 화면
```bash
python run.py overview     # voc_amazon_ko/overview.html 생성 (저장된 결과만 읽음, GPU·API 불필요)
```
브라우저로 `voc_amazon_ko/overview.html`을 연다. 번역 모델 비교, 감성 모델(별점 5단계 + 긍/부정 점수), ABSA 시험, 추후 진행사항이 한 페이지에 있다. 별점 모델 상세(혼동행렬, 예측표)는 같은 폴더의 `dashboard.html`.

## 추후 진행사항
`overview.html` 4장과 같은 목록이다(코드: `review_analysis/overview.py`의 `NEXT_STEPS`).
- 데이터·평가: 한글 평가셋 200~300건 작성·검수, 합성 리뷰 불일치 확인, `absa eval`로 실제 말투 성능 확인, AI Hub 조건 확인과 문의
- 모델 학습(GPU/Colab): `absa-train` 소량 동작 확인 → 영어+한글 합본 학습, Rosetta/EXAONE/iris/llama3 재비교와 역번역 chrF, clapAI 영어 재실행
- 번역·운영 결정: 서비스용 번역 모델 선택, Gemini 배치 운영 여부, 2단계 번역·후보 선택 실험

### ABSA 라벨 규칙 v2 (2026-10-10)
- `docs/absa-label-guide.md` 4장에 번호 규칙 R1~R21을 확정했다. 프롬프트(`absa.py`)도 같은 규칙이고 `VERSION='v2'`.
- 새로 갈리는 사례가 나오면 가이드에 규칙을 추가하고 `VERSION`을 올린 뒤 `absa eval`을 다시 돌린다(캐시가 버전별로 분리되어 옛 결과와 섞이지 않는다).

### 결과 화면 두 종류
```bash
python run.py overview              # voc_amazon_ko/overview.html  — 실제 후기 원문 없음 (공유용)
python run.py overview --internal   # + private/overview_internal.html — 사람 평가셋 원문·사람/모델 라벨 포함 (내부용, 외부 공유 금지)
```

## 작은 모델(KLUE-RoBERTa) 증류 테스트 — 이 PC(CPU)에서도 가능
```bash
.venv/Scripts/python -m pip install torch transformers        # 한 번만 (CPU 버전, 이 .venv에 이미 설치됨)
python run.py absa-train --n 300 --epochs 8 --human           # 약 10분(CPU). 첫 실행은 모델 다운로드(약 440MB)와 Gemini 검증 호출이 있음
python run.py absa-train --n 300 --en 2000 --epochs 8 --human # 영어 아마존 2,000건(Gemini 라벨)을 학습에 더함. Gemini 약 100번 호출
```
- 학습 데이터: 한글 합성 리뷰 중 지시와 재추출이 일치한 항목(약 240건)을 70/15/15로 나눔. 평가: 합성 test + (`--human`) 사람 평가셋(private/, 이 PC 안에서만 계산, 외부 전송 없음).
- 출력은 속성 10개 × {미언급, 긍정, 부정, 중립}. `미언급`이 대부분이라 드문 클래스에 가중치를 둔다(없으면 전부 미언급으로 답한다).
- 2026-10-10 첫 실행(학습 170건, 8에폭, CPU): 합성 test 탐지 F1 0.81·감성 일치 77%, 사람 평가셋 11건 탐지 F1 0.67·감성 일치 54%·극성 반전 5/13. 같은 11건에서 Gemini는 F1 0.88·감성 일치 94.7%. 데이터가 아주 적은 동작 확인 수준이다.
- 실제 후기가 든 `private/`는 Colab 등 외부로 올리지 않는다. GPU 학습이 필요하면 합성 데이터만으로 학습하고, 사람 평가셋 평가는 이 PC에서 한다.
- 2026-10-10 확대 실행(`--n 1000 --en 1000 --epochs 6`, 학습 1,579건, CPU 약 1시간 반): 합성 test 125건 탐지 F1 0.99·감성 일치 98%, 사람 평가셋 11건 탐지 F1 0.70·감성 일치 79%·극성 반전 2/14. 같은 11건에서 Gemini는 F1 0.88·감성 일치 94.7%. 합성 안에서는 거의 완벽한데 실제 후기에서 떨어지는 합성-실제 격차가 핵심 과제다(특히 품질·내구성 재현율 0.2).
- 실행 기록은 `data/absa_pilot/small_model_runs.json`에 쌓이고 `overview`의 ABSA 장 아래 표에 나온다.
- 합성 리뷰(`synth_ko.v1.json`)는 이번에 1,000건으로 다시 만들어 덮어썼다(이전 300건 세트의 `synth_review_queue.v1.csv`는 옛 세트 기준).
