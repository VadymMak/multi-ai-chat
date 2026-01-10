# PostgreSQL Migration Guide

This guide explains how to migrate from SQLite to PostgreSQL while maintaining backward compatibility.

## Overview

The application now supports both SQLite (default for development) and PostgreSQL (recommended for production). The database type is automatically detected based on the `DATABASE_URL` environment variable.

## What Changed

### 1. **Updated Dependencies**

- Added `psycopg2-binary==2.9.9` for PostgreSQL support

### 2. **Database Configuration** (`backend/app/memory/db.py`)

- Auto-detects database type from `DATABASE_URL`
- Uses connection pooling (QueuePool) for PostgreSQL
- Uses NullPool for SQLite (no pooling)
- Logs which database is being used on startup

### 3. **Environment Configuration**

- New `DATABASE_URL` environment variable
- Optional connection pool settings for PostgreSQL
- Example configuration in `.env.example`

## Quick Start

### Option 1: Continue Using SQLite (No Changes Required)

By default, the application uses SQLite. No configuration needed!

```bash
# SQLite is used automatically (default)
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

### Option 2: Switch to PostgreSQL

#### A. Using Docker (Recommended)

1. **Start PostgreSQL with Docker:**

```bash
docker run --name ai-assistant-postgres \
  -e POSTGRES_USER=ai_user \
  -e POSTGRES_PASSWORD=ai_password \
  -e POSTGRES_DB=ai_assistant \
  -p 5432:5432 \
  -d postgres:15-alpine
```

2. **Update your `.env` file:**

```bash
DATABASE_URL=postgresql://ai_user:ai_password@localhost:5432/ai_assistant
```

3. **Install dependencies and run:**

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

4. **Stop/Start PostgreSQL later:**

```bash
# Stop
docker stop ai-assistant-postgres

# Start again
docker start ai-assistant-postgres

# Remove (deletes data!)
docker rm -f ai-assistant-postgres
```

#### B. Using Docker Compose

1. **Create `docker-compose.yml` in project root (if not exists):**

```yaml
version: "3.8"

services:
  postgres:
    image: postgres:15-alpine
    container_name: ai-assistant-postgres
    environment:
      POSTGRES_USER: ai_user
      POSTGRES_PASSWORD: ai_password
      POSTGRES_DB: ai_assistant
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  postgres_data:
```

2. **Start services:**

```bash
docker-compose up -d postgres
```

3. **Update `.env` as shown above**

#### C. Manual PostgreSQL Installation

**On Windows:**

1. Download from: https://www.postgresql.org/download/windows/
2. Install PostgreSQL 15+
3. During installation, remember your password
4. Open pgAdmin or command line

**On macOS:**

```bash
brew install postgresql@15
brew services start postgresql@15
```

**On Linux (Ubuntu/Debian):**

```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
```

**Create Database:**

```bash
# Access PostgreSQL
sudo -u postgres psql

# In PostgreSQL shell
CREATE DATABASE ai_assistant;
CREATE USER ai_user WITH PASSWORD 'ai_password';
GRANT ALL PRIVILEGES ON DATABASE ai_assistant TO ai_user;
\q
```

**Update `.env`:**

```bash
DATABASE_URL=postgresql://ai_user:ai_password@localhost:5432/ai_assistant
```

## Testing the Migration

### 1. Verify Database Connection

Start your application and check the logs:

**SQLite:**

```
✅ SQLite configured (development mode)
Database path: sqlite:///e:\projects\ai-assistant\backend\memory.db
```

**PostgreSQL:**

```
✅ PostgreSQL configured with connection pooling
Database URL: postgresql://ai_user@***
```

### 2. Test Database Operations

```bash
cd backend

# Start the application
python -m uvicorn app.main:app --reload

# In another terminal, test with curl or browse to:
# http://localhost:8000/docs
```

### 3. Verify Tables Were Created

**For PostgreSQL:**

```bash
# Connect to database
docker exec -it ai-assistant-postgres psql -U ai_user -d ai_assistant

# List tables
\dt

# Expected tables:
# - chat_messages
# - chat_sessions
# - memory_entries
# - projects
# - prompt_templates
# - roles
# - ... (and others)

# Exit
\q
```

**For SQLite:**

```bash
cd backend
sqlite3 memory.db ".tables"
```

## Connection Pool Configuration

For PostgreSQL, you can customize connection pooling via environment variables:

```bash
# In .env
DATABASE_URL=postgresql://ai_user:ai_password@localhost:5432/ai_assistant

# Optional pool settings (defaults shown)
SQL_POOL_SIZE=5              # Number of connections to maintain
SQL_MAX_OVERFLOW=10          # Max additional connections
SQL_POOL_TIMEOUT=30          # Seconds to wait for connection
SQL_POOL_RECYCLE=3600        # Recycle connections after 1 hour
```

## Migrating Data from SQLite to PostgreSQL

If you have existing SQLite data you want to migrate:

### Option 1: Using pgloader

```bash
# Install pgloader
# Ubuntu/Debian: sudo apt install pgloader
# macOS: brew install pgloader

# Migrate
pgloader sqlite://./backend/memory.db postgresql://ai_user:ai_password@localhost:5432/ai_assistant
```

### Option 2: Manual Export/Import

```bash
# Export from SQLite
sqlite3 backend/memory.db .dump > dump.sql

# Edit dump.sql to make it PostgreSQL compatible:
# - Remove SQLite-specific syntax
# - Adjust data types if needed

# Import to PostgreSQL
psql -U ai_user -d ai_assistant < dump.sql
```

## Troubleshooting

### Issue: "could not connect to server"

**Solution:** Make sure PostgreSQL is running:

```bash
# Docker
docker ps | grep postgres

# System service
sudo systemctl status postgresql  # Linux
brew services list                 # macOS
```

### Issue: "FATAL: password authentication failed"

**Solution:** Check your credentials in `DATABASE_URL`

### Issue: "database does not exist"

**Solution:** Create the database:

```bash
docker exec -it ai-assistant-postgres psql -U ai_user -c "CREATE DATABASE ai_assistant;"
```

### Issue: ImportError for psycopg2

**Solution:** Reinstall dependencies:

```bash
pip install -r requirements.txt --force-reinstall
```

## Production Deployment

For production, always use PostgreSQL:

### Environment Variables

```bash
# Production PostgreSQL (e.g., on Heroku, Railway, DigitalOcean)
DATABASE_URL=postgresql://user:password@host:5432/dbname

# Connection pooling (adjust based on your plan)
SQL_POOL_SIZE=10
SQL_MAX_OVERFLOW=20
SQL_POOL_TIMEOUT=30
SQL_POOL_RECYCLE=3600
```

### Cloud Providers

**Heroku:**

- Automatically sets `DATABASE_URL`
- No additional configuration needed

**Railway:**

- Copy the PostgreSQL connection string
- Set as `DATABASE_URL` environment variable

**DigitalOcean:**

- Use managed database connection string
- Enable SSL if required

**AWS RDS:**

```bash
DATABASE_URL=postgresql://user:password@your-db.region.rds.amazonaws.com:5432/ai_assistant
```

## Backward Compatibility

The system is fully backward compatible:

- ✅ SQLite works without any changes
- ✅ All existing code works unchanged
- ✅ All models work with both databases
- ✅ No query changes required
- ✅ Switch databases by changing one environment variable

## Performance Considerations

**SQLite:**

- ✅ No setup required
- ✅ Good for development
- ⚠️ Single writer at a time
- ⚠️ Limited for production

**PostgreSQL:**

- ✅ Production-ready
- ✅ Multiple concurrent writers
- ✅ Better performance at scale
- ✅ Advanced features (JSON, full-text search)
- ⚠️ Requires server setup

## Summary

1. **Development:** SQLite (default, no setup)
2. **Production:** PostgreSQL (recommended)
3. **Switch:** Change `DATABASE_URL` environment variable
4. **Easy setup:** Use Docker for quick PostgreSQL
5. **No code changes:** Everything works the same

---

**Need Help?**

- Check logs for database connection status
- Verify `DATABASE_URL` is correct
- Ensure PostgreSQL is running
- Test connection manually with `psql`
