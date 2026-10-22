# 작업 지시서: agent/image-build

> 상태: 완료(빌드는 아직 못 해 봄) · 브랜치: `agent/image-build` · 다음 작업: 판정·조사 이미지 빌드·ECR push, DAG(`agent/dags/`)

## 목표

판정 잡 이미지의 **빌드 위치를 조사 이미지와 같은 `agent` 폴더로 맞춘다.** 인프라 담당(재영 님)이 두 이미지의 빌드 위치가 달라 연결 때 헷갈린다고 지적했다(판정은 `agent/detect/`, 조사는 `agent/`).

## 만드는 것

- `agent/detect/Dockerfile`: 빌드 위치를 `agent`로 바꾸고 `COPY` 경로를 `detect/...`로 맞춘다. 복사하는 파일은 그대로(`rules.py`, `job.py`, `athena_io.py`, `run_job.py`, `requirements.txt`).
- `docs/BRANCHES.md`: agent 구역에 `agent/bedrock`, `agent/image-build` 행

## 만들지 않는 것

- 이미지 빌드·ECR push, DAG, 환경변수·자원 요구량 확정(이미지를 빌드한 뒤 인프라 담당에게 전달)

## 빌드 방법

```
docker build -f agent/detect/Dockerfile -t <이름> agent
docker build -f agent/investigator/Dockerfile -t <이름> agent    # 조사 이미지는 PR #54
```
ECR 태그는 변경 불가이므로 새 커밋마다 새 태그(예: 커밋 해시)를 쓴다.

## 완료 확인

- [x] Dockerfile이 복사하는 파일이 `agent` 폴더 안에 모두 있다
- [x] 이미지 안과 같은 평평한 배치(`rules.py`, `job.py`, `athena_io.py`, `run_job.py`)에서 네 모듈이 모두 불러와진다
- [ ] 실제 `docker build` — 작업한 환경에 docker 실행 환경이 없어 **못 했다**. 빌드는 개발자 PC에서 확인한다
- [x] 비밀값, 계정 ID가 없다

## 작업 결과

판정 이미지 빌드 위치를 조사 이미지와 같게 맞췄다. 실제 빌드는 확인하지 못했다.
