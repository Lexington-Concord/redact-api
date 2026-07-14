FROM ghcr.io/astral-sh/uv:alpine

ENV PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_NO_DEV=1 \
    UV_PYTHON_INSTALL_DIR=/app/.python

WORKDIR /app

# tesseract-ocr is required at runtime by the redaction verify gate (pytesseract).
# Installed before the dependency sync so this layer is cached across pure-Python
# dependency changes.
RUN apk add --no-cache tesseract-ocr tesseract-ocr-data-eng

COPY pyproject.toml uv.lock ./
RUN uv sync --locked -n --no-progress
COPY scripts ./scripts
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY redact_api ./redact_api/

RUN addgroup -g 1000 -S app && adduser -u 1000 -S app -G app \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["sh", "scripts/start.sh"]
