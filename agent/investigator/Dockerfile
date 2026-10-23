# 조사 에이전트 이미지 (제안). 빌드 위치는 agent 폴더: docker build -f agent/investigator/Dockerfile -t <이름> agent
# (detect/athena_io.py, tools를 같이 쓰기 때문에 build context가 agent 폴더다.)
# 이미지 저장소(ECR) 등록과 Airflow DAG 연결은 인프라 담당과 정한다.
FROM python:3.12-slim
WORKDIR /app/agent
COPY detect/requirements.txt detect/requirements.txt
RUN pip install --no-cache-dir -r detect/requirements.txt
COPY detect/athena_io.py detect/athena_io.py
COPY tools/guard.py tools/ledger_tools.py tools/
COPY investigator/bedrock_io.py investigator/loop.py investigator/prompt.py investigator/report.py investigator/run_investigation.py investigator/
RUN useradd --system --no-create-home runner
USER runner
WORKDIR /app/agent/investigator
ENTRYPOINT ["python", "run_investigation.py"]
