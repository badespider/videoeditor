FROM python:3.11-slim

# Install system dependencies for video processing and ML libraries
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1 \
    libglib2.0-0 \
    g++ \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy language model for visual grounding
RUN python -m spacy download en_core_web_sm

# Copy application code
COPY . .

# Create temp directories
RUN mkdir -p /app/temp/scenes /app/temp/audio /app/temp/frames

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

