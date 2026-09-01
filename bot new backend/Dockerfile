# Production API + scheduler (train models on host or CI, mount ./models)
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-ml.txt ./
RUN pip install --upgrade pip && \
    pip install -r requirements.txt && \
    pip install -r requirements-ml.txt

COPY . .

RUN chmod +x scripts/run_api.sh scripts/gunicorn_start.sh || true

EXPOSE 6000

# WORKDIR=/app → project root; config resolves models/ and .env* from here (not host cwd).
CMD ["./scripts/run_api.sh"]
