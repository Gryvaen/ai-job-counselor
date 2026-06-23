FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install --no-deps .

COPY agent ./agent
COPY api ./api
COPY config ./config
COPY models ./models

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8001/api/health || exit 1

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8001"]
