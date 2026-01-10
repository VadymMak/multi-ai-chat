# Use official Python base image
FROM python:3.11-slim

# Set work directory
WORKDIR /app

# Copy backend code
COPY ./backend /app

# Install dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Expose port (FastAPI runs on 8000)
EXPOSE 8000

# Default command to run FastAPI app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
