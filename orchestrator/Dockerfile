FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV ORCHESTRATOR_HOST=0.0.0.0 \
    ORCHESTRATOR_PORT=8000 \
    STORAGE_ROOT=/data/storage \
    JOB_STORE_PATH=/data/jobs.db

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=20s --timeout=5s --retries=5 --start-period=5s \
  CMD curl -fs http://localhost:8000/healthz || exit 1

CMD ["python", "server.py"]
