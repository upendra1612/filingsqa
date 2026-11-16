# FilingsQA API image (Render free web service, 512 MB RAM).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/app/models

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[api]"

# Bake the embedding model into the image so a cold start doesn't download it.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

# Render provides $PORT; default to 8000 locally.
CMD uvicorn filingsqa.api:app --host 0.0.0.0 --port ${PORT:-8000}
