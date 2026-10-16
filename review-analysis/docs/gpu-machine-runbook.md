# GPU PC에서 로컬 LLM(EXAONE) 시험하기

2026-10-11 RTX 3070 Laptop 8GB, RAM 32GB, Windows 11, 드라이버 CUDA 12.7 기준으로 확인한 절차다.

## 환경 만들기
```bash
python -m venv .venv-llm
.venv-llm/Scripts/python -m pip install torch --index-url https://download.pytorch.org/whl/cu126   # CUDA 빌드를 먼저
.venv-llm/Scripts/python -m pip install -r requirements-llm.txt bitsandbytes                        # transformers 4.53.3 (<4.54 유지)
python check_env.py
```
- `torch`를 requirements보다 먼저 CUDA 빌드로 설치해야 CPU 빌드로 덮이지 않는다.
- `bitsandbytes`(4bit)는 이 PC(Windows)에서 0.50.2로 동작했다. 8GB GPU에서 7.8B를 쓰려면 필요하다.
- `.venv-llm/`은 커밋하지 않는다.

## 모델 리비전 고정 (중요)
두 모델의 최신 원격 코드(2026-02, Transformers v5용)는 4.53에서 `RopeParameters` ImportError가 난다. 2024-12 리비전을 쓴다.

| 모델 | 리비전 |
|---|---|
| LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct | `e949c91dec` |
| LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct | `0ff6b5ec7c` |

## 실행
```bash
.venv-llm/Scripts/python llm_probe.py load --model 2.4b                      # 로드·속도 확인
.venv-llm/Scripts/python llm_probe.py absa --model 2.4b --n 200              # 합성 한글 리뷰 ABSA 평가
.venv-llm/Scripts/python llm_probe.py absa --model 7.8b --quant 4bit --n 200 --batch 4
```
평가는 합성 리뷰(`data/absa_pilot/synth_*`)만 쓴다. 정답은 생성 지시서이고, Gemini 재추출과 일치한 항목만 대상이다. 결과는 `absa_pilot/llm_local/`에 저장된다.

## 측정값 (프롬프트 1개, 64토큰)
| 모델 | 정밀도 | VRAM 피크 | 속도 |
|---|---|---|---|
| 2.4B | bf16 | 4.85GB | 14.0 tok/s |
| 7.8B | 4bit nf4 | 5.68GB | 9.1 tok/s |
| 7.8B | bf16 | 15.68GB | 1.4 tok/s (8GB 초과분이 시스템 RAM으로 넘어가 비실용적) |

배치 생성(배치 8) 중에는 KV 캐시 때문에 피크 VRAM이 더 커진다(2.4B 9GB대, Windows가 공유 메모리로 넘김). 8GB 안에 두려면 `--batch`를 줄인다.

## 규칙
- `.env`, `private/`, `*.zip`은 커밋·푸시하지 않는다.
- 실제 후기를 받아 적은 사람 평가셋(`private/`)은 내부 전용이다. `llm_probe.py`는 읽지 않는다.
