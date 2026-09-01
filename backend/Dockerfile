# Production API (build with: docker build --network=host -t trading-api .)
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt requirements-ml.txt ./
RUN pip install --upgrade pip && \
    pip install -r requirements.txt && \
    pip install -r requirements-ml.txt

COPY . .

RUN chmod +x scripts/run_api.sh scripts/gunicorn_start.sh || true

EXPOSE 6000
CMD ["./scripts/run_api.sh"]
