# 모델 패치노트 (releases/)

모델 버전마다 `<model_version>.yaml` 한 개를 쓴다. 대시보드 `감성분석 모델` 화면의 "버전·패치노트" 탭이 이 내용을 보여 준다.
양식은 [_template.yaml](_template.yaml)(예시 값. 파일 이름이 `_`로 시작하면 검사·업로드에서 빠진다)을 복사해서 쓴다.

## 언제 쓰나
- `model_version_no`를 올리는 PR에는 이 폴더의 새 파일이 **반드시 같이** 들어간다.
- 번호 규칙: 평가 모델/로직이 바뀌면 메이저(0.0→1.0), 작은 수정·버그 수정이면 마이너(0.0→0.1). 마이너는 0~9, x.9 다음 변경은 메이저.
- 배포된 버전의 파일은 고치지 않는다. 정정·추가는 `notes`에 날짜와 함께 덧붙인다. 그 밖의 필드를 고쳐야 하면 새 버전으로 쓴다.

## 쓰는 것
| 필드 | 설명 |
|---|---|
| `model_version` | 모델 이름. 파일 이름과 같게 |
| `model_version_no` | `x.y` (소수 한 자리). 점수 테이블의 `model_version_no`와 같은 값 |
| `change_type` | `최초`(가장 낮은 번호 하나) / `메이저` / `마이너` |
| `released_at` | 배포일(KST) `YYYY-MM-DD` |
| `summary` | 한 줄 요약 |
| `rescore_required` | 기존 후기를 다시 점수화해야 하는지 (메이저면 보통 true) |
| `changes` | 바뀐 내용 목록. 항목마다 `category`, `item`, `detail`. 분류는 `모델`, `학습 데이터`, `프롬프트·후처리`, `속성 목록`, `평가`, `배포` |
| `evaluation` | `eval_set`, `eval_n`, `f1`, `mae`, `qwk`, `source`(지표를 만든 결과 파일 이름). 평가 결과 파일의 값을 옮긴다 |
| `notes` | 배포 뒤 정정·추가 `{date, text}` 목록 |
| `based_on` | (되돌림 버전만) 되돌릴 원래 버전 이름. 원래 버전보다 번호가 높아야 하고, 실제 가중치가 있는 버전(다른 되돌림 버전이 아닌)을 가리켜야 한다. 업로드는 가중치를 다시 올리지 않고 원래 버전 묶음을 그대로 가리킨다 |

후기 원문, AI Hub 원본 내용, 사람 평가 세트의 후기 문장은 쓰지 않는다(공개 저장소). 정해진 필드 밖의 항목은 검사에서 막힌다.

## 검사·변환·업로드 (`deploy/release_notes.py`)
```
python deploy/release_notes.py validate
python deploy/release_notes.py to-json --out <폴더>   # 변환 결과 확인용 (대시보드는 S3 를 직접 읽는다)
python deploy/release_notes.py upload --uri s3://<버킷>/review-score/model-registry/releases/ --dry-run
```
모델 업로드(`deploy/upload_model.py`)는 이 검사를 통과하고 올리는 버전의 패치노트가 있어야만 진행되고, 릴리스 묶음(manifest)을 만든 뒤 패치노트도 같이 올린다(묶음이 있는 버전만). 업로드는 검사를 통과한 파일만 JSON으로 바꿔 올리고 `index.json`을 갱신한다. 이미 올라간 버전은 `notes` 덧붙임만 허용하고, 다른 필드가 다르면 거부한다. 버킷 이름은 코드·문서에 쓰지 않고 `--uri`로만 준다.
