FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose default port
EXPOSE 5000

# Default environment variables
ENV PORT=5000
ENV FLASK_ENV=production
ENV DATABASE_URL=sqlite:///./unisync.db

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5000/api/resources || exit 1

# Start gunicorn WSGI server
CMD ["gunicorn", "run:app", "--workers", "2", "--bind", "0.0.0.0:5000"]
