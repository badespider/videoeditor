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
COPY requirements.txt .
COPY constraints.txt .

# Marker so we can confirm in Railway logs that the *latest* Dockerfile is being used
RUN echo "Video Recap AI backend build: CPU torch v4 - FORCE CPU ONLY"

# CRITICAL: Set pip to ONLY use CPU PyTorch index for torch packages
# This prevents any CUDA downloads
ENV PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu

# Install PyTorch CPU-only FIRST with explicit constraint
RUN pip install --no-cache-dir torch==2.2.2+cpu --index-url https://download.pytorch.org/whl/cpu

# Install sentence-transformers and transformers with torch already satisfied
RUN pip install --no-cache-dir sentence-transformers==2.7.0 transformers==4.39.3

# Install remaining Python dependencies (torch already installed, will be skipped)
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

# Download spaCy model
RUN python -m spacy download en_core_web_sm

# Copy application code
COPY app ./app
COPY scripts ./scripts
COPY railway.toml .
COPY list_models.py .

# Create temp directories for video processing
RUN mkdir -p /app/temp/scenes /app/temp/audio /app/temp/frames

EXPOSE 8000

# Use shell form to expand $PORT environment variable (Railway sets this)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
