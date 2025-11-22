# Database Migrations

This directory contains database migration scripts for the AI Assistant application.

## Available Migrations

### add_user_id_to_projects.py

Adds multi-user support to the projects table.

**Changes:**

- Adds `user_id` column (foreign key to users table)
- Adds `assistant_id` column (foreign key to roles table)
- Adds `created_at` and `updated_at` timestamp columns
- Sets existing projects to admin user
- Adds appropriate foreign key constraints

**Usage:**

```bash
cd backend
python migrations/add_user_id_to_projects.py
```

**Safety Features:**

- ✅ Idempotent - can be run multiple times safely
- ✅ Transaction rollback on error
- ✅ Pre-flight checks (admin user exists, etc.)
- ✅ User confirmation required
- ✅ Detailed progress output

## Running Migrations

### Prerequisites

1. Ensure PostgreSQL database is running
2. Ensure database connection is configured in `.env`
3. Ensure superuser account exists in database

### Steps

1. **Backup your database** (recommended):

   ```bash
   pg_dump -U postgres ai_assistant > backup_$(date +%Y%m%d).sql
   ```

2. **Run the migration**:

   ```bash
   cd backend
   python migrations/add_user_id_to_projects.py
   ```

3. **Verify the migration**:

   ```bash
   # Check table structure
   psql -U postgres -d ai_assistant -c "\d projects"

   # Check that user_id exists
   psql -U postgres -d ai_assistant -c "SELECT column_name FROM information_schema.columns WHERE table_name='projects';"
   ```

4. **Restart the backend**:
   ```bash
   uvicorn app.main:app --reload
   ```

## Testing After Migration

### Test Projects API

```powershell
# Login
$loginBody = @{ username = "testuser"; password = "test12345" }
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/auth/login" `
    -Method Post -Body $loginBody -ContentType "application/x-www-form-urlencoded"
$TOKEN = $response.access_token
$headers = @{ "Authorization" = "Bearer $TOKEN" }

# List projects (should return only user's projects)
Invoke-RestMethod -Uri "http://localhost:8000/api/projects" -Headers $headers

# Create a new project
$projectBody = @{
    name = "Test Project"
    description = "Testing multi-user projects"
    assistant_id = 1
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/api/projects" `
    -Method Post `
    -Headers $headers `
    -Body $projectBody `
    -ContentType "application/json"
```

## Expected Behavior

### Before Migration

- ❌ GET/POST to `/api/projects` returns 500 error
- ❌ Error: "column projects.user_id does not exist"
- ❌ Projects not isolated by user

### After Migration

- ✅ GET `/api/projects` returns 200 OK with user's projects only
- ✅ POST `/api/projects` creates project with user_id
- ✅ Each user sees only their own projects
- ✅ Projects are properly isolated by user

## Rollback

If you need to rollback the migration:

```sql
-- Remove the columns (WARNING: This will delete data!)
ALTER TABLE projects DROP COLUMN IF EXISTS user_id CASCADE;
ALTER TABLE projects DROP COLUMN IF EXISTS assistant_id CASCADE;
ALTER TABLE projects DROP COLUMN IF EXISTS created_at;
ALTER TABLE projects DROP COLUMN IF EXISTS updated_at;
```

**Note:** Rollback will remove the multi-user functionality. Ensure you have a database backup before running migrations.

## Troubleshooting

### "No superuser found" Error

Create a superuser first:

```bash
python scripts/init_auth_tables.py
```

Or manually in psql:

```sql
INSERT INTO users (email, username, password_hash, status, is_superuser, is_active)
VALUES (
    'admin@example.com',
    'admin',
    '$2b$12$yourhashhere',  -- Generate with: python -c "from passlib.hash import bcrypt; print(bcrypt.hash('yourpassword'))"
    'active',
    true,
    true
);
```

### "Column already exists" Error

This means the migration was already applied. The script is idempotent and will skip if already run.

### Transaction Rollback

If the migration fails at any step, all changes are automatically rolled back. Check the error output for details.

## Creating New Migrations

When creating new migration scripts:

1. Use descriptive filenames: `add_feature_name.py`
2. Include docstring describing the changes
3. Implement idempotency checks
4. Use transactions with rollback
5. Add detailed progress output
6. Include user confirmation prompt
7. Show final structure after migration

Example template:

```python
"""
Database Migration: Description of changes
"""

from sqlalchemy import text, inspect
from app.memory.db import engine
import sys

def check_migration_needed() -> bool:
    """Check if migration is needed"""
    # Implement check logic
    pass

def migrate():
    """Run the migration"""
    conn = engine.connect()
    trans = conn.begin()

    try:
        # Migration steps
        trans.commit()
        return True
    except Exception as e:
        print(f"Migration failed: {e}")
        trans.rollback()
        return False
    finally:
        conn.close()

def main():
    """Main entry point"""
    # Confirmation prompt
    # Run migration
    # Return exit code
    pass

if __name__ == "__main__":
    sys.exit(main())
```

## Best Practices

1. **Always backup** before running migrations
2. **Test locally** before running in production
3. **Read the output** carefully during migration
4. **Verify results** with psql after migration
5. **Restart services** after migration completes
6. **Monitor logs** after restart for any errors

## Support

If you encounter issues:

1. Check the error message in the migration output
2. Verify database connection settings
3. Ensure database user has ALTER TABLE permissions
4. Check that all referenced tables exist
5. Review the migration logs for detailed traceback
