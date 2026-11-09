FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 FLOWPAY_DB_PATH=/data/flowpayai.sqlite3 FLOWPAY_DUCKDB_PATH=/data/flowpayai.duckdb
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends nginx supervisor build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN mkdir -p /data && chmod +x /app/deploy/entrypoint.sh
EXPOSE 7860
CMD ["/app/deploy/entrypoint.sh"]\n