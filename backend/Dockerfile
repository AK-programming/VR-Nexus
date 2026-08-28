FROM python:3.12-slim

# Tesseract OCR for scanned PDF fallback
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code mounted as volume in dev; copied in production builds
COPY . .

# Storage directories created at runtime; no need to bake them in
