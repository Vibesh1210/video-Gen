FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv \
      ffmpeg \
      git \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

# Install VoxCPM + service deps. torch comes in via voxcpm's own install.
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121 && \
    pip install voxcpm && \
    pip install -r requirements.txt

# Service code + voices (weights are mounted at runtime).
COPY api/ ./api/
COPY engine/ ./engine/
COPY voices/ ./voices/
COPY voices.yaml ./voices.yaml

ENV VOXCPM_MODEL_PATH=/models/VoxCPM2 \
    VOXCPM_DEVICE=cuda \
    VOXCPM_VOICES_FILE=/app/voices.yaml \
    API_HOST=0.0.0.0 \
    API_PORT=8080 \
    LOG_LEVEL=INFO

EXPOSE 8080

CMD ["sh", "-c", "uvicorn api.server:app --host ${API_HOST} --port ${API_PORT}"]
