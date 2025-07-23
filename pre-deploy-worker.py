#!/usr/bin/env python3
"""
Pre-deploy script for CSV Merger Worker
Clears Redis queue to prevent serialization issues
"""

import sys
import os
import redis
import logging

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """Clean Redis queue before worker deployment"""
    try:
        logger.info("=== CSV Merger Worker Pre-Deploy Script ===")
        
        # Get Redis URL from environment
        redis_url = os.getenv('REDIS_URL')
        if not redis_url:
            logger.warning("No REDIS_URL found, skipping queue cleanup")
            return 0
        
        logger.info(f"Connecting to Redis: {redis_url[:20]}...")
        
        # Connect to Redis
        redis_client = redis.from_url(redis_url, decode_responses=True)
        
        # Test connection
        redis_client.ping()
        logger.info("✅ Redis connection successful")
        
        # Clear the CSV processing queue
        queue_name = 'csv_processing'
        
        # Delete queue-related keys
        keys_to_clear = [
            f"rq:queue:{queue_name}",
            f"rq:queue:{queue_name}:started",
            f"rq:queue:{queue_name}:finished", 
            f"rq:queue:{queue_name}:failed",
            f"rq:queue:{queue_name}:deferred",
            f"rq:queue:{queue_name}:scheduled"
        ]
        
        cleared_count = 0
        for key in keys_to_clear:
            try:
                if redis_client.exists(key):
                    redis_client.delete(key)
                    cleared_count += 1
                    logger.info(f"✅ Cleared Redis key: {key}")
            except Exception as e:
                logger.warning(f"Failed to clear key {key}: {e}")
        
        # Clear any job data that might be corrupted
        try:
            # Get all job keys
            job_keys = redis_client.keys("rq:job:*")
            if job_keys:
                redis_client.delete(*job_keys)
                logger.info(f"✅ Cleared {len(job_keys)} job keys")
                cleared_count += len(job_keys)
        except Exception as e:
            logger.warning(f"Failed to clear job keys: {e}")
        
        logger.info(f"✅ Pre-deploy cleanup complete! Cleared {cleared_count} Redis keys")
        return 0
        
    except redis.ConnectionError as e:
        logger.error(f"❌ Redis connection failed: {e}")
        logger.info("Worker will attempt to start anyway...")
        return 0  # Don't fail deployment if Redis is temporarily unavailable
        
    except Exception as e:
        logger.error(f"❌ Pre-deploy script failed: {e}")
        import traceback
        traceback.print_exc()
        return 0  # Don't fail deployment for cleanup issues

if __name__ == "__main__":
    sys.exit(main()) 