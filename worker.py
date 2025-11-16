"""
RQ Worker Script for Railway Deployment
Processes webhook sending jobs from Redis queue in parallel
"""

import os
import sys
from redis import Redis
from rq import Worker, Queue

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))


def get_redis_config():
    """Get Redis configuration from environment variables"""
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        # Railway Redis addon provides REDIS_URL
        return Redis.from_url(redis_url, decode_responses=False)
    else:
        # Fallback to localhost for development
        return Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=int(os.getenv("REDIS_DB", 0)),
            decode_responses=False,
        )


if __name__ == "__main__":
    # Connect to Redis
    redis_conn = get_redis_config()
    
    # Listen to the csv_processing queue
    queue_name = os.getenv("QUEUE_NAME", "csv_processing")
    
    print(f"🚀 Starting RQ Worker for queue: {queue_name}")
    print(f"📡 Redis: {os.getenv('REDIS_URL', 'localhost:6379')}")
    
    # Create queue and worker with direct Redis connection (modern RQ API)
    queue = Queue(queue_name, connection=redis_conn)
    worker = Worker([queue], connection=redis_conn)
    
    print(f"✅ Worker ready - listening for jobs...")
    worker.work(with_scheduler=True)

