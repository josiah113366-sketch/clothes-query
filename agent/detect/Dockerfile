# 판정 잡 이미지 (제안). 빌드 위치는 agent 폴더(조사 이미지와 같음): docker build -f agent/detect/Dockerfile -t <이름> agent
# 이미지 저장소(ECR) 등록과 Airflow DAG 연결은 인프라 담당과 정한다.
FROM python:3.12-slim
WORKDIR /app
COPY detect/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY detect/rules.py detect/job.py detect/athena_io.py detect/run_job.py ./
RUN useradd --system --no-create-home runner
USER runner
ENTRYPOINT ["python", "run_job.py"]
