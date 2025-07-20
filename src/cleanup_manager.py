import os
import time
import logging
import shutil
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone
from pathlib import Path
import redis
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import json
from config.settings import Config

logger = logging.getLogger(__name__)

class CleanupManager:
    """Manages automated cleanup of temporary files, expired sessions, and data retention"""
    
    def __init__(self, redis_connection: redis.Redis, config, session_manager=None):
        """
        Initialize cleanup manager
        
        Args:
            redis_connection: Redis connection instance
            config: Application configuration
            session_manager: Optional session manager instance
        """
        self.redis = redis_connection
        self.config = config
        self.session_manager = session_manager
        
        # Configuration values - use class properties for most, instance for properties
        self.data_retention_hours = Config.DATA_RETENTION_HOURS
        self.cleanup_interval_minutes = Config.CLEANUP_INTERVAL_MINUTES
        self.max_total_storage_gb = Config.MAX_TOTAL_STORAGE_GB
        self.upload_dir = Config.TEMP_UPLOAD_DIR
        
        # Cleanup statistics
        self.cleanup_stats = {
            'last_cleanup': None,
            'total_cleanups': 0,
            'files_deleted': 0,
            'sessions_cleaned': 0,
            'storage_freed_mb': 0.0,
            'errors': 0
        }
        
        # Initialize scheduler
        self.scheduler = None
        self.is_running = False
        
        logger.info(f"Cleanup Manager initialized - retention: {self.data_retention_hours}h, interval: {self.cleanup_interval_minutes}m")
    
    def start_scheduled_cleanup(self, background: bool = True):
        """
        Start scheduled automatic cleanup
        
        Args:
            background: If True, run as background scheduler, else blocking
        """
        if self.is_running:
            logger.warning("Cleanup scheduler is already running")
            return
        
        # Choose scheduler type
        if background:
            self.scheduler = BackgroundScheduler()
        else:
            self.scheduler = BlockingScheduler()
        
        # Schedule regular cleanup
        cleanup_trigger = IntervalTrigger(minutes=self.cleanup_interval_minutes)
        self.scheduler.add_job(
            func=self.run_full_cleanup,
            trigger=cleanup_trigger,
            id='regular_cleanup',
            name='Regular Cleanup',
            replace_existing=True
        )
        
        # Schedule daily deep cleanup at 2 AM
        deep_cleanup_trigger = CronTrigger(hour=2, minute=0)
        self.scheduler.add_job(
            func=self.run_deep_cleanup,
            trigger=deep_cleanup_trigger,
            id='deep_cleanup',
            name='Daily Deep Cleanup',
            replace_existing=True
        )
        
        # Schedule storage monitoring every 30 minutes
        storage_trigger = IntervalTrigger(minutes=30)
        self.scheduler.add_job(
            func=self.monitor_storage_usage,
            trigger=storage_trigger,
            id='storage_monitor',
            name='Storage Monitor',
            replace_existing=True
        )
        
        try:
            self.scheduler.start()
            self.is_running = True
            logger.info(f"Cleanup scheduler started ({'background' if background else 'blocking'} mode)")
            
            if not background:
                # Blocking mode - keep running
                logger.info("Cleanup manager running in blocking mode. Press Ctrl+C to stop.")
                
        except Exception as e:
            logger.error(f"Failed to start cleanup scheduler: {e}")
            raise
    
    def stop_scheduled_cleanup(self):
        """Stop scheduled cleanup"""
        if self.scheduler and self.is_running:
            self.scheduler.shutdown(wait=True)
            self.is_running = False
            logger.info("Cleanup scheduler stopped")
        else:
            logger.warning("Cleanup scheduler is not running")
    
    def run_full_cleanup(self) -> Dict[str, Any]:
        """
        Run complete cleanup process
        
        Returns:
            Dictionary with cleanup results
        """
        logger.info("Starting full cleanup process")
        start_time = time.time()
        
        results = {
            'start_time': datetime.now(timezone.utc).isoformat(),
            'expired_sessions_cleaned': 0,
            'files_deleted': 0,
            'directories_removed': 0,
            'storage_freed_mb': 0.0,
            'redis_keys_cleaned': 0,
            'errors': []
        }
        
        try:
            # Step 1: Clean expired sessions
            if self.session_manager:
                sessions_cleaned = self.session_manager.cleanup_expired_sessions()
                results['expired_sessions_cleaned'] = sessions_cleaned
                logger.info(f"Cleaned {sessions_cleaned} expired sessions")
            
            # Step 2: Clean old files
            file_results = self.cleanup_old_files()
            results['files_deleted'] = file_results['files_deleted']
            results['directories_removed'] = file_results['directories_removed']
            results['storage_freed_mb'] += file_results['storage_freed_mb']
            
            # Step 3: Clean Redis keys
            redis_cleaned = self.cleanup_redis_keys()
            results['redis_keys_cleaned'] = redis_cleaned
            
            # Step 4: Clean empty directories
            empty_dirs = self.cleanup_empty_directories()
            results['directories_removed'] += empty_dirs
            
            # Update statistics
            self.cleanup_stats['last_cleanup'] = datetime.now(timezone.utc).isoformat()
            self.cleanup_stats['total_cleanups'] += 1
            self.cleanup_stats['files_deleted'] += results['files_deleted']
            self.cleanup_stats['sessions_cleaned'] += results['expired_sessions_cleaned']
            self.cleanup_stats['storage_freed_mb'] += results['storage_freed_mb']
            
            processing_time = time.time() - start_time
            results['processing_time'] = round(processing_time, 2)
            results['end_time'] = datetime.now(timezone.utc).isoformat()
            
            logger.info(f"Full cleanup completed in {processing_time:.2f}s - freed {results['storage_freed_mb']:.1f}MB")
            
        except Exception as e:
            error_msg = f"Error during full cleanup: {e}"
            logger.error(error_msg)
            results['errors'].append(error_msg)
            self.cleanup_stats['errors'] += 1
        
        return results
    
    def run_deep_cleanup(self) -> Dict[str, Any]:
        """
        Run deep cleanup with additional maintenance tasks
        
        Returns:
            Dictionary with cleanup results
        """
        logger.info("Starting deep cleanup process")
        
        # Run regular cleanup first
        results = self.run_full_cleanup()
        
        try:
            # Additional deep cleanup tasks
            
            # Clean up orphaned job data
            orphaned_jobs = self.cleanup_orphaned_jobs()
            results['orphaned_jobs_cleaned'] = orphaned_jobs
            
            # Verify file integrity
            integrity_results = self.verify_file_integrity()
            results['integrity_check'] = integrity_results
            
            # Compress old logs (if any)
            log_results = self.cleanup_old_logs()
            results['logs_cleaned'] = log_results
            
            # Redis memory optimization
            redis_optimized = self.optimize_redis_memory()
            results['redis_optimized'] = redis_optimized
            
            logger.info(f"Deep cleanup completed - additional {orphaned_jobs} orphaned jobs cleaned")
            
        except Exception as e:
            error_msg = f"Error during deep cleanup: {e}"
            logger.error(error_msg)
            results['errors'].append(error_msg)
        
        return results
    
    def cleanup_old_files(self) -> Dict[str, Any]:
        """
        Clean up files older than retention period
        
        Returns:
            Dictionary with cleanup results
        """
        logger.debug("Starting old file cleanup")
        
        results = {
            'files_deleted': 0,
            'directories_removed': 0,
            'storage_freed_mb': 0.0
        }
        
        if not os.path.exists(self.upload_dir):
            return results
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=self.data_retention_hours)
        cutoff_timestamp = cutoff_time.timestamp()
        
        try:
            for root, dirs, files in os.walk(self.upload_dir):
                # Clean old files
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        file_stat = os.stat(file_path)
                        if file_stat.st_mtime < cutoff_timestamp:
                            file_size = file_stat.st_size
                            os.remove(file_path)
                            results['files_deleted'] += 1
                            results['storage_freed_mb'] += file_size / (1024 * 1024)
                            logger.debug(f"Deleted old file: {file_path}")
                    except (OSError, IOError) as e:
                        logger.warning(f"Could not delete file {file_path}: {e}")
                
                # Mark empty directories for removal
                if root != self.upload_dir:  # Don't remove the main upload directory
                    try:
                        if not os.listdir(root):  # Directory is empty
                            os.rmdir(root)
                            results['directories_removed'] += 1
                            logger.debug(f"Removed empty directory: {root}")
                    except OSError:
                        pass  # Directory not empty or other issue
        
        except Exception as e:
            logger.error(f"Error during file cleanup: {e}")
        
        logger.debug(f"File cleanup completed: {results['files_deleted']} files, {results['storage_freed_mb']:.1f}MB freed")
        return results
    
    def cleanup_redis_keys(self) -> int:
        """
        Clean up expired Redis keys
        
        Returns:
            Number of keys cleaned
        """
        logger.debug("Starting Redis key cleanup")
        
        cleaned_count = 0
        
        try:
            # Get all session-related keys
            patterns = [
                'session_data:*',
                'session_files:*',
                'job:*:*',
                'job_progress:*:*',
                'rate_change:*:*'
            ]
            
            for pattern in patterns:
                keys = self.redis.keys(pattern)
                for key in keys:
                    try:
                        # Check if key has TTL
                        ttl = self.redis.ttl(key)
                        if ttl == -1:  # Key has no expiration
                            # Set TTL based on data retention
                            self.redis.expire(key, self.data_retention_hours * 3600)
                        elif ttl == -2:  # Key doesn't exist
                            cleaned_count += 1
                    except redis.RedisError:
                        pass
            
        except Exception as e:
            logger.error(f"Error during Redis cleanup: {e}")
        
        logger.debug(f"Redis cleanup completed: {cleaned_count} keys cleaned")
        return cleaned_count
    
    def cleanup_empty_directories(self) -> int:
        """
        Remove empty directories in upload folder
        
        Returns:
            Number of directories removed
        """
        logger.debug("Starting empty directory cleanup")
        
        removed_count = 0
        
        if not os.path.exists(self.upload_dir):
            return removed_count
        
        try:
            # Walk bottom-up to remove nested empty directories
            for root, dirs, files in os.walk(self.upload_dir, topdown=False):
                if root != self.upload_dir:  # Don't remove main upload directory
                    try:
                        if not os.listdir(root):  # Directory is empty
                            os.rmdir(root)
                            removed_count += 1
                            logger.debug(f"Removed empty directory: {root}")
                    except OSError:
                        pass  # Directory not empty or permission issue
        
        except Exception as e:
            logger.error(f"Error during directory cleanup: {e}")
        
        logger.debug(f"Directory cleanup completed: {removed_count} directories removed")
        return removed_count
    
    def cleanup_orphaned_jobs(self) -> int:
        """
        Clean up orphaned job data (jobs without sessions)
        
        Returns:
            Number of orphaned jobs cleaned
        """
        logger.debug("Starting orphaned job cleanup")
        
        cleaned_count = 0
        
        try:
            # Get all job keys
            job_keys = self.redis.keys('job:*:*')
            
            for job_key in job_keys:
                try:
                    # Extract session ID from job key
                    key_parts = job_key.decode('utf-8').split(':')
                    if len(key_parts) >= 3:
                        session_id = key_parts[1]
                        
                        # Check if session exists
                        session_key = f"session_data:{session_id}"
                        if not self.redis.exists(session_key):
                            # Session doesn't exist, remove orphaned job
                            self.redis.delete(job_key)
                            
                            # Also clean related keys
                            progress_key = f"job_progress:{session_id}:{key_parts[2]}"
                            rate_key = f"rate_change:{session_id}:{key_parts[2]}"
                            self.redis.delete(progress_key, rate_key)
                            
                            cleaned_count += 1
                            logger.debug(f"Cleaned orphaned job: {job_key}")
                
                except Exception as e:
                    logger.warning(f"Error checking job {job_key}: {e}")
        
        except Exception as e:
            logger.error(f"Error during orphaned job cleanup: {e}")
        
        logger.debug(f"Orphaned job cleanup completed: {cleaned_count} jobs cleaned")
        return cleaned_count
    
    def verify_file_integrity(self) -> Dict[str, Any]:
        """
        Verify file system integrity and remove corrupted files
        
        Returns:
            Dictionary with integrity check results
        """
        logger.debug("Starting file integrity verification")
        
        results = {
            'files_checked': 0,
            'corrupted_files': 0,
            'inaccessible_files': 0,
            'total_size_mb': 0.0
        }
        
        if not os.path.exists(self.upload_dir):
            return results
        
        try:
            for root, dirs, files in os.walk(self.upload_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    results['files_checked'] += 1
                    
                    try:
                        # Check if file is accessible and get size
                        file_stat = os.stat(file_path)
                        file_size = file_stat.st_size
                        results['total_size_mb'] += file_size / (1024 * 1024)
                        
                        # Try to read first few bytes to verify accessibility
                        with open(file_path, 'rb') as f:
                            f.read(1024)  # Read first 1KB
                    
                    except (OSError, IOError) as e:
                        logger.warning(f"Inaccessible file detected: {file_path} - {e}")
                        results['inaccessible_files'] += 1
                        
                        # Try to remove inaccessible file
                        try:
                            os.remove(file_path)
                            logger.info(f"Removed inaccessible file: {file_path}")
                        except:
                            pass
        
        except Exception as e:
            logger.error(f"Error during integrity verification: {e}")
        
        results['total_size_mb'] = round(results['total_size_mb'], 2)
        logger.debug(f"Integrity check completed: {results['files_checked']} files checked, {results['total_size_mb']}MB total")
        return results
    
    def cleanup_old_logs(self) -> int:
        """
        Clean up old log files
        
        Returns:
            Number of log files cleaned
        """
        logger.debug("Starting log cleanup")
        
        cleaned_count = 0
        log_dirs = ['logs', 'log']  # Common log directories
        
        for log_dir in log_dirs:
            if os.path.exists(log_dir):
                try:
                    cutoff_time = datetime.now(timezone.utc) - timedelta(days=7)  # Keep logs for 7 days
                    cutoff_timestamp = cutoff_time.timestamp()
                    
                    for file in os.listdir(log_dir):
                        file_path = os.path.join(log_dir, file)
                        if os.path.isfile(file_path) and file.endswith('.log'):
                            try:
                                if os.path.getmtime(file_path) < cutoff_timestamp:
                                    os.remove(file_path)
                                    cleaned_count += 1
                                    logger.debug(f"Removed old log: {file_path}")
                            except OSError:
                                pass
                
                except Exception as e:
                    logger.warning(f"Error cleaning logs in {log_dir}: {e}")
        
        logger.debug(f"Log cleanup completed: {cleaned_count} log files cleaned")
        return cleaned_count
    
    def optimize_redis_memory(self) -> bool:
        """
        Optimize Redis memory usage
        
        Returns:
            True if optimization was successful
        """
        logger.debug("Starting Redis memory optimization")
        
        try:
            # Get Redis info before optimization
            info_before = self.redis.info('memory')
            used_memory_before = info_before.get('used_memory', 0)
            
            # Run Redis BGSAVE to create snapshot
            self.redis.bgsave()
            
            # Wait a moment and get info after
            time.sleep(1)
            info_after = self.redis.info('memory')
            used_memory_after = info_after.get('used_memory', 0)
            
            memory_saved = used_memory_before - used_memory_after
            logger.debug(f"Redis optimization completed: {memory_saved} bytes saved")
            
            return True
        
        except Exception as e:
            logger.error(f"Error during Redis optimization: {e}")
            return False
    
    def monitor_storage_usage(self) -> Dict[str, Any]:
        """
        Monitor overall storage usage and warn if approaching limits
        
        Returns:
            Dictionary with storage monitoring results
        """
        logger.debug("Starting storage usage monitoring")
        
        monitoring_results = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'total_storage_gb': 0.0,
            'storage_limit_gb': self.max_total_storage_gb,
            'usage_percentage': 0.0,
            'warning_threshold': 80.0,
            'critical_threshold': 95.0,
            'status': 'ok'
        }
        
        try:
            if os.path.exists(self.upload_dir):
                total_size = 0
                for root, dirs, files in os.walk(self.upload_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        try:
                            total_size += os.path.getsize(file_path)
                        except OSError:
                            pass
                
                total_size_gb = total_size / (1024 ** 3)
                usage_percentage = (total_size_gb / self.max_total_storage_gb) * 100
                
                monitoring_results['total_storage_gb'] = round(total_size_gb, 2)
                monitoring_results['usage_percentage'] = round(usage_percentage, 1)
                
                # Determine status
                if usage_percentage >= monitoring_results['critical_threshold']:
                    monitoring_results['status'] = 'critical'
                    logger.warning(f"CRITICAL: Storage usage at {usage_percentage:.1f}% of {self.max_total_storage_gb}GB limit")
                elif usage_percentage >= monitoring_results['warning_threshold']:
                    monitoring_results['status'] = 'warning'
                    logger.warning(f"WARNING: Storage usage at {usage_percentage:.1f}% of {self.max_total_storage_gb}GB limit")
                else:
                    monitoring_results['status'] = 'ok'
                    logger.debug(f"Storage usage: {usage_percentage:.1f}% of {self.max_total_storage_gb}GB limit")
        
        except Exception as e:
            logger.error(f"Error during storage monitoring: {e}")
            monitoring_results['status'] = 'error'
            monitoring_results['error'] = str(e)
        
        return monitoring_results
    
    def get_cleanup_stats(self) -> Dict[str, Any]:
        """Get cleanup statistics"""
        return self.cleanup_stats.copy()
    
    def force_cleanup_session(self, session_id: str) -> bool:
        """
        Force cleanup of a specific session
        
        Args:
            session_id: Session ID to clean up
            
        Returns:
            True if cleanup was successful
        """
        logger.info(f"Force cleaning session: {session_id}")
        
        if self.session_manager:
            return self.session_manager.delete_session(session_id)
        
        return False

def main():
    """Main entry point for cleanup manager"""
    import argparse
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    from src.session_manager import SessionManager
    
    parser = argparse.ArgumentParser(description='CSV Merger Cleanup Manager')
    parser.add_argument('--mode', choices=['once', 'scheduled'], default='once', 
                       help='Run cleanup once or start scheduled cleanup')
    parser.add_argument('--deep', action='store_true', help='Run deep cleanup')
    parser.add_argument('--redis-url', help='Redis connection URL')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info(f"Starting CSV Merger Cleanup Manager - Mode: {args.mode}")
    
    try:
        # Connect to Redis
        redis_connection = redis.from_url(args.redis_url or Config.REDIS_URL)
        redis_connection.ping()
        
        # Initialize managers
        session_manager = SessionManager(redis_connection, Config)
        cleanup_manager = CleanupManager(redis_connection, Config, session_manager)
        
        if args.mode == 'once':
            # Run cleanup once
            if args.deep:
                results = cleanup_manager.run_deep_cleanup()
                logger.info("Deep cleanup completed")
            else:
                results = cleanup_manager.run_full_cleanup()
                logger.info("Regular cleanup completed")
            
            # Print results
            print(json.dumps(results, indent=2))
        
        else:
            # Start scheduled cleanup
            cleanup_manager.start_scheduled_cleanup(background=False)
    
    except KeyboardInterrupt:
        logger.info("Cleanup manager interrupted by user")
    except Exception as e:
        logger.error(f"Cleanup manager failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main() 