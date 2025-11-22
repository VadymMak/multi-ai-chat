# Dockerfile for Railway Backend Deployment
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better caching)
COPY backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/app /app/app

# Copy migration scripts
COPY backend/scripts /app/backend/scripts
COPY backend/migrations /app/backend/migrations

# Create uploads directory
RUN mkdir -p /app/uploads

# Expose port (Railway will set PORT env var)
EXPOSE 8000

# Run check_users, then migrations, then start server
CMD ["sh", "-c", "export PYTHONPATH=/app:$PYTHONPATH && python backend/scripts/check_users.py && python backend/scripts/init_auth_tables.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]