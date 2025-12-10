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
EXPOSE ${PORT:-8000}

# Run check_users, init_auth, migrations, then start server
CMD ["sh", "-c", "export PYTHONPATH=/app:$PYTHONPATH && \
     python backend/scripts/check_users.py && \
     python backend/scripts/init_auth_tables.py && \
     python backend/migrations/add_git_integration_to_projects.py && \
     python backend/migrations/add_file_dependencies_table.py && \
     python backend/migrations/add_file_specifications_table.py && \
     python backend/migrations/add_file_embeddings_table.py && \
     python backend/migrations/add_query_classification_logs.py && \
     python backend/migrations/add_folder_identifier.py && \
     python backend/migrations/add_index_status_to_projects.py && \
     uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]