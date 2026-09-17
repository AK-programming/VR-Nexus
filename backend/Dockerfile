# VR-Nexus backend — Python 3.11 on Debian slim.
#
# Serves three roles from the same image: the FastAPI app (uvicorn), the Celery
# worker, and Flower. docker-compose picks the role via the `command` override.
#
# Tesseract is included for OCR fallback on scanned PDFs. The English trained
# data is enough for PPRA/World-Bank tenders; add tesseract-ocr-<lang> packages
# here if other languages are needed.

FROM python:3.11-slim AS base

# System dependencies: tesseract for OCR, libpq for psycopg, build tools for
# any wheels that need compilation (fastembed's ONNX runtime, bcrypt, etc.).
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libpq-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching: requirements change less
# often than application code).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code.
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY tests/ ./tests/

# The static directory may not exist in every checkout, but the app references
# it for serving uploaded assets. Create it so the COPY does not fail, and so
# the path exists at runtime even if nothing is mounted over it.
RUN mkdir -p /app/static
COPY static/ ./static/ 2>/dev/null || true

# Storage directories. In production these are typically backed by EBS or EFS
# volumes; the Dockerfile creates the paths so the app does not need to.
RUN mkdir -p /data/storage/tenders /data/storage/library /data/storage/outputs

# Default port for the API. The worker and Flower override the command entirely,
# so this only matters for the api service.
EXPOSE 8000

# Default: run the API. docker-compose overrides this for worker and flower.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
