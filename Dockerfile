FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/engine

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Non-root user for security
RUN adduser --disabled-password --no-create-home --gecos "" appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app/data

ENV SHOPKEEPER_HOST=0.0.0.0 \
    SHOPKEEPER_PORT=9999 \
    SHOPKEEPER_WS_PORT=8765 \
    SHOPKEEPER_HTTP_PORT=8080 \
    SHOPKEEPER_DB_PATH=/app/data/shopkeeper.db

EXPOSE 9999 8765 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')" || exit 1

USER appuser

CMD ["python", "engine/heartbeat_server.py"]
