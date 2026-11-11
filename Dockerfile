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

# Remove default port-80 site and configure Nginx for non-root execution
RUN rm -f /etc/nginx/sites-enabled/default && \
    sed -i 's|/run/nginx.pid|/tmp/nginx.pid|g' /etc/nginx/nginx.conf && \
    sed -i 's|/var/log/nginx/error.log|/dev/stderr|g' /etc/nginx/nginx.conf && \
    sed -i 's|/var/log/nginx/access.log|/dev/stdout|g' /etc/nginx/nginx.conf && \
    sed -i '/^user /d' /etc/nginx/nginx.conf

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf

RUN mkdir -p /data /var/log/supervisor /var/log/nginx /var/lib/nginx /var/cache/nginx && \
    chmod +x /app/deploy/entrypoint.sh && \
    groupadd appgroup && \
    useradd -r -g appgroup appuser && \
    chown -R appuser:appgroup /app /data /var/log/supervisor /var/log/nginx /var/lib/nginx /var/cache/nginx /etc/nginx

USER appuser

EXPOSE 7860

VOLUME ["/data"]

CMD ["supervisord", "-n", "-c", "/app/deploy/supervisord.conf"]
