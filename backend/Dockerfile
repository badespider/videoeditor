# Optimized Dockerfile for Railway deployment
# Uses CPU-only PyTorch to avoid massive CUDA downloads
# BUILD VERSION 7 - 2025-12-22 - FORCE FRESH BUILD

FROM python:3.11-slim

# ============================================================
# CACHE BUSTER - Change this value to force a fresh build
# ============================================================
ARG CACHE_BUST=v7_20251222_001
RUN echo "Build version: ${CACHE_BUST}"

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

# ============================================================
# CRITICAL: Install CPU-only PyTorch BEFORE copying requirements
# This ensures we control exactly which torch version is installed
# ============================================================

# Marker for debugging - confirm this Dockerfile is being used
RUN echo "=== VIDEO RECAP AI BUILD v6 ===" && \
    echo "Installing CPU-only PyTorch first to prevent CUDA downloads"

# Install PyTorch CPU-only FIRST using the CPU-only index
# This MUST happen before any other ML packages
RUN pip install --no-cache-dir \
    torch==2.2.2+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# Verify torch is CPU-only
RUN python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}')"

# Install sentence-transformers and transformers BEFORE requirements.txt
# This ensures they use the already-installed CPU torch
RUN pip install --no-cache-dir \
    sentence-transformers==2.7.0 \
    transformers==4.39.3

# Verify sentence-transformers is installed
RUN python -c "from sentence_transformers import SentenceTransformer; print('✅ sentence_transformers installed successfully')"

# NOW copy and install remaining requirements
COPY requirements.txt .
COPY constraints.txt .

# Install remaining dependencies - torch/sentence-transformers already satisfied
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

# Download spaCy model
RUN python -m spacy download en_core_web_sm

# Final verification of all ML packages
RUN python -c "import torch; from sentence_transformers import SentenceTransformer; import spacy; print('✅ All ML packages verified')"

# Copy application code
COPY app ./app
COPY scripts ./scripts
COPY railway.toml .
COPY list_models.py .

# Create temp directories for video processing
RUN mkdir -p /app/temp/scenes /app/temp/audio /app/temp/frames

EXPOSE 8000

# ============================================================
# Entrypoint
# - Default: run API (uvicorn)
# - Worker service: set WORKER=1 to run the pipeline worker instead
# ============================================================
CMD ["sh", "-c", "echo \"🔧 Entrypoint: WORKER=${WORKER:-unset} PORT=${PORT:-unset}\"; if [ \"${WORKER:-0}\" = \"1\" ]; then echo \"🚀 Starting Pipeline Worker...\"; python -m app.workers.pipeline; else echo \"🚀 Starting API...\"; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}; fi"]
