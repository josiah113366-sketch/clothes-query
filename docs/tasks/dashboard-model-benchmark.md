# 작업 지시서: dashboard/model-benchmark (감성분석 모델 관리 통합)

> 상태: 진행 중 · 브랜치: `dashboard/model-benchmark` · 함께 들어간 브랜치: `review-model/release`, `infra/sagemaker-model-release` (이 브랜치에 머지됨)
> 설계 정리: 감성분석 모델 버전 관리 설계(프로젝트 공유 문서 `MODEL-VERSIONING.md`)의 결정을 이 저장소에 반영한 작업이다.

## 목표

감성분석 모델(점수형 s2c)을 **버전 단위로 관리**한다.
1. 대시보드 데이터 관리 Role 에 `감성분석 모델` 화면을 만든다(버전·패치노트, 모델별 리뷰 분석, 버전 비교, 일별 분석 현황).
2. 버전마다 패치노트를 git 에 쓰고(`review-analysis/releases/`), 모델을 올릴 때 검사·변환해 S3 로 배포한다. 대시보드는 S3 를 바로 읽는다.
3. 버전 하나를 **릴리스 묶음(manifest) 하나**로 정한다. 점수화 Job 은 버전 이름 하나만 받고 가중치·실행 코드·라이브러리·이미지·번호를 모두 manifest 에서 가져온다.
4. 되돌리기는 번호를 올리면서 원래 버전을 다시 배포하는 방식(roll-forward)으로 한다.

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- **세 영역을 한 브랜치로 머지한다.** `review-model`(review-analysis/), `infra`(sagemaker 스택), `dashboard`(dashboard/, infra/platform/dashboard/) 변경이 이 브랜치 하나에 들어 있다. 영역별 브랜치 두 개를 이 브랜치에 머지했고, PR 도 이 브랜치 하나로 올린다(2026-10-23 결정). 리뷰는 아래 "만드는 것"의 영역 구분으로 나눠 본다. infra 부분은 인프라 담당이 확인한다.
- 코드에는 버킷 이름을 상수로 두지 않고 인자, SSM, 환경변수로 받는다. 배포 설정(`deployment.yaml`)에는 팀 버킷 이름을 써도 된다(버킷 공개 차단, 2026-10-23 결정).
- 후기 원문, AI Hub 원본, 사람 평가 세트의 후기 문장은 패치노트·manifest·화면 어디에도 넣지 않는다.
- git commit·push 는 사람이 한다. Terraform apply, S3 업로드, kubectl apply 도 사람이 한다.

## 결정 사항 (2026-10-23)

| 항목 | 결정 |
|---|---|
| S3 위치 | 루트 폴더를 늘리지 않고 `review-score/` 하나 아래에 둔다. 가중치 `review-score/model/<버전>/`, 패치노트·묶음 `review-score/model-registry/releases/` |
| 버킷 설정 | 버저닝 켜짐, 수명주기 규칙 없음(확인함). 나중에 규칙을 추가하면 위 두 경로는 뺀다 |
| 패치노트 | git `review-analysis/releases/<버전>.yaml`로 쓰고, 업로드 때 JSON 으로 S3 에 배포. 배포된 버전은 `notes` 덧붙임만 허용 |
| 버전 세트 | manifest 하나 = 한 버전 세트. 한 번 만든 묶음과 가중치 폴더는 덮어쓰지 않는다 |
| 지금 쓸 버전 | SSM 설정의 `release` 하나 (Terraform). 실행 스크립트가 읽는다 |
| 라이브러리 고정 | manifest 의 pip 목록 (`deploy/runtime-requirements.txt`, 모두 `==`) |
| 되돌리기 | 패치노트에 `based_on: <원래 버전>`, 번호는 올린다(Gold 가 가장 큰 번호를 읽기 때문). 가중치를 다시 올리지 않는다 |
| 대시보드 | 임시 복사본 없이 S3 를 바로 읽는다 |

## 만드는 것

### A. 대시보드 화면 (`dashboard/`)
- `pages_data/models.py`: 탭 4개. 버전 목록을 누르면 패치노트(분류별 변경, 평가 지표 이전 버전 대비, 되돌림 표시, 배포 뒤 정정)가 나온다
- `data.py`: `get_model_registry`, `get_model_changelog`(S3 실데이터 연결), `get_model_review_daily`, `get_model_score_daily`, `get_model_score_diff`, `get_model_runs`(더미)
- S3 읽기: `MODEL_REGISTRY_URI`가 있고 `DATA_SOURCE`가 `dummy`가 아니면 `index.json`과 `<버전>.json`을 읽는다. 없거나 실패하면 더미
- `requirements.txt`에 `boto3`

### B. 패치노트 (`review-analysis/releases/`, `deploy/release_notes.py`)
- 양식 `_template.yaml`, 작성 규칙 `README.md`, 소급 작성 `2.4b_score_s2c.yaml`
- `release_notes.py validate | to-json | upload`: 필수·허용 키, 번호 형식, 변경 유형, 날짜, 분류 6개, 평가 지표, 번호 사슬(최초·메이저·마이너), `based_on` 규칙

### C. 릴리스 묶음 (`review-analysis/deploy/`)
- `release_bundle.py`(새): manifest 만들기·읽기·검사, 가중치 sha256, 버전 고정 목록 검사
- `upload_model.py`: 패치노트 검사 → 버전 고정 검사 → 덮어쓰기 거부 → 가중치 → 코드 사본 → manifest(맨 마지막) → 패치노트(묶음 있는 버전만). `--weights-already-uploaded`(이미 올린 가중치 등록), 되돌림 버전 처리
- `run_processing_job.py`: `--release`(기본 SSM `release`)로 manifest 를 읽어 Job 을 만든다. 실행 전 S3 가중치 이름·크기 대조. 하드코딩된 모델 폴더 이름 제거
- `runtime-requirements.txt`(새): 컨테이너 설치 목록

### D. 인프라 (`infra/modules|stacks/sagemaker-review-score`)
- SSM 설정: `release`, `registry_prefix` 추가. `model_version`, `model_version_no`, `code_prefix` 제거. `image_uri`는 새 묶음의 기본 이미지로만 남김
- Job 역할: `review-score/code/*` 대신 `review-score/model-registry/releases/*/code/*` 읽기
- launcher 정책: manifest 읽기, 가중치 목록 조회
- 대시보드 배포(`infra/platform/dashboard/`): `MODEL_REGISTRY_URI` 환경변수(팀 데이터 버킷의 `review-score/model-registry/releases/`)

## 만들지 않는 것

- 점수 테이블(Athena) 실조회: 모델별 리뷰 분석, 버전 비교, 일별 분석 현황, 버전 목록의 분석 현황 열은 더미로 둔다(`dashboard/TODO.md` B6)
- 대시보드 Pod Identity 와 S3 읽기 권한(`TODO.md` F3, F4)
- S3 파일 복구 스크립트(버저닝 이전 버전 복구는 README 절차만)
- 실제 업로드·apply (사람이 한다)

## 적용 순서 (머지 후)

1. 이 브랜치를 main 에 머지한다.
2. 인프라 담당이 `infra/stacks/sagemaker-review-score`를 plan → apply 한다. **머지 전에 apply 하지 않는다**(main 의 옛 실행 스크립트가 SSM 의 `model_version`을 찾지 못해 멈춘다).
3. `python deploy/run_processing_job.py --input-key <키> --dry-run`을 `--release` 없이 실행해 SSM `release`를 읽고 manifest 기준 요청이 만들어지는지 확인한다.
4. 대시보드: 파드에 S3 읽기 권한을 붙이면 패치노트가 실데이터로 보인다(`deployment.yaml`에 `DATA_SOURCE=auto`, `MODEL_REGISTRY_URI` 설정됨). 권한 전에는 더미.

## 완료 확인

- [x] 패치노트·묶음: 가짜 S3 로 9가지 경우(이미 올린 가중치 등록, 같은 버전 거부, 파일 있는 가중치 폴더 거부, 이미지 없음 거부, 새 버전, 되돌림, `based_on` 규칙 위반 2종, 가중치 손상 감지)
- [x] `2.4b_score_s2c` 묶음 소급 등록 (사람이 실행)
- [x] `terraform fmt -check`, `terraform validate` (sagemaker-review-score 스택)
- [x] 대시보드: `ruff check`, `ruff format --check`, AppTest 로 S3 실데이터(가짜 boto3)와 더미 두 경우 모두 예외 없음, 되돌림·정정 표시
- [x] `terraform plan`
- [ ] 점수화 Job 첫 실행에서 고정 라이브러리가 컨테이너에 설치되는지 (`accelerate==1.15.0`, `pyarrow==25.0.1` 등은 로컬 가상환경 버전이라 이미지에서 실측 필요)

## 작업 결과 (머지 전에 작성한다)

- **한 줄 요약:** 감성분석 모델을 버전(릴리스 묶음) 단위로 올리고·실행하고·되돌리는 흐름과, 그 패치노트를 보여 주는 대시보드 화면.
- **무엇을 만들었나:** 위 "만드는 것" A~D.
- **왜 그렇게 했나:** 점수화 실행에 쓰이는 구성품(가중치, 실행 코드, 라이브러리, 이미지, 번호)이 따로 관리돼 "1.0 으로 되돌려"가 무엇을 뜻하는지 정할 수 없었다. manifest 하나에 묶어 버전 이름만으로 같은 실행을 다시 할 수 있게 했다. Gold 가 가장 큰 번호를 읽어 번호를 내리는 되돌리기는 효과가 없으므로 roll-forward 로 했다.
- **입력과 출력:** 입력은 합친 모델 폴더, `releases/<버전>.yaml`, `runtime-requirements.txt`, SSM `release`. 출력은 S3 `review-score/model/<버전>/`, `review-score/model-registry/releases/`(index.json, `<버전>.json`, `<버전>/manifest.json`, `<버전>/code/`), 대시보드 화면. 다른 영역과의 약속: 패치노트 JSON `schema: 1`(`release_notes.py` SCHEMA 와 대시보드 `_RELEASE_SCHEMA`를 같이 바꾼다), manifest `schema: 1`.
- **확인한 결과:** 위 "완료 확인" 참고.
- **알려진 한계·남은 일:** 점수 현황 실데이터(B6), 파싱 실패·Job 결과 위치(B7), 대시보드 S3 읽기 권한(F3, F4), 첫 실행에서 라이브러리 설치 확인.
