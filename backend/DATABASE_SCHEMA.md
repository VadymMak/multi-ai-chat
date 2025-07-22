# 📊 Database Schema - AI Assistant Project

## 🗄️ Database Configuration

**Database Engine:** SQLAlchemy ORM  
**Default DB:** SQLite (`backend/memory.db`)  
**Database URL:** `SQLALCHEMY_URL` environment variable (default: `sqlite:///memory.db`)  
**Connection Mode:** WAL (Write-Ahead Logging) for better concurrency

### SQLite Optimization Settings (db.py)

```python
PRAGMA foreign_keys=ON          # Enforce foreign key constraints
PRAGMA journal_mode=WAL         # Write-Ahead Logging for concurrency
PRAGMA synchronous=NORMAL       # Balance performance/durability
PRAGMA cache_size=-64000        # 64MB memory cache
```

---

## 📁 Memory Folder Structure

```
backend/app/memory/
├── __init__.py              # Package initialization
├── db.py                    # Database engine, session management, init
├── models.py                # SQLAlchemy ORM models (all tables)
├── manager.py               # MemoryManager class (business logic)
├── utils.py                 # Utility functions
└── schemas/
    └── prompt_template.py   # Pydantic schemas for API validation
```

---

## 🗃️ Database Tables

### 1. **roles** - AI Agent Roles

Stores different AI agent personas (Developer, Analyst, Architect, etc.)

```python
Table: roles
├── id: Integer [PK] [Auto-increment]
├── name: String(50) [Unique] [Not Null] [Indexed]
└── description: String(255) [Nullable]

Indexes:
  - ix_roles_name (name)

Relationships:
  → memories: MemoryEntry[] (back_populates="role", ON DELETE SET NULL)
  → role_projects: RoleProjectLink[] (cascade="all, delete")
  → prompt_templates: PromptTemplate[] (cascade="all, delete")
  → canon_items: CanonItem[] (ON DELETE SET NULL)
```

**Example Data:**

- Developer
- Business Analyst
- Technical Architect
- QA Engineer

---

### 2. **projects** - Project Definitions

Stores project information and structure

```python
Table: projects
├── id: Integer [PK] [Auto-increment]
├── name: String(100) [Unique] [Not Null] [Indexed]
├── description: Text [Nullable]
└── project_structure: Text [Nullable]

Indexes:
  - ix_projects_name (name)

Relationships:
  → memories: MemoryEntry[] (viewonly, via project_id_int)
  → role_projects: RoleProjectLink[] (cascade="all, delete")
  → canon_items: CanonItem[] (viewonly, via project_id_int)
```

---

### 3. **role_project_link** - Many-to-Many Link

Links roles to projects (which roles work on which projects)

```python
Table: role_project_link
├── id: Integer [PK] [Auto-increment]
├── role_id: Integer [FK → roles.id] [ON DELETE CASCADE] [Not Null]
└── project_id: Integer [FK → projects.id] [ON DELETE CASCADE] [Not Null]

Indexes:
  - ix_role_project_unique (role_id, project_id) [UNIQUE]

Relationships:
  → role: Role (back_populates="role_projects")
  → project: Project (back_populates="role_projects")
```

**Purpose:** Defines which AI roles are assigned to which projects

---

### 4. **memory_entries** - Chat Messages & Summaries

Stores all chat messages, AI responses, and conversation summaries

```python
Table: memory_entries
├── id: Integer [PK] [Auto-increment]
├── project_id: String(255) [Not Null] [Indexed]
├── project_id_int: Integer [FK → projects.id] [ON DELETE CASCADE] [Nullable]
├── role_id: Integer [FK → roles.id] [ON DELETE SET NULL] [Nullable] [Indexed]
├── chat_session_id: String(255) [Nullable] [Indexed]
├── timestamp: DateTime [Default: utcnow()] [Indexed]
├── tokens: Integer [Nullable]
├── summary: Text [Nullable]
├── raw_text: Text [Nullable]
├── is_summary: Boolean [Default: False] [Not Null] [Indexed]
└── is_ai_to_ai: Boolean [Default: False] [Not Null]

Indexes:
  - ix_memory_entries_project_id (project_id)
  - ix_memory_entries_role_id (role_id)
  - ix_memory_entries_chat_session_id (chat_session_id)
  - ix_memory_entries_timestamp (timestamp)
  - ix_memory_entries_is_summary (is_summary)
  - ix_mem_role_proj_sess_time (role_id, project_id, chat_session_id, timestamp)
  - ix_mem_proj_role_is_summary_time (project_id, role_id, is_summary, timestamp)

Relationships:
  → role: Role (back_populates="memories", ON DELETE SET NULL)
  → project: Project (viewonly, via project_id_int)
```

**Key Fields:**

- `project_id`: String ID for API filtering
- `project_id_int`: Integer FK for database joins
- `is_summary`: Flags conversation summaries
- `is_ai_to_ai`: Flags AI-to-AI conversations
- `raw_text`: Format: "{sender}: {message_content}"

---

### 5. **canon_items** - Canonical Project Documents

Stores project knowledge: ADRs, changelogs, backlog, glossary, PMD

```python
Table: canon_items
├── id: Integer [PK] [Auto-increment]
├── project_id: String(255) [Not Null] [Indexed]
├── project_id_int: Integer [FK → projects.id] [ON DELETE CASCADE] [Nullable]
├── role_id: Integer [FK → roles.id] [ON DELETE SET NULL] [Nullable] [Indexed]
├── type: String(32) [Not Null] [Indexed]
├── title: String(256) [Not Null] [Indexed]
├── body: Text [Not Null]
├── tags: JSON [Nullable]
├── terms: Text [Nullable]
├── created_at: DateTime [Default: utcnow()] [Indexed]
├── updated_at: DateTime [Default: utcnow()] [On Update: utcnow()]
└── is_active: Boolean [Default: True] [Not Null] [Indexed]

Indexes:
  - ix_canon_items_project_id (project_id)
  - ix_canon_items_role_id (role_id)
  - ix_canon_items_type (type)
  - ix_canon_items_title (title)
  - ix_canon_items_created_at (created_at)
  - ix_canon_items_is_active (is_active)
  - ix_canon_proj_role_type_time (project_id, role_id, type, created_at)
  - ix_canon_title_terms (title, terms)

Relationships:
  → role: Role (back_populates="canon_items", ON DELETE SET NULL)
  → project: Project (viewonly, via project_id_int)
```

**Document Types:**

- `ADR` - Architecture Decision Records
- `CHANGELOG` - Change logs
- `BACKLOG` - Task backlog
- `GLOSSARY` - Term definitions
- `PMD` - Project Management Documents

---

### 6. **prompt_templates** - Role-Specific Prompts

Stores custom prompt templates for each role

```python
Table: prompt_templates
├── id: Integer [PK] [Auto-increment]
├── role_id: Integer [FK → roles.id] [ON DELETE CASCADE] [Not Null] [Indexed]
├── name: String(100) [Not Null]
├── content: Text [Not Null]
└── is_default: Boolean [Default: False]

Indexes:
  - ix_prompt_templates_role_id (role_id)
  - ix_prompt_unique_per_role (role_id, name) [UNIQUE]

Relationships:
  → role: Role (back_populates="prompt_templates")
```

**Purpose:** Custom system prompts tailored to each AI role

---

### 7. **audit_logs** - Activity Audit Trail

Tracks all AI interactions and model usage

```python
Table: audit_logs
├── id: Integer [PK] [Auto-increment]
├── project_id: String(255) [Not Null] [Indexed]
├── role_id: Integer [Not Null] [Indexed]
├── chat_session_id: String(255) [Nullable] [Indexed]
├── provider: String(50) [Not Null] [Indexed]
├── action: String(50) [Not Null]
├── query: Text [Nullable]
├── timestamp: DateTime [Default: utcnow()] [Indexed]
└── model_version: String(50) [Nullable]

Indexes:
  - ix_audit_logs_project_id (project_id)
  - ix_audit_logs_role_id (role_id)
  - ix_audit_logs_chat_session_id (chat_session_id)
  - ix_audit_logs_provider (provider)
  - ix_audit_logs_timestamp (timestamp)
```

**Tracked Providers:**

- openai
- anthropic (Claude)
- youtube
- internal

---

## 🔗 Entity Relationship Diagram

```
┌──────────────┐         ┌─────────────────┐         ┌──────────────┐
│   roles      │         │ role_project_   │         │  projects    │
│              │◄───────┤│     link        │├───────►│              │
│ • id (PK)    │ 1     M │                 │ M     1 │ • id (PK)    │
│ • name       │         │ • id (PK)       │         │ • name       │
│ • description│         │ • role_id (FK)  │         │ • description│
└──────┬───────┘         │ • project_id(FK)│         └──────┬───────┘
       │                 └─────────────────┘                │
       │ 1                                                  │ 1
       │                                                    │
       │ M                                                  │ M
       │                  ┌──────────────────┐             │
       └─────────────────►│ memory_entries   │◄────────────┘
       │                  │                  │
       │                  │ • id (PK)        │
       │                  │ • project_id     │
       │                  │ • project_id_int │
       │                  │ • role_id (FK)   │
       │                  │ • chat_session_id│
       │                  │ • timestamp      │
       │                  │ • tokens         │
       │                  │ • summary        │
       │                  │ • raw_text       │
       │                  │ • is_summary     │
       │                  │ • is_ai_to_ai    │
       │                  └──────────────────┘
       │
       │ 1                ┌──────────────────┐
       ├─────────────────►│  canon_items     │
       │ M                │                  │
       │                  │ • id (PK)        │
       │                  │ • project_id     │
       │                  │ • project_id_int │
       │                  │ • role_id (FK)   │
       │                  │ • type           │
       │                  │ • title          │
       │                  │ • body           │
       │                  │ • tags           │
       │                  │ • terms          │
       │                  │ • created_at     │
       │                  │ • updated_at     │
       │                  │ • is_active      │
       │                  └──────────────────┘
       │
       │ 1                ┌──────────────────┐
       └─────────────────►│ prompt_templates │
         M                │                  │
                          │ • id (PK)        │
                          │ • role_id (FK)   │
                          │ • name           │
                          │ • content        │
                          │ • is_default     │
                          └──────────────────┘

                          ┌──────────────────┐
                          │  audit_logs      │
                          │                  │
                          │ • id (PK)        │
                          │ • project_id     │
                          │ • role_id        │
                          │ • chat_session_id│
                          │ • provider       │
                          │ • action         │
                          │ • query          │
                          │ • timestamp      │
                          │ • model_version  │
                          └──────────────────┘
```

---

## 🧠 MemoryManager Functions (manager.py)

### Session Management

```python
get_or_create_chat_session_id(role_id, project_id) -> str
  # Returns existing session ID or creates new UUID

preflight_token_budget(texts, soft, hard) -> Dict
  # Checks if text fits within token limits
  # Returns: {total_tokens, near_soft, over_hard, soft, hard}
```

### Token Operations

```python
count_tokens(text: str) -> int
  # Uses tiktoken (o200k_base) or fallback (len/4)
  # Logs token counts if settings.LOG_TOKEN_COUNTS=True
```

### Summary Generation

```python
summarize_messages(messages: List[str]) -> str
  # Uses OpenAI API to create ~600 token summaries
  # Focuses on decisions, requirements, code, next steps

summarize_text(text: str) -> str
  # Wrapper around summarize_messages for single text
```

### Writing Data

```python
store_memory(project_id, role_id, summary, raw_text,
             chat_session_id, is_ai_to_ai) -> MemoryEntry
  # Stores summarized conversation
  # Auto-counts tokens, limits text length
  # Sets is_summary=True

store_chat_message(project_id, role_id, chat_session_id,
                   sender, text, is_summary, is_ai_to_ai) -> MemoryEntry
  # Stores individual chat turn
  # Format: "{sender}: {text}"
  # Default: is_summary=False
```

### Canon Operations

```python
store_canon_item(project_id, role_id, type, title, body,
                 tags, terms) -> Optional[int]
  # Stores ADR/CHANGELOG/BACKLOG/GLOSSARY/PMD
  # Returns canon item ID or None if disabled
  # Requires: settings.ENABLE_CANON=True

save_canon_items(items: List[Dict]) -> List[Optional[int]]
  # Batch save multiple canon items
  # Returns list of IDs

search_canon_items(project_id, role_id, query_terms,
                   top_k, types, include_global_roleless) -> List[CanonItem]
  # Full-text search across canon items
  # Searches: title, body, terms fields
  # Filters by: project, role, type, active status
  # Returns: ordered by created_at DESC

retrieve_context_digest(project_id, role_id, query_terms,
                        top_k) -> Tuple[str, List[Dict]]
  # Returns formatted digest + raw items
  # Digest format: "### Canonical Context\n[TYPE] title\nbody..."

extract_canon_deltas(text, project_id, role_id) -> List[Dict]
  # LLM-based extraction of canon items from text
  # Fallback: heuristic keyword matching
  # Returns: [{type, title, body, tags, terms}]
```

### Reading Data

```python
retrieve_messages(project_id, role_id, limit,
                  chat_session_id, include_summaries) -> List[dict]
  # Gets recent chat messages (newest last)
  # Default: excludes summaries (include_summaries=False)
  # Returns: [{sender, text, role_id, project_id, ...}]

load_recent_summaries(project_id, role_id, limit) -> List[str]
  # Gets recent summary texts only
  # Filters: is_summary=True
  # Returns: ordered by timestamp DESC
```

### Cleanup

```python
delete_chat_messages(project_id, role_id, chat_session_id,
                     keep_summaries) -> None
  # Deletes chat messages for session
  # Default: keep_summaries=True (preserves summaries)
```

### Discovery

```python
get_last_session(role_id, project_id) -> Optional[dict]
  # Finds most recent chat session
  # Returns: {project_id, role_id, chat_session_id, role_name}
```

### Audit

```python
insert_audit_log(project_id, role_id, chat_session_id,
                 provider, action, query, model_version) -> None
  # Logs AI interactions
  # Providers: openai, anthropic, youtube, internal
  # Actions: query, response, error, canon_insert, etc.
```

---

## 🔑 Key Design Patterns

### Dual Project ID Strategy

- `project_id` (String): For API filtering, backward compatibility
- `project_id_int` (Integer): For efficient database joins

### Foreign Key Policies

- **CASCADE DELETE**: role_project_link, prompt_templates
- **SET NULL**: memory_entries.role_id, canon_items.role_id
- Preserves data when roles/projects are deleted

### Text Safety

```python
safe_text(text: str) -> str
  # Unicode normalization (NFKD)
  # Removes surrogates
  # UTF-8 encoding with error handling
```

### Token Budgeting

- **Soft Limit**: 6000 tokens (80% warning threshold)
- **Hard Limit**: 7800 tokens (cutoff)
- Uses tiktoken for accurate counting

### Content Limits

```python
MAX_RAW_TEXT_LEN = 10,000     # Chat message text
MAX_SUMMARY_LEN = 2,000       # Summary preview
MAX_CANON_BODY_LEN = 8,000    # Canon document body
```

---

## 📊 Performance Optimizations

### Composite Indexes

```sql
-- Memory entries
ix_mem_role_proj_sess_time (role_id, project_id, chat_session_id, timestamp)
ix_mem_proj_role_is_summary_time (project_id, role_id, is_summary, timestamp)

-- Canon items
ix_canon_proj_role_type_time (project_id, role_id, type, created_at)
ix_canon_title_terms (title, terms)

-- Unique constraints
ix_role_project_unique (role_id, project_id)
ix_prompt_unique_per_role (role_id, name)
```

### SQLite WAL Mode

- Concurrent readers while writing
- Better performance for multiple connections
- 64MB in-memory cache

### Query Patterns

- Ordered DESC for recent items
- Limit queries for pagination
- Strategic use of viewonly relationships

---

## 🔄 Database Initialization

```python
# From db.py
init_db(retries=3, delay=1.0)
  # Creates all tables
  # Retries for container startup races
  # Auto-runs on import if INIT_DB_ON_IMPORT=1
```

**Environment Variables:**

```bash
SQLALCHEMY_URL=sqlite:///memory.db    # Database connection
SQLALCHEMY_ECHO=0                     # Log SQL queries
INIT_DB_ON_IMPORT=1                   # Auto-initialize tables
ENABLE_CANON=True                     # Enable canon features
```

---

## 📝 Usage Examples

### Creating a Chat Message

```python
from app.memory.manager import MemoryManager
from app.memory.db import get_session

db = get_session()
manager = MemoryManager(db)

manager.store_chat_message(
    project_id="proj-123",
    role_id=1,
    chat_session_id="uuid-abc",
    sender="user",
    text="How do I implement authentication?"
)
```

### Storing a Canon Item

```python
manager.store_canon_item(
    project_id="proj-123",
    role_id=1,
    type="ADR",
    title="Use JWT for authentication",
    body="Decision: We will use JWT tokens because...",
    tags=["security", "auth"],
    terms="JWT, authentication, security"
)
```

### Retrieving Context

```python
# Get recent messages
messages = manager.retrieve_messages(
    project_id="proj-123",
    role_id=1,
    limit=10,
    include_summaries=False
)

# Get canon digest
digest, items = manager.retrieve_context_digest(
    project_id="proj-123",
    role_id=1,
    query_terms=["authentication", "security"],
    top_k=5
)
```

---

## 🎯 Summary

**Total Tables:** 7

- 2 Core entities (roles, projects)
- 1 Link table (role_project_link)
- 3 Content tables (memory_entries, canon_items, prompt_templates)
- 1 Audit table (audit_logs)

**Total Indexes:** 25+ (including composite indexes)

**Key Features:**

- ✅ Multi-project, multi-role support
- ✅ Chat history with summarization
- ✅ Canonical project documents (ADR, changelog, etc.)
- ✅ Token budget management
- ✅ Full audit trail
- ✅ SQLite optimizations for concurrency
- ✅ Flexible project ID strategy (string + int)

**Database Size:**

- Development: ~5-50 MB
- Production: Scales with message history
