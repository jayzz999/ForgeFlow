"""Continuous Improvement — Feedback loop and learning system for ForgeFlow.

Tracks workflow outcomes, user feedback, and patterns to improve future generations:
- Records success/failure rates per service and pattern
- Stores user feedback (approve/reject/modify) with context
- Provides pattern insights to the code generator for better results
- Learns which API patterns work best for different use cases
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Optional

logger = logging.getLogger("forgeflow.feedback")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "forgeflow.db")


def _get_db():
    """Get database connection with feedback tables."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflow_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            feedback_type TEXT NOT NULL,
            rating INTEGER DEFAULT 0,
            comment TEXT,
            user_request TEXT,
            services TEXT,
            debug_attempts INTEGER DEFAULT 0,
            execution_success INTEGER DEFAULT 0,
            test_results TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pattern_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service TEXT NOT NULL,
            pattern_type TEXT NOT NULL,
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            avg_debug_attempts REAL DEFAULT 0,
            last_error TEXT,
            last_success_code TEXT,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(service, pattern_type)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS improvement_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            improvement_type TEXT NOT NULL,
            description TEXT NOT NULL,
            data TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def record_feedback(
    workflow_id: str,
    feedback_type: str,
    rating: int = 0,
    comment: str = "",
    user_request: str = "",
    services: list[str] | None = None,
    debug_attempts: int = 0,
    execution_success: bool = False,
    test_results: dict | None = None,
) -> dict:
    """Record user/system feedback for a workflow.

    Args:
        workflow_id: The workflow identifier
        feedback_type: 'approve', 'reject', 'modify', 'auto_success', 'auto_failure'
        rating: 1-5 star rating (0 = not rated)
        comment: Optional user comment
        user_request: Original user request
        services: List of services used
        debug_attempts: Number of self-debug attempts
        execution_success: Whether execution succeeded
        test_results: Test execution results

    Returns:
        Dict with feedback_id and status
    """
    try:
        db = _get_db()
        cursor = db.execute("""
            INSERT INTO workflow_feedback
            (workflow_id, feedback_type, rating, comment, user_request, services,
             debug_attempts, execution_success, test_results)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            workflow_id, feedback_type, rating, comment, user_request,
            ",".join(services or []), debug_attempts,
            1 if execution_success else 0,
            json.dumps(test_results) if test_results else None,
        ))
        db.commit()
        feedback_id = cursor.lastrowid
        db.close()

        logger.info(f"[Feedback] Recorded {feedback_type} for workflow {workflow_id} (id={feedback_id})")
        return {"feedback_id": feedback_id, "status": "recorded"}

    except Exception as e:
        logger.error(f"[Feedback] Failed to record: {e}")
        return {"feedback_id": None, "status": "error", "error": str(e)}


def update_pattern_stats(
    service: str,
    pattern_type: str,
    success: bool,
    debug_attempts: int = 0,
    error_msg: str = "",
    success_code_snippet: str = "",
):
    """Update success/failure stats for a service pattern.

    Args:
        service: Service name (e.g., 'Slack', 'Gmail')
        pattern_type: Pattern (e.g., 'post_message', 'create_issue', 'send_email')
        success: Whether the pattern execution succeeded
        debug_attempts: Number of debug attempts needed
        error_msg: Error message if failed
        success_code_snippet: Code snippet if succeeded (for learning)
    """
    try:
        db = _get_db()

        # Upsert pattern stats
        existing = db.execute(
            "SELECT * FROM pattern_stats WHERE service = ? AND pattern_type = ?",
            (service, pattern_type)
        ).fetchone()

        if existing:
            if success:
                new_success = existing["success_count"] + 1
                total = new_success + existing["failure_count"]
                new_avg = ((existing["avg_debug_attempts"] * (total - 1)) + debug_attempts) / total
                db.execute("""
                    UPDATE pattern_stats
                    SET success_count = ?, avg_debug_attempts = ?,
                        last_success_code = ?, updated_at = datetime('now')
                    WHERE service = ? AND pattern_type = ?
                """, (new_success, new_avg,
                      success_code_snippet[:2000] if success_code_snippet else existing["last_success_code"],
                      service, pattern_type))
            else:
                db.execute("""
                    UPDATE pattern_stats
                    SET failure_count = failure_count + 1,
                        last_error = ?, updated_at = datetime('now')
                    WHERE service = ? AND pattern_type = ?
                """, (error_msg[:500], service, pattern_type))
        else:
            db.execute("""
                INSERT INTO pattern_stats
                (service, pattern_type, success_count, failure_count, avg_debug_attempts,
                 last_error, last_success_code)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                service, pattern_type,
                1 if success else 0,
                0 if success else 1,
                float(debug_attempts),
                error_msg[:500] if not success else None,
                success_code_snippet[:2000] if success else None,
            ))

        db.commit()
        db.close()

    except Exception as e:
        logger.error(f"[Feedback] Failed to update pattern stats: {e}")


def get_pattern_insights(services: list[str] | None = None) -> dict:
    """Get insights from past workflow patterns for the code generator.

    Args:
        services: Optional filter by services

    Returns:
        Dict with:
        - service_stats: success/failure rates per service
        - best_patterns: top working patterns with code snippets
        - common_errors: frequently encountered errors
        - recommendations: actionable suggestions
    """
    try:
        db = _get_db()

        # Service stats
        if services:
            placeholders = ",".join("?" * len(services))
            rows = db.execute(
                f"SELECT * FROM pattern_stats WHERE service IN ({placeholders}) ORDER BY success_count DESC",
                services
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM pattern_stats ORDER BY success_count DESC LIMIT 20"
            ).fetchall()

        service_stats = {}
        best_patterns = []
        common_errors = []

        for row in rows:
            row_dict = dict(row)
            service = row_dict["service"]
            total = row_dict["success_count"] + row_dict["failure_count"]
            success_rate = row_dict["success_count"] / total if total > 0 else 0

            if service not in service_stats:
                service_stats[service] = {
                    "total_patterns": 0,
                    "total_success": 0,
                    "total_failure": 0,
                    "avg_success_rate": 0,
                }

            service_stats[service]["total_patterns"] += 1
            service_stats[service]["total_success"] += row_dict["success_count"]
            service_stats[service]["total_failure"] += row_dict["failure_count"]

            if success_rate >= 0.7 and row_dict.get("last_success_code"):
                best_patterns.append({
                    "service": service,
                    "pattern": row_dict["pattern_type"],
                    "success_rate": round(success_rate, 2),
                    "code_hint": row_dict["last_success_code"][:500],
                })

            if row_dict.get("last_error") and row_dict["failure_count"] > 0:
                common_errors.append({
                    "service": service,
                    "pattern": row_dict["pattern_type"],
                    "error": row_dict["last_error"],
                    "failure_count": row_dict["failure_count"],
                })

        # Calculate avg success rates
        for service in service_stats:
            total = service_stats[service]["total_success"] + service_stats[service]["total_failure"]
            if total > 0:
                service_stats[service]["avg_success_rate"] = round(
                    service_stats[service]["total_success"] / total, 2
                )

        # Generate recommendations
        recommendations = []
        for error in sorted(common_errors, key=lambda x: x["failure_count"], reverse=True)[:3]:
            recommendations.append(
                f"⚠️ {error['service']}/{error['pattern']} has failed {error['failure_count']} time(s). "
                f"Common error: {error['error'][:100]}"
            )

        for pattern in best_patterns[:3]:
            recommendations.append(
                f"✅ {pattern['service']}/{pattern['pattern']} works well ({pattern['success_rate']*100:.0f}% success rate)"
            )

        db.close()

        return {
            "service_stats": service_stats,
            "best_patterns": best_patterns[:5],
            "common_errors": common_errors[:5],
            "recommendations": recommendations,
        }

    except Exception as e:
        logger.error(f"[Feedback] Failed to get insights: {e}")
        return {
            "service_stats": {},
            "best_patterns": [],
            "common_errors": [],
            "recommendations": [],
        }


def get_feedback_summary(limit: int = 10) -> dict:
    """Get recent feedback summary for the dashboard.

    Returns:
        Dict with: recent_feedback, stats, trends
    """
    try:
        db = _get_db()

        # Recent feedback
        recent = db.execute("""
            SELECT workflow_id, feedback_type, rating, comment,
                   services, debug_attempts, execution_success, created_at
            FROM workflow_feedback
            ORDER BY created_at DESC LIMIT ?
        """, (limit,)).fetchall()

        # Overall stats
        stats_row = db.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN feedback_type = 'approve' THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN feedback_type = 'reject' THEN 1 ELSE 0 END) as rejected,
                SUM(CASE WHEN feedback_type = 'modify' THEN 1 ELSE 0 END) as modified,
                SUM(CASE WHEN execution_success = 1 THEN 1 ELSE 0 END) as exec_success,
                AVG(CASE WHEN rating > 0 THEN rating ELSE NULL END) as avg_rating,
                AVG(debug_attempts) as avg_debug_attempts
            FROM workflow_feedback
        """).fetchone()

        db.close()

        return {
            "recent_feedback": [dict(r) for r in recent],
            "stats": dict(stats_row) if stats_row else {},
        }

    except Exception as e:
        logger.error(f"[Feedback] Failed to get summary: {e}")
        return {"recent_feedback": [], "stats": {}}


def log_improvement(improvement_type: str, description: str, data: dict | None = None):
    """Log an improvement event for tracking the system's learning.

    Args:
        improvement_type: 'pattern_learned', 'error_fixed', 'prompt_updated', 'api_indexed'
        description: What improved
        data: Optional additional data
    """
    try:
        db = _get_db()
        db.execute("""
            INSERT INTO improvement_log (improvement_type, description, data)
            VALUES (?, ?, ?)
        """, (improvement_type, description, json.dumps(data) if data else None))
        db.commit()
        db.close()
        logger.info(f"[Feedback] Improvement logged: {improvement_type} — {description}")
    except Exception as e:
        logger.error(f"[Feedback] Failed to log improvement: {e}")
