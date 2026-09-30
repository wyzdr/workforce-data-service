# Stage 1: Build dependencies
FROM python:3.11-slim AS builder
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime environment (least privilege security principle)
FROM python:3.11-slim
WORKDIR /app

# Comply with federal IT security standards: run as dedicated non-root user
RUN useradd -u 8888 appuser && chown -R appuser:appuser /app
COPY --from=builder /root/.local /home/appuser/.local
COPY --chown=appuser:appuser . .

USER appuser
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Run on container
CMD ["sh", "-c", "python import_data.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]