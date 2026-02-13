FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

ENV SHOPKEEPER_HOST=0.0.0.0 \
    SHOPKEEPER_PORT=9999 \
    SHOPKEEPER_DB_PATH=/app/data/shopkeeper.db

EXPOSE 9999

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',int(os.environ.get('SHOPKEEPER_PORT','9999')))); s.close()" || exit 1

CMD ["python", "heartbeat_server.py"]
