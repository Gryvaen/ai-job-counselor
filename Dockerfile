FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

RUN python -m playwright install --with-deps chromium

COPY pyproject.toml README.md ./
COPY agent ./agent
COPY api ./api
COPY config ./config
COPY crews ./crews
COPY mcp_servers ./mcp_servers
COPY models ./models
COPY notifier ./notifier
COPY rag ./rag
COPY scraper ./scraper
COPY scripts ./scripts
COPY storage ./storage

RUN pip install --no-deps .

EXPOSE 8000

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
