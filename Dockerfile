# Stage 1: Build dependencies
FROM python:3.11-slim AS builder
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime environment (least privilege security principle)
FROM python:3.11-slim
WORKDIR /app

# Comply with federal IT security standards: create home dir (-m) and dedicated non-root user (UID 10001)
RUN useradd -m -u 10001 appuser

# Copy installed Python packages to appuser's local directory with correct ownership
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local

# Copy application source code and grant write ownership to appuser for SQLite generation
COPY --chown=appuser:appuser . .
RUN chown -R appuser:appuser /app

USER appuser
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Automatically run ETL pipeline on startup, then launch FastAPI
CMD ["sh", "-c", "python import_data.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]