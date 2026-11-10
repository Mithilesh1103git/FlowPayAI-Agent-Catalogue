
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV FLOWPAY_DB_PATH=/data/flowpayai.sqlite3
ENV FLOWPAY_DUCKDB_PATH=/data/flowpayai.duckdb

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    supervisor \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install -r requirements.txt

COPY . .

# Configure Nginx
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf

RUN mkdir -p /data /var/log/supervisor

RUN chmod +x /app/deploy/entrypoint.sh

RUN groupadd appgroup

RUN useradd -r -g appgroup appuser

RUN chown -R appuser:appgroup /app /data /var/log/supervisor /var/lib/nginx

USER appuser

EXPOSE 8000 8501

VOLUME ["/data"]

CMD ["supervisord", "-n", "-c", "/app/deploy/supervisord.conf"]

