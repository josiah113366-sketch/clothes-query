# 작업 지시서: sim/sink-pause

> 상태: 진행 중 · 브랜치: `sim/sink-pause` (최신 `main`) · 요청: 탐지 담당(소비 지연 시연, 2026-10-23)

## 목표

소비 지연(R3) 시연을 burst 모드 대신 **S3 Sink 정지**로 한다. 정지는 사람이 `kubectl`로 하지만 채점하려면 정답표(`incident_log`)에 시작·끝이 남아야 한다. 컨트롤러에 **기록만 하는** 사건 `SINK_PAUSE`를 더한다.

## 사용자 결정 (2026-10-23, 다른 문서보다 우선)

- 사건 종류 이름 `SINK_PAUSE`. `INGEST_LAG`(burst, 유입↑)와 원인이 달라(유입 평소, 적재 멈춤) 따로 둔다
- 대상은 `bronze-s3-sink-v2`만
- 버튼은 만들지 않고 명령(`sim controller sink-pause`)으로 한다. 콘솔에는 진행 중 사건 이름과 기존 "지금 종료"만
- 기본 25분(R3 기준 1200초를 확실히 넘기는 20분 + 여유), 최대 60분. **자동 종료하지 않는다**: 컨트롤러가 Sink를 재개할 수 없어 타이머로 끝 기록을 쓰면 실제 재개 시각과 어긋난다. 사람이 재개를 확인한 뒤 `end`(`ended_by: manual`)

## 만드는 것

- `model.py`: `SINK_PAUSE`, `SINK_CONNECTORS`, 기본·최대 분
- `service.py`: `start_sink_pause(connector, minutes)` — 검증 → 시작 기록 → 진행 중 사건. 제어 파일은 쓰지 않는다. 끝(`end`, `shutdown`)도 제어 파일 없이 끝 기록만
- `server.py`: `POST /api/incidents/sink-pause`, `cli.py`: `sim controller sink-pause`, `page.py`: 사건 이름
- 테스트, `simulator/README.md` 컨트롤러 절(순서와 `kubectl` 명령)

## 만들지 않는 것

- 컨트롤러가 커넥터를 직접 멈추거나 재개하는 것 (ECS에서 EKS Connect 권한·경로 없음, Strimzi가 되돌림)
- 채점 대응표(`SINK_PAUSE → BRONZE_LAG_SPIKE / 적재 층 / R3`)와 `docs/design/agent/anomaly-answer-key.md` 7절 반영: 탐지 담당
- Gold B 지연 수집기를 v2로 바꾸기(`GOLD_B_SINK_CONNECTOR=bronze-s3-sink-v2`): Gold B 담당

## 의존

- `conn/bronze-v2`(v2 Sink)는 아직 main에 머지 전이지만 클러스터에는 적용돼 있다. 이 브랜치는 커넥터 이름 문자열만 쓰므로 머지 순서와 상관없이 동작한다

## 완료 확인

- [x] `ruff check .`, `ruff format --check .`, `pytest` 통과
- [ ] ECS 이미지 재배포 후 `sim controller sink-pause` → S3 `ground_truth/incident_log/`에 `SINK_PAUSE` start, `end` → end(`manual`) (사용자)
- [ ] 짧은 시험 정지(5분): `kubectl` 정지·재개, 수집기 `connector_state=PAUSED`·`lag_sec` 증가 (사용자)

## 작업 결과

(머지 전에 채운다)
