# Repo-root Dockerfile for Railway
#
# This exists to prevent Railway services from accidentally building the repo root
# without finding `backend/Dockerfile`. It builds the backend image and supports
# both API and worker modes via WORKER=1.
#
# NOTE: If your Railway service is configured with Root Directory = backend,
# it will use `backend/Dockerfile` instead. This file is a safe fallback.
#
# BUILD VERSION 7 - 2025-12-22 - FORCE FRESH BUILD

FROM python:3.11-slim

ARG CACHE_BUST=v7_root_20251222_001
RUN echo "Build version: ${CACHE_BUST}"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1 \
    libglib2.0-0 \
    g++ \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install CPU-only torch first to avoid CUDA downloads
RUN echo "=== VIDEO RECAP AI ROOT DOCKERFILE v7 ===" && \
    echo "Installing CPU-only PyTorch first to prevent CUDA downloads"

RUN pip install --no-cache-dir \
    torch==2.2.2+cpu \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir \
    sentence-transformers==2.7.0 \
    transformers==4.39.3

# Copy and install requirements
COPY backend/requirements.txt ./requirements.txt
COPY backend/constraints.txt ./constraints.txt
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

RUN python -m spacy download en_core_web_sm

# Copy backend code into /app/app
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/list_models.py ./list_models.py

RUN mkdir -p /app/temp/scenes /app/temp/audio /app/temp/frames

EXPOSE 8000

CMD ["sh", "-c", "echo \"🔧 Entrypoint: WORKER=${WORKER:-unset} PORT=${PORT:-unset}\"; if [ \"${WORKER:-0}\" = \"1\" ]; then echo \"🚀 Starting Pipeline Worker...\"; python -m app.workers.pipeline; else echo \"🚀 Starting API...\"; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}; fi"]

# Optimized Dockerfile for Railway deployment
# Uses CPU-only PyTorch to avoid massive CUDA downloads

FROM python:3.11-slim

# Install system dependencies for video processing and ML libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1 \
    libglib2.0-0 \
    g++ \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better Docker layer caching
COPY backend/requirements.txt .
COPY backend/constraints.txt .

# Marker so we can confirm in Railway logs that the *latest* Dockerfile is being used
RUN echo "Video Recap AI backend build: CPU torch pinned (v3: torch 2.2.2+cpu)"

# Install PyTorch CPU-only FIRST (before other packages pull in CUDA version)
# This significantly reduces build time and image size
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu torch==2.2.2+cpu

# Install remaining Python dependencies
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt -c constraints.txt

# Download spaCy model
RUN python -m spacy download en_core_web_sm

# Copy application code
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/railway.toml .
COPY backend/list_models.py .

# Create temp directories for video processing
RUN mkdir -p /app/temp/scenes /app/temp/audio /app/temp/frames

EXPOSE 8000

# Use shell form to expand $PORT environment variable (Railway sets this)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
