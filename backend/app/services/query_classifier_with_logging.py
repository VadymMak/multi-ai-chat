# File: backend/app/services/query_classifier_with_logging.py
"""
Query Classifier with Background Logging (Week 2 Version)

SIMPLE APPROACH FOR WEEK 2:
- Uses rule-based classification (fast, reliable)
- Logs queries in background (non-blocking)
- Collects data for future ML training
- NO ML model yet - will add in Phase 3

After 100+ queries logged → Can train ML model later
"""

from typing import Optional, Dict, List
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text

# Import rule-based classifier
from .query_classifier import QueryType, classify_query


# ====================================================================
# DATABASE SCHEMA (Run this migration first)
# ====================================================================

"""
CREATE TABLE IF NOT EXISTS query_classification_logs (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER,
    query TEXT NOT NULL,
    classified_as VARCHAR(50) NOT NULL,
    search_results_count INTEGER,
    search_took_ms INTEGER,
    timestamp TIMESTAMP DEFAULT NOW(),
    
    -- For future analysis
    user_clicked_result INTEGER,  -- Which result user clicked (1-5)
    user_satisfied BOOLEAN,       -- Did user find what they needed?
    
    -- Index for fast queries
    INDEX idx_query_logs_project (project_id),
    INDEX idx_query_logs_timestamp (timestamp),
    INDEX idx_query_logs_classified (classified_as)
);
"""


# ====================================================================
# BACKGROUND LOGGER (NON-BLOCKING)
# ====================================================================

class QueryLogger:
    """
    Background logger for query classifications.
    
    Logs to PostgreSQL without blocking search results.
    Data can be exported later for ML training.
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def log_query_classification(
        self,
        project_id: int,
        query: str,
        classified_as: QueryType,
        user_id: Optional[int] = None,
        search_results_count: int = 0,
        search_took_ms: int = 0
    ):
        """
        Log a query classification in background.
        
        This is NON-BLOCKING - errors are caught and logged,
        but won't break the search functionality.
        
        Args:
            project_id: Project being searched
            query: User's search query
            classified_as: QueryType from classifier
            user_id: User who made the query
            search_results_count: How many results returned
            search_took_ms: Search execution time
        """
        
        try:
            # Insert log (background, don't wait)
            self.db.execute(
                text("""
                    INSERT INTO query_classification_logs 
                    (project_id, user_id, query, classified_as, 
                     search_results_count, search_took_ms, timestamp)
                    VALUES 
                    (:project_id, :user_id, :query, :classified_as, 
                     :search_results_count, :search_took_ms, NOW())
                """),
                {
                    "project_id": project_id,
                    "user_id": user_id,
                    "query": query,
                    "classified_as": classified_as.value,
                    "search_results_count": search_results_count,
                    "search_took_ms": search_took_ms
                }
            )
            
            # Commit in background (async would be better, but keep simple)
            self.db.commit()
            
        except Exception as e:
            # Log error but DON'T break search
            print(f"[WARNING] Failed to log query: {e}")
            self.db.rollback()
    
    def log_user_feedback(
        self,
        query_log_id: int,
        user_clicked_result: Optional[int] = None,
        user_satisfied: Optional[bool] = None
    ):
        """
        Log user feedback on search results.
        
        This helps measure if classification was good:
        - Which result did user click? (1st, 2nd, 3rd?)
        - Did user find what they needed?
        
        GOLD DATA for training ML model later!
        """
        
        try:
            updates = []
            params = {"id": query_log_id}
            
            if user_clicked_result is not None:
                updates.append("user_clicked_result = :clicked")
                params["clicked"] = user_clicked_result
            
            if user_satisfied is not None:
                updates.append("user_satisfied = :satisfied")
                params["satisfied"] = user_satisfied
            
            if updates:
                self.db.execute(
                    text(f"""
                        UPDATE query_classification_logs 
                        SET {', '.join(updates)}
                        WHERE id = :id
                    """),
                    params
                )
                self.db.commit()
                
        except Exception as e:
            print(f"[WARNING] Failed to log feedback: {e}")
            self.db.rollback()


# ====================================================================
# MAIN INTERFACE (WEEK 2 VERSION)
# ====================================================================

def classify_and_log(
    query: str,
    project_id: int,
    db: Session,
    user_id: Optional[int] = None,
    enable_logging: bool = True
) -> QueryType:
    """
    Classify query + log in background.
    
    WEEK 2 VERSION: Simple rule-based + background logging
    
    Usage in file_indexer.py:
        from .query_classifier_with_logging import classify_and_log
        
        query_type = classify_and_log(
            query=query,
            project_id=project_id,
            db=db,
            user_id=current_user.id
        )
        
        # Then route to appropriate search strategy
        if query_type == QueryType.FILENAME:
            results = await search_by_filename(...)
        elif query_type == QueryType.SYMBOL:
            results = await search_by_symbol(...)
        ...
    
    Args:
        query: Search query from user
        project_id: Project being searched
        db: Database session
        user_id: Current user (optional)
        enable_logging: Set False to disable logging
        
    Returns:
        QueryType for routing search strategy
    """
    
    # 1. Classify using rule-based logic (fast!)
    query_type = classify_query(query)
    
    # 2. Log in background (non-blocking)
    if enable_logging:
        try:
            logger = QueryLogger(db)
            logger.log_query_classification(
                project_id=project_id,
                query=query,
                classified_as=query_type,
                user_id=user_id,
                search_results_count=0,  # Will update after search
                search_took_ms=0         # Will update after search
            )
        except Exception as e:
            # Don't break search if logging fails
            print(f"[WARNING] Query logging failed: {e}")
    
    return query_type


# ====================================================================
# DATA EXPORT FOR ML TRAINING (FUTURE USE)
# ====================================================================

def export_training_data(
    db: Session,
    min_samples: int = 100,
    output_file: str = "/tmp/query_training_data.json"
) -> Dict[str, any]:
    """
    Export logged queries for ML model training.
    
    USE THIS LATER (Phase 3) when you have 100+ logged queries.
    
    Returns JSON file with:
    - queries: List of search queries
    - labels: List of QueryTypes (from rule-based classifier)
    - metadata: Results count, user satisfaction, etc.
    
    Usage:
        data = export_training_data(db, min_samples=100)
        # Then train sklearn model with this data
    """
    
    try:
        # Get all logged queries
        result = db.execute(
            text("""
                SELECT 
                    query,
                    classified_as,
                    search_results_count,
                    user_clicked_result,
                    user_satisfied,
                    COUNT(*) as frequency
                FROM query_classification_logs
                GROUP BY query, classified_as, search_results_count, 
                         user_clicked_result, user_satisfied
                HAVING COUNT(*) >= 1
                ORDER BY frequency DESC
            """)
        )
        
        queries = []
        labels = []
        metadata = []
        
        for row in result:
            queries.append(row.query)
            labels.append(row.classified_as)
            metadata.append({
                "results_count": row.search_results_count,
                "user_clicked": row.user_clicked_result,
                "user_satisfied": row.user_satisfied,
                "frequency": row.frequency
            })
        
        data = {
            "total_samples": len(queries),
            "queries": queries,
            "labels": labels,
            "metadata": metadata,
            "exported_at": datetime.now().isoformat()
        }
        
        # Save to file
        import json
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"✅ Exported {len(queries)} training samples to {output_file}")
        
        return data
        
    except Exception as e:
        print(f"❌ Export failed: {e}")
        return {"error": str(e)}


def get_classification_stats(db: Session) -> Dict[str, any]:
    """
    Get statistics on logged classifications.
    
    Useful for deciding if/when to train ML model.
    
    Usage:
        stats = get_classification_stats(db)
        print(f"Total queries: {stats['total_queries']}")
        print(f"By type: {stats['by_type']}")
    """
    
    try:
        # Total queries
        total = db.execute(
            text("SELECT COUNT(*) FROM query_classification_logs")
        ).scalar()
        
        # By classification type
        by_type = db.execute(
            text("""
                SELECT classified_as, COUNT(*) as count
                FROM query_classification_logs
                GROUP BY classified_as
                ORDER BY count DESC
            """)
        ).fetchall()
        
        # Average results count
        avg_results = db.execute(
            text("""
                SELECT AVG(search_results_count) 
                FROM query_classification_logs
                WHERE search_results_count > 0
            """)
        ).scalar() or 0
        
        # User satisfaction (if tracked)
        satisfaction = db.execute(
            text("""
                SELECT 
                    COUNT(CASE WHEN user_satisfied = true THEN 1 END) as satisfied,
                    COUNT(CASE WHEN user_satisfied = false THEN 1 END) as not_satisfied,
                    COUNT(CASE WHEN user_satisfied IS NULL THEN 1 END) as unknown
                FROM query_classification_logs
            """)
        ).fetchone()
        
        return {
            "total_queries": total,
            "by_type": {row.classified_as: row.count for row in by_type},
            "avg_results_per_query": round(avg_results, 2),
            "user_satisfaction": {
                "satisfied": satisfaction.satisfied if satisfaction else 0,
                "not_satisfied": satisfaction.not_satisfied if satisfaction else 0,
                "unknown": satisfaction.unknown if satisfaction else 0
            },
            "ready_for_ml": total >= 100
        }
        
    except Exception as e:
        return {"error": str(e)}


# ====================================================================
# USAGE EXAMPLE
# ====================================================================

"""
STEP 1: Run database migration (create table)

-- Run in PostgreSQL:
CREATE TABLE IF NOT EXISTS query_classification_logs (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER,
    query TEXT NOT NULL,
    classified_as VARCHAR(50) NOT NULL,
    search_results_count INTEGER,
    search_took_ms INTEGER,
    timestamp TIMESTAMP DEFAULT NOW(),
    user_clicked_result INTEGER,
    user_satisfied BOOLEAN
);

CREATE INDEX idx_query_logs_project ON query_classification_logs(project_id);
CREATE INDEX idx_query_logs_timestamp ON query_classification_logs(timestamp);


STEP 2: Use in file_indexer.py (Week 2)

from .query_classifier_with_logging import classify_and_log

async def search_files(project_id, query, limit, db):
    # Classify query (+ log in background)
    query_type = classify_and_log(
        query=query,
        project_id=project_id,
        db=db
    )
    
    # Route to appropriate search
    if query_type == QueryType.FILENAME:
        return await search_by_filename(...)
    elif query_type == QueryType.SYMBOL:
        return await search_by_symbol(...)
    # etc.


STEP 3: After 2-3 weeks of dogfooding

from .query_classifier_with_logging import get_classification_stats

stats = get_classification_stats(db)
print(stats)
# {
#   "total_queries": 156,
#   "by_type": {"SYMBOL": 45, "FILENAME": 38, "SEMANTIC": 73},
#   "ready_for_ml": True  ← If True, can train model!
# }


STEP 4: Export data for ML training (Phase 3)

from .query_classifier_with_logging import export_training_data

data = export_training_data(db, min_samples=100)
# Creates /tmp/query_training_data.json

# Then train sklearn model:
# from sklearn.feature_extraction.text import TfidfVectorizer
# from sklearn.naive_bayes import MultinomialNB
# ... (ML training code)
"""