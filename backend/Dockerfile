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
RUN echo "Video Recap AI backend build: CPU torch pinned (v3: torch 2.2.2+cpu)"

# Install PyTorch CPU-only FIRST (before other packages pull in CUDA version)
# This significantly reduces build time and image size
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu torch==2.2.2+cpu

# Install remaining Python dependencies
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt -c constraints.txt

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
