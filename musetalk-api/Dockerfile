# MuseTalk API image. Heavy — layers a conda env onto a CUDA base.
#
# Build context should be the REPO ROOT (not musetalk-api/), so this image
# can COPY both musetalk-api/ and MuseTalk/ into the container.
#
#   docker build -t musetalk-api:latest -f musetalk-api/Dockerfile .

FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONDA_DIR=/opt/conda \
    PATH=/opt/conda/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg git curl ca-certificates build-essential \
      libsm6 libxext6 libgl1 \
 && rm -rf /var/lib/apt/lists/*

# Miniconda — MuseTalk's upstream env mirrors its README.
RUN curl -fsSL -o /tmp/miniconda.sh \
      https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh \
 && bash /tmp/miniconda.sh -b -p $CONDA_DIR \
 && rm /tmp/miniconda.sh \
 && conda clean -afy

WORKDIR /app

# Copy code.
COPY MuseTalk /app/MuseTalk
COPY musetalk-api /app/musetalk-api

# Python env. MuseTalk's requirements.txt is authoritative; the API only adds
# fastapi/uvicorn/multipart.
RUN conda create -y -n musetalk python=3.10 \
 && conda run -n musetalk pip install --no-cache-dir -r /app/MuseTalk/requirements.txt \
 && conda run -n musetalk pip install --no-cache-dir -r /app/musetalk-api/requirements.txt \
 && conda clean -afy

ENV MUSETALK_HOST=0.0.0.0 \
    MUSETALK_PORT=8081 \
    MUSETALK_GPU_ID=0 \
    MUSETALK_VERSION=v15

EXPOSE 8081

# Models are expected to be mounted at /app/MuseTalk/models (volume).
WORKDIR /app/musetalk-api
CMD ["conda", "run", "--no-capture-output", "-n", "musetalk", "python", "server.py"]
