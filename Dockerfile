# Single-stage build on a CUDA base for GPU acceleration (GTX 1060 / Pascal, sm_61).
# CUDA 12.2 + cuDNN 8 runtime: required by CTranslate2 (faster-whisper) for GPU transcription.
# This image STILL runs on CPU-only hosts (CUDA libs go unused); the GPU device reservation
# lives ONLY in docker-compose.gpu.yml so `docker compose up` stays portable.
FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive

# Python 3.11 (deadsnakes) + FFmpeg + OpenCV runtime deps + Node.js (yt-dlp JS challenges).
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    ca-certificates \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    build-essential \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

# Build the venv in-place with Python 3.11 (no cross-image slim-venv copy).
RUN python3.11 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Install Python dependencies. torch/torchvision resolve to cu126 (sm_61-capable) wheels
# via the --extra-index-url pinned at the top of requirements.txt.
COPY requirements.txt .
# The large CUDA torch wheel (~700MB) is prone to mid-stream connection drops on
# WSL2/flaky networks. Retry the whole install a few times; pip --retries alone
# doesn't recover from a ProtocolError mid-download.
RUN pip install --upgrade pip \
    && for i in 1 2 3 4 5 6; do \
         pip install --no-cache-dir --retries 5 --timeout 300 -r requirements.txt && break; \
         echo "pip attempt $i failed, retrying in 5s..."; sleep 5; \
       done \
    && python -c "import torch, torchvision, faster_whisper, ctranslate2, ultralytics; print('core deps import OK; torch', torch.__version__)"

# Always upgrade yt-dlp to latest (YouTube bot-detection changes frequently)
RUN pip install --upgrade --no-cache-dir yt-dlp

# Copy application code
COPY . .

# Create a non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# Create directories including Ultralytics cache config
RUN mkdir -p /app/uploads /app/output /tmp/Ultralytics
# Fix permissions: /app for code/uploads, /tmp/Ultralytics for AI cache
RUN chown -R appuser:appuser /app /tmp/Ultralytics

# Switch to non-root user
USER appuser

# Pre-download YOLO model on build (CPU-only network download; NO GPU required at build time).
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

# Expose FastAPI port
EXPOSE 8000

# Run FastAPI app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]