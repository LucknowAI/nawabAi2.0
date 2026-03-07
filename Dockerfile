# Use Python 3.12.10 as the base image
FROM python:3.12.10-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libffi-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directory for query logs
RUN mkdir -p query_logs && chmod 777 query_logs

# Expose port 8080
EXPOSE 8080

# Run DB migrations then start Gunicorn with 2 Uvicorn workers.
# --timeout 120 accommodates long-running AG-UI streaming responses.
# --graceful-timeout 30 lets in-flight requests finish before shutdown.
CMD ["sh", "-c", "alembic upgrade head && gunicorn main:app -k uvicorn.workers.UvicornWorker -w 2 --timeout 120 --graceful-timeout 30 -b 0.0.0.0:$PORT"]
