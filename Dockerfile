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

# Start with Gunicorn using Uvicorn workers and auto-scaled worker count
CMD ["sh", "-c", "gunicorn main:app -k uvicorn.workers.UvicornWorker -w $(nproc) -b 0.0.0.0:8080"]
