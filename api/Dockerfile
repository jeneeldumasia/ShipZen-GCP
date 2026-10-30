FROM mirror.gcr.io/library/python:3.11.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create non-root user matching Kubernetes runAsUser: 1000
RUN groupadd -r appgroup && useradd -r -g appgroup -u 1000 appuser
USER appuser

EXPOSE 8000

# 4 workers by default; override via WEB_CONCURRENCY env var per environment
# Prometheus multi-process mode: every uvicorn worker writes its metrics to
# this directory and /metrics merges them. It must exist and be empty at start
# (/tmp is a writable emptyDir; the root filesystem is read-only).
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus
CMD ["sh", "-c", "rm -rf \"$PROMETHEUS_MULTIPROC_DIR\" && mkdir -p \"$PROMETHEUS_MULTIPROC_DIR\" && uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers --workers ${WEB_CONCURRENCY:-4}"]
