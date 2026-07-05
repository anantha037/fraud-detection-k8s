# Builder stage
FROM python:3.11-slim AS builder

WORKDIR /build

# Copy requirements
COPY requirements.txt .

# Install dependencies into /install prefix
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Copy installed dependencies from builder
COPY --from=builder /install /usr/local

# Copy application and required model files
COPY app/ app/
COPY model/fraud_model.pkl model/
COPY model/feature_columns.json model/
COPY model/label_encoders.pkl model/
COPY model/preprocessing_info.json model/

# Install curl in runtime stage (needed for healthcheck)
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Create and switch to non-root user
RUN useradd -m appuser
USER appuser

# Set environment variables
ENV MODEL_PATH=model/fraud_model.pkl
ENV PORT=8000

# Expose PORT
EXPOSE $PORT

# Add HEALTHCHECK
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=10s \
  CMD curl -f http://localhost:8000/health || exit 1

# Start the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
