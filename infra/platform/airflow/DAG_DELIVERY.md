# 현재 Airflow DAG 공급·확인 절차

2026-10-22 실제 Airflow에서 읽기 전용으로 확인했다. 이 문서는 **현재 실행 중인 상태**를 설명한다. main의 development-values.yaml에는 아직 최초 ConfigMap 방식이 남아 있으므로 그 파일만으로 재배포하지 않는다. GitDagBundle 적용 코드는 `infra/agent-runtime-connections` 브랜치에 보관되어 있고 별도 검토가 필요하다.

## 현재 경로

Git 저장소의 **main / infra/platform/airflow/dags/** → Airflow GitDagBundle → DAG processor 파싱 → UI에 등록.

| 항목 | 확인 값 |
|---|---|
| bundle | dags-folder |
| 구현 | airflow.providers.git.bundles.git.GitDagBundle |
| 추적 브랜치 | main |
| 읽는 하위 경로 | infra/platform/airflow/dags |
| 갱신 검사 주기 | 60초 |
| 신규 DAG 기본 상태 | 일시정지(true). 첫 업무 연결에서도 UI에서 확인 후 수동 실행한다. |

60초는 갱신 검사 주기이며 PR 머지부터 UI 반영까지 정확히 60초 이내라는 보장은 아니다. Git 다운로드·파싱 시간이 추가된다. DAG 파일 수정만으로 본체 Pod를 재시작하거나 ConfigMap으로 복사할 필요는 없다. Git 경로를 바꾸거나 Airflow 이미지에 패키지를 추가하는 변경은 별도 배포다.

`agent/dags/`나 `pipelines/`에 파일을 올리는 것만으로 현재 bundle이 그 파일을 자동 수집하지 않는다. 담당자와 다른 원본 경로를 선택하면 bundle 추가/경로 연결을 먼저 준비해야 한다. Silver·Gold A의 최종 업무 DAG 경로는 아직 확정하지 않았다.

## 팀원 작업과 인프라 작업

팀원은 DAG ID·실행 순서·인자·완료 조건을 작성하고 PR로 제출한다. 인프라는 해당 namespace에서 작업을 실행할 RBAC·이미지 digest·ServiceAccount/Pod Identity·자원·설정/Secret 참조를 확인한다. 검토 후 팀원이 수동으로 main에 머지하고 아래 절차로 반영을 확인한다. 자동 머지·자동 활성화를 설정한 것이 아니다.

무거운 Spark/판정/조사 코드는 처리 이미지에 넣고 DAG는 실행 요청과 상태 확인을 담당한다. DAG 폴더에 requirements.txt를 추가해도 Airflow에 패키지가 설치되지는 않는다. 현재 이미지에 없는 provider/import가 필요하면 인프라와 이미지 변경을 맞춘다. `AIRFLOW_INFRA_PROBE_CONFIG`는 설치 확인용 DAG의 설정이며 업무 이미지·인자를 자동 공급하는 공통 계약이 아니다.

## 배포 후 확인

1. main에 실제 머지됐고 bundle의 하위 경로 안에 DAG 파일이 있는지 확인한다.
2. 갱신/파싱 후 Airflow UI에서 해당 DAG ID가 보이고 import error가 없는지 확인한다.
3. 일시정지 상태·실제 이미지 digest·입력 범위·처리 동시성·실행 권한을 확인한 다음 첫 작업을 수동 실행한다.
4. 업무 실행 시험에서는 Airflow task 로그와 Spark 제출기/Driver/Executor 로그를 각각 확인한다. Job 종료만으로 Driver나 데이터 임시 파일까지 정리됐다고 가정하지 않는다.

인프라 권한으로 상태를 읽을 때는 다음 명령을 사용할 수 있다. 이 명령은 DAG를 실행하지 않는다.

```powershell
kubectl -n airflow exec deployment/airflow-scheduler -c scheduler -- airflow dags list --output json
kubectl -n airflow exec deployment/airflow-scheduler -c scheduler -- airflow dags list-import-errors --output json
```

## 이번 확인 결과와 한계

- `infra_airflow_access_probe`, `infra_airflow_five_minute_probe` 두 DAG가 dags-folder bundle에서 인식됐다.
- 파일 위치가 Git tracking_repo 아래의 infra/platform/airflow/dags/infra_probe.py인 것을 확인했다.
- DAG processor의 tracking_repo HEAD는 이번 점검 기준 최신 main `783fa84`와 일치했다.
- 두 DAG 모두 일시정지, import error 0건이었다.
- DAG 실행·테스트 파일 추가·설정/권한 변경·Pod 재시작은 하지 않았다. 따라서 업무 DAG 실행과 신규 커밋의 반영 지연을 시험한 결과는 아니다.
- 실제 설정과 main의 이전 values 사이 차이는 해소하지 않았다. 검토 없이 이전 values를 사용하면 Git 공급 설정을 되돌릴 수 있다.
