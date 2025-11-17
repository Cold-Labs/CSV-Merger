"""
Log Collector - Structured logging to Redis for queryable logs
Stores logs for 7 days with ability to query by date range, job ID, level, etc.
"""

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from redis import Redis
import os


class LogCollector:
    """Collects and stores structured logs in Redis for easy querying"""
    
    # Log retention in seconds (7 days)
    LOG_RETENTION_SECONDS = 7 * 24 * 60 * 60
    
    def __init__(self, redis_client: Optional[Redis] = None):
        """Initialize log collector with Redis connection"""
        if redis_client is None:
            redis_url = os.getenv("REDIS_URL")
            if redis_url:
                self.redis = Redis.from_url(redis_url, decode_responses=True)
            else:
                self.redis = Redis(
                    host=os.getenv("REDIS_HOST", "localhost"),
                    port=int(os.getenv("REDIS_PORT", 6379)),
                    db=int(os.getenv("REDIS_DB", 0)),
                    decode_responses=True,
                )
        else:
            self.redis = redis_client
    
    def log(
        self,
        level: str,
        message: str,
        job_id: Optional[str] = None,
        error_type: Optional[str] = None,
        record_number: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Log a structured event to Redis
        
        Args:
            level: Log level (INFO, WARNING, ERROR, CRITICAL)
            message: Log message
            job_id: Associated job ID
            error_type: Type of error (e.g., 'HTTP_403', 'TIMEOUT', 'VALIDATION')
            record_number: Record number if applicable
            metadata: Additional metadata
        """
        timestamp = datetime.now(timezone.utc)
        
        log_entry = {
            "timestamp": timestamp.isoformat(),
            "timestamp_unix": int(timestamp.timestamp()),
            "level": level.upper(),
            "message": message,
            "job_id": job_id,
            "error_type": error_type,
            "record_number": record_number,
            "metadata": metadata or {},
        }
        
        # Generate unique log ID
        log_id = f"log:{int(timestamp.timestamp() * 1000000)}"
        
        # Store log entry
        self.redis.setex(
            log_id,
            self.LOG_RETENTION_SECONDS,
            json.dumps(log_entry)
        )
        
        # Add to sorted sets for queryability
        score = timestamp.timestamp()
        
        # Global log index (all logs)
        self.redis.zadd("logs:all", {log_id: score})
        
        # Index by level
        self.redis.zadd(f"logs:level:{level.upper()}", {log_id: score})
        
        # Index by job_id
        if job_id:
            self.redis.zadd(f"logs:job:{job_id}", {log_id: score})
        
        # Index by error_type
        if error_type:
            self.redis.zadd(f"logs:error:{error_type}", {log_id: score})
        
        # Set expiry on sorted sets (cleanup)
        self.redis.expire("logs:all", self.LOG_RETENTION_SECONDS)
        self.redis.expire(f"logs:level:{level.upper()}", self.LOG_RETENTION_SECONDS)
        if job_id:
            self.redis.expire(f"logs:job:{job_id}", self.LOG_RETENTION_SECONDS)
        if error_type:
            self.redis.expire(f"logs:error:{error_type}", self.LOG_RETENTION_SECONDS)
    
    def query_logs(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        job_id: Optional[str] = None,
        level: Optional[str] = None,
        error_type: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        Query logs with filters
        
        Args:
            start_time: Start of time range (default: 7 days ago)
            end_time: End of time range (default: now)
            job_id: Filter by job ID
            level: Filter by log level
            error_type: Filter by error type
            limit: Maximum number of logs to return
            
        Returns:
            List of log entries
        """
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        if start_time is None:
            start_time = end_time - timedelta(days=7)
        
        min_score = start_time.timestamp()
        max_score = end_time.timestamp()
        
        # Determine which index to query
        if job_id:
            index_key = f"logs:job:{job_id}"
        elif error_type:
            index_key = f"logs:error:{error_type}"
        elif level:
            index_key = f"logs:level:{level.upper()}"
        else:
            index_key = "logs:all"
        
        # Get log IDs in time range (newest first)
        log_ids = self.redis.zrevrangebyscore(
            index_key,
            max_score,
            min_score,
            start=0,
            num=limit
        )
        
        # Fetch log entries
        logs = []
        for log_id in log_ids:
            log_data = self.redis.get(log_id)
            if log_data:
                try:
                    logs.append(json.loads(log_data))
                except json.JSONDecodeError:
                    continue
        
        return logs
    
    def get_error_summary(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        job_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        Get summary of errors by type
        
        Args:
            start_time: Start of time range
            end_time: End of time range
            job_id: Filter by job ID
            
        Returns:
            Dictionary mapping error types to counts
        """
        logs = self.query_logs(
            start_time=start_time,
            end_time=end_time,
            job_id=job_id,
            level="ERROR",
            limit=10000,
        )
        
        error_counts = {}
        for log in logs:
            error_type = log.get("error_type", "UNKNOWN")
            error_counts[error_type] = error_counts.get(error_type, 0) + 1
        
        return error_counts
    
    def cleanup_old_logs(self):
        """
        Cleanup logs older than retention period
        Note: Redis automatically expires keys, but this cleans up sorted set entries
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=self.LOG_RETENTION_SECONDS)
        cutoff_score = cutoff_time.timestamp()
        
        # Get all log index keys
        for key in self.redis.scan_iter("logs:*"):
            # Remove old entries from sorted sets
            self.redis.zremrangebyscore(key, "-inf", cutoff_score)


# Global instance
_log_collector = None


def get_log_collector() -> LogCollector:
    """Get global log collector instance"""
    global _log_collector
    if _log_collector is None:
        _log_collector = LogCollector()
    return _log_collector

