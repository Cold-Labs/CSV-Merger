import os
import json
import logging
import uuid
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta, timezone
import redis
from rq import Queue, Worker
from rq.job import Job, JobStatus
from rq.registry import StartedJobRegistry, FinishedJobRegistry
from rq.exceptions import NoSuchJobError
import time

logger = logging.getLogger(__name__)

class JobManager:
    """Manages job queue operations with Redis and RQ integration"""
    
    def __init__(self, redis_connection: redis.Redis, config, socketio=None):
        """
        Initialize job manager with Redis queue
        
        Args:
            redis_connection: Redis connection instance
            config: Application configuration
            socketio: Optional SocketIO instance for real-time updates
        """
        self.redis = redis_connection
        self.config = config
        self.socketio = socketio  # Add SocketIO for real-time updates
        
        # Initialize RQ queue
        self.queue = Queue('csv_processing', connection=redis_connection)
        
        # Configuration
        self.session_prefix = "session:"
        self.job_ttl = 86400  # 24 hours
        self.session_ttl = 172800  # 48 hours
        self.job_timeout = 1800  # 30 minutes job timeout
        
        logger.info("Job Manager initialized with Redis queue")
    
    def set_socketio(self, socketio):
        """Set SocketIO instance for real-time updates"""
        self.socketio = socketio
    
    def _broadcast_to_session(self, session_id: str, event: str, data: Dict[str, Any]):
        """Broadcast event to all clients in a session room"""
        if self.socketio:
            room = f"session_{session_id}"
            self.socketio.emit(event, data, room=room)
    
    def _broadcast_to_job(self, job_id: str, event: str, data: Dict[str, Any]):
        """Broadcast event to all clients following a specific job"""
        if self.socketio:
            room = f"job_{job_id}"
            self.socketio.emit(event, data, room=room)
    
    def _broadcast_progress_update(self, job_id: str, session_id: str, progress_data: Dict[str, Any]):
        """Broadcast job progress update to relevant clients"""
        if self.socketio:
            # Add metadata to progress data
            enhanced_progress = {
                'job_id': job_id,
                'session_id': session_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                **progress_data
            }
            
            # Broadcast to job room and session room
            self._broadcast_to_job(job_id, 'job_progress', enhanced_progress)
            self._broadcast_to_session(session_id, 'job_progress', enhanced_progress)
    
    def _broadcast_status_change(self, job_id: str, session_id: str, old_status: str, new_status: str, additional_data: Optional[Dict] = None):
        """Broadcast job status change to relevant clients"""
        if self.socketio:
            status_data = {
                'job_id': job_id,
                'session_id': session_id,
                'old_status': old_status,
                'new_status': new_status,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            if additional_data:
                status_data.update(additional_data)
            
            # Broadcast to job room and session room
            self._broadcast_to_job(job_id, 'job_status_change', status_data)
            self._broadcast_to_session(session_id, 'job_status_change', status_data)
    
    def enqueue_job(self, job_data: Dict[str, Any]) -> str:
        """
        Add CSV processing job to queue
        
        Args:
            job_data: Dictionary containing job information
                - session_id: User session ID
                - file_paths: List of CSV file paths
                - table_type: 'company' or 'people'
                - webhook_url: Optional webhook URL
                - webhook_rate_limit: Optional rate limit
                
        Returns:
            Job ID string
        """
        session_id = job_data.get('session_id')
        if not session_id:
            raise ValueError("session_id is required")
        
        # Check session limits
        if not self._check_session_limits(session_id):
            raise ValueError("Session has reached maximum concurrent jobs limit")
        
        # Create unique job ID
        job_id = str(uuid.uuid4())
        
        # Prepare job data with metadata
        job_payload = {
            'job_id': job_id,
            'session_id': session_id,
            'file_paths': job_data.get('file_paths', []),
            'table_type': job_data.get('table_type'),
            'webhook_url': job_data.get('webhook_url'),
            'webhook_rate_limit': job_data.get('webhook_rate_limit', 10),
            'processing_mode': job_data.get('processing_mode', 'webhook'),  # 'webhook' or 'download'
            'created_at': datetime.now(timezone.utc).isoformat(),
            'status': 'pending'
        }
        
        try:
            # Enqueue the job with timeout
            rq_job = self.queue.enqueue(
                process_csv_job,  # Function to call
                job_payload,
                job_id=job_id,
                job_timeout=self.job_timeout,
                result_ttl=self.session_ttl,
                failure_ttl=self.session_ttl
            )
            
            # Store job metadata in Redis with session context
            self._store_job_metadata(job_id, session_id, job_payload)
            
            # Add job to session's job list
            self._add_job_to_session(session_id, job_id)
            
            logger.info(f"Job {job_id} enqueued for session {session_id}")
            return job_id
            
        except Exception as e:
            logger.error(f"Failed to enqueue job: {e}")
            raise
    
    def get_job_status(self, job_id: str, session_id: str) -> Dict[str, Any]:
        """
        Retrieve current job status and progress
        
        Args:
            job_id: Job ID to check
            session_id: Session ID for access control
            
        Returns:
            Dictionary with job status and progress information
        """
        # Verify job belongs to session
        if not self._verify_job_access(job_id, session_id):
            raise ValueError("Job not found or access denied")
        
        try:
            # Get RQ job
            rq_job = Job.fetch(job_id, connection=self.redis)
            
            # Get job metadata from Redis
            job_key = f"job:{session_id}:{job_id}"
            job_data = self.redis.get(job_key)
            
            if job_data:
                job_metadata = json.loads(job_data)
            else:
                job_metadata = {}
            
            # Get progress data
            progress_key = f"job_progress:{session_id}:{job_id}"
            progress_data = self.redis.get(progress_key)
            progress = json.loads(progress_data) if progress_data else {}
            
            # Prepare status response
            status_data = {
                'job_id': job_id,
                'session_id': session_id,
                'status': self._map_rq_status(rq_job.get_status()),
                'created_at': job_metadata.get('created_at'),
                'started_at': job_metadata.get('started_at'),
                'completed_at': job_metadata.get('completed_at'),
                'progress': {
                    'percentage': progress.get('percentage', 0),
                    'message': progress.get('message', ''),
                    'stats': progress.get('stats', {}),
                    'current_rate': progress.get('current_rate', 0),
                    'rate_limit': job_metadata.get('webhook_rate_limit', 10)
                },
                'result': None,
                'error': None
            }
            
            # Add result data if job is completed
            if rq_job.is_finished:
                status_data['result'] = rq_job.result
                status_data['completed_at'] = job_metadata.get('completed_at')
                
                # Add download URL if available
                if rq_job.result and isinstance(rq_job.result, dict):
                    if 'export_path' in rq_job.result:
                        status_data['download_available'] = True
                        status_data['download_url'] = f'/api/jobs/{job_id}/download'
            
            # Add error information if job failed
            if rq_job.is_failed:
                status_data['error'] = str(rq_job.exc_info) if rq_job.exc_info else 'Unknown error'
            
            return status_data
            
        except NoSuchJobError:
            # Job not found in RQ, check if it's in our metadata
            job_key = f"job:{session_id}:{job_id}"
            job_data = self.redis.get(job_key)
            
            if job_data:
                job_metadata = json.loads(job_data)
                return {
                    'job_id': job_id,
                    'session_id': session_id,
                    'status': 'expired',
                    'created_at': job_metadata.get('created_at'),
                    'error': 'Job has expired and been cleaned up'
                }
            else:
                raise ValueError("Job not found")
    
    def update_progress(self, job_id: str, session_id: str, progress_data: Dict[str, Any]):
        """
        Update job progress in Redis
        
        Args:
            job_id: Job ID
            session_id: Session ID
            progress_data: Progress information dictionary
        """
        progress_key = f"job_progress:{session_id}:{job_id}"
        
        # Store progress with TTL
        self.redis.setex(
            progress_key,
            self.session_ttl,
            json.dumps(progress_data)
        )
        
        logger.debug(f"Updated progress for job {job_id}: {progress_data.get('message', 'No message')}")
    
    def update_webhook_rate(self, job_id: str, session_id: str, new_rate_limit: int) -> bool:
        """
        Update webhook rate limit for a running job
        
        Args:
            job_id: Job ID
            session_id: Session ID  
            new_rate_limit: New rate limit (requests per second)
            
        Returns:
            True if successfully updated
        """
        # Verify job access
        if not self._verify_job_access(job_id, session_id):
            return False
        
        try:
            # Update job metadata
            job_key = f"job:{session_id}:{job_id}"
            job_data = self.redis.get(job_key)
            
            if job_data:
                job_metadata = json.loads(job_data)
                old_rate = job_metadata.get('webhook_rate_limit', 10)
                job_metadata['webhook_rate_limit'] = new_rate_limit
                
                # Store updated metadata
                self.redis.setex(job_key, self.session_ttl, json.dumps(job_metadata))
                
                # Store rate change signal for worker to pick up
                rate_signal_key = f"rate_change:{session_id}:{job_id}"
                self.redis.setex(rate_signal_key, 300, json.dumps({  # 5 minute TTL
                    'new_rate': new_rate_limit,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }))
                
                logger.info(f"Updated rate limit for job {job_id}: {old_rate} -> {new_rate_limit}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to update rate for job {job_id}: {e}")
            return False
    
    def mark_job_completed(self, job_id: str, session_id: str, results: Dict[str, Any]):
        """
        Mark job as completed with results and download information
        
        Args:
            job_id: Job ID
            session_id: Session ID
            results: Job results dictionary
        """
        job_key = f"job:{session_id}:{job_id}"
        job_data = self.redis.get(job_key)
        
        if job_data:
            job_metadata = json.loads(job_data)
            old_status = job_metadata.get('status', 'unknown')
            
            # Prepare download information if export path exists
            download_info = None
            if results.get('export_path'):
                export_path = results['export_path']
                download_info = {
                    'file_path': export_path,
                    'filename': os.path.basename(export_path),
                    'file_size': os.path.getsize(export_path) if os.path.exists(export_path) else 0,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'stats': {
                        'total_records': results.get('total_records', 0),
                        'duplicates_removed': results.get('duplicates_removed', 0),
                        'sources_merged': results.get('sources_merged', 0),
                        'processing_time_seconds': results.get('processing_time', 0)
                    }
                }
            
            job_metadata.update({
                'status': 'completed',
                'completed_at': datetime.now(timezone.utc).isoformat(),
                'results': results,
                'download_info': download_info,
                'processing_time_seconds': results.get('processing_time', 0)
            })
            
            # Store updated metadata
            self.redis.setex(job_key, self.session_ttl, json.dumps(job_metadata))
            
            # Broadcast status change
            self._broadcast_status_change(
                job_id, session_id, old_status, 'completed',
                {
                    'download_available': download_info is not None,
                    'processing_time': results.get('processing_time', 0),
                    'total_records': results.get('total_records', 0)
                }
            )
            
            logger.info(f"Job {job_id} marked as completed with download info")
    
    def mark_job_failed(self, job_id: str, session_id: str, error: str):
        """
        Mark job as failed with error details
        
        Args:
            job_id: Job ID
            session_id: Session ID
            error: Error message
        """
        job_key = f"job:{session_id}:{job_id}"
        job_data = self.redis.get(job_key)
        
        if job_data:
            job_metadata = json.loads(job_data)
            old_status = job_metadata.get('status', 'unknown')
            
            job_metadata.update({
                'status': 'failed',
                'failed_at': datetime.now(timezone.utc).isoformat(),
                'error': error
            })
            
            # Store updated metadata
            self.redis.setex(job_key, self.session_ttl, json.dumps(job_metadata))
            
            # Broadcast status change
            self._broadcast_status_change(
                job_id, session_id, old_status, 'failed',
                {'error_message': error}
            )
            
            logger.error(f"Job {job_id} marked as failed: {error}")
    
    def update_job_progress(self, job_id: str, session_id: str, progress_data: Dict[str, Any]):
        """
        Update job progress and broadcast to clients
        
        Args:
            job_id: Job ID
            session_id: Session ID
            progress_data: Progress information (percentage, message, etc.)
        """
        try:
            # Store progress in Redis with short TTL
            progress_key = f"job_progress:{session_id}:{job_id}"
            progress_info = {
                'job_id': job_id,
                'session_id': session_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                **progress_data
            }
            
            # Store with 1 hour TTL
            self.redis.setex(progress_key, 3600, json.dumps(progress_info))
            
            # Broadcast progress update
            self._broadcast_progress_update(job_id, session_id, progress_data)
            
        except Exception as e:
            logger.error(f"Error updating job progress: {e}")
    
    def get_job_progress(self, job_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current job progress
        
        Args:
            job_id: Job ID
            session_id: Session ID
            
        Returns:
            Progress data or None if not found
        """
        try:
            progress_key = f"job_progress:{session_id}:{job_id}"
            progress_data = self.redis.get(progress_key)
            
            if progress_data:
                return json.loads(progress_data)
            return None
            
        except Exception as e:
            logger.error(f"Error getting job progress: {e}")
            return None
    
    def create_progress_callback(self, job_id: str, session_id: str) -> Callable[[Dict[str, Any]], None]:
        """
        Create a progress callback function for workers
        
        Args:
            job_id: Job ID
            session_id: Session ID
            
        Returns:
            Progress callback function
        """
        def progress_callback(progress_data: Dict[str, Any]):
            """Progress callback that broadcasts updates via SocketIO"""
            try:
                self.update_job_progress(job_id, session_id, progress_data)
            except Exception as e:
                logger.error(f"Error in progress callback: {e}")
        
        return progress_callback
    
    def get_session_jobs(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get all jobs for a session
        
        Args:
            session_id: Session ID
            
        Returns:
            List of job dictionaries
        """
        session_jobs_key = f"session:{session_id}:jobs"
        job_ids = self.redis.smembers(session_jobs_key)
        
        jobs = []
        for job_id_bytes in job_ids:
            job_id = job_id_bytes.decode('utf-8')
            try:
                job_status = self.get_job_status(job_id, session_id)
                jobs.append(job_status)
            except Exception as e:
                logger.warning(f"Failed to get status for job {job_id}: {e}")
                # Remove invalid job from session
                self.redis.srem(session_jobs_key, job_id)
        
        return jobs
    
    def get_completed_jobs(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get all completed jobs for a session with download information
        
        Args:
            session_id: Session ID
            
        Returns:
            List of completed job information
        """
        try:
            all_jobs = self.get_session_jobs(session_id)
            completed_jobs = []
            
            for job in all_jobs:
                if job.get('status') == 'completed' and job.get('download_info'):
                    # Check if download file still exists
                    download_info = job.get('download_info', {})
                    file_path = download_info.get('file_path')
                    file_exists = file_path and os.path.exists(file_path)
                    
                    job_info = {
                        'job_id': job.get('job_id'),
                        'created_at': job.get('created_at'),
                        'completed_at': job.get('completed_at'),
                        'processing_time_seconds': job.get('processing_time_seconds', 0),
                        'download_available': file_exists,
                        'filename': download_info.get('filename'),
                        'file_size_bytes': download_info.get('file_size', 0),
                        'file_size_mb': round(download_info.get('file_size', 0) / 1024 / 1024, 2),
                        'stats': download_info.get('stats', {})
                    }
                    
                    if not file_exists:
                        job_info['message'] = 'File has been cleaned up'
                        
                    completed_jobs.append(job_info)
            
            # Sort by completion time (newest first)
            completed_jobs.sort(key=lambda x: x.get('completed_at', ''), reverse=True)
            return completed_jobs
            
        except Exception as e:
            logger.error(f"Error getting completed jobs: {e}")
            return []
    
    def cleanup_expired_jobs(self):
        """Clean up expired job data"""
        logger.info("Starting job cleanup process")
        
        # This would be implemented as part of the cleanup manager
        # For now, we rely on Redis TTL for automatic cleanup
        pass
    
    def _store_job_metadata(self, job_id: str, session_id: str, job_data: Dict[str, Any]):
        """Store job metadata in Redis with TTL"""
        job_key = f"job:{session_id}:{job_id}"
        self.redis.setex(job_key, self.session_ttl, json.dumps(job_data))
    
    def _add_job_to_session(self, session_id: str, job_id: str):
        """Add job to session's job list"""
        session_jobs_key = f"session:{session_id}:jobs"
        self.redis.sadd(session_jobs_key, job_id)
        self.redis.expire(session_jobs_key, self.session_ttl)
    
    def _verify_job_access(self, job_id: str, session_id: str) -> bool:
        """
        Verify that a session has access to a specific job
        
        Args:
            job_id: Job ID to verify
            session_id: Session ID to check access for
            
        Returns:
            True if session has access to the job
        """
        try:
            job_key = f"session:{session_id}:jobs"
            return self.redis.sismember(job_key, job_id)
        except Exception as e:
            logger.error(f"Error verifying job access: {e}")
            return False
    
    def cancel_job(self, job_id: str, session_id: str) -> bool:
        """
        Cancel a running job
        
        Args:
            job_id: Job ID to cancel
            session_id: Session ID (for access control)
            
        Returns:
            True if job was cancelled successfully
        """
        try:
            # Verify access
            if not self._verify_job_access(job_id, session_id):
                logger.warning(f"Access denied for job cancellation: {job_id} by {session_id}")
                return False
            
            # Get job from RQ
            try:
                job = self.queue.fetch_job(job_id)
                if not job:
                    logger.warning(f"Job not found for cancellation: {job_id}")
                    return False
                
                # Cancel job if it's not already finished
                job_status = job.get_status()
                if job_status in ['started', 'queued']:
                    job.cancel()
                    logger.info(f"Job cancelled: {job_id}")
                    
                    # Update job status in Redis
                    self._update_job_status(job_id, session_id, 'cancelled', {
                        'cancelled_at': datetime.now(timezone.utc).isoformat(),
                        'message': 'Job cancelled by user'
                    })
                    
                    return True
                else:
                    logger.info(f"Job cannot be cancelled (status: {job_status}): {job_id}")
                    return False
                    
            except Exception as e:
                logger.error(f"Error cancelling RQ job {job_id}: {e}")
                return False
        
        except Exception as e:
            logger.error(f"Error in cancel_job: {e}")
            return False
    
    def get_session_jobs(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get all jobs for a session
        
        Args:
            session_id: Session ID
            
        Returns:
            List of job information dictionaries
        """
        try:
            job_key = f"session:{session_id}:jobs"
            job_ids = self.redis.smembers(job_key)
            
            jobs = []
            for job_id_bytes in job_ids:
                job_id = job_id_bytes.decode('utf-8') if isinstance(job_id_bytes, bytes) else job_id_bytes
                try:
                    job_status = self.get_job_status(job_id, session_id)
                    jobs.append(job_status)
                except Exception as e:
                    logger.warning(f"Error getting status for job {job_id}: {e}")
                    continue
            
            # Sort by creation time (newest first)
            jobs.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            return jobs
        
        except Exception as e:
            logger.error(f"Error getting session jobs: {e}")
            return []
    
    def _check_session_limits(self, session_id: str) -> bool:
        """Check if session is within job limits"""
        session_jobs = self.get_session_jobs(session_id)
        active_jobs = [job for job in session_jobs if job['status'] in ['pending', 'started', 'processing']]
        
        # Handle config access properly
        if isinstance(self.config, type):
            max_concurrent = self.config().MAX_CONCURRENT_JOBS_PER_SESSION
        else:
            max_concurrent = self.config.MAX_CONCURRENT_JOBS_PER_SESSION
        
        return len(active_jobs) < max_concurrent
    
    def _map_rq_status(self, rq_status) -> str:
        """Map RQ job status to our status format"""
        status_mapping = {
            JobStatus.QUEUED: 'pending',
            JobStatus.STARTED: 'processing', 
            JobStatus.FINISHED: 'completed',
            JobStatus.FAILED: 'failed',
            JobStatus.STOPPED: 'cancelled',
            JobStatus.CANCELED: 'cancelled',
            JobStatus.SCHEDULED: 'pending',
            JobStatus.DEFERRED: 'pending'
        }
        return status_mapping.get(rq_status, 'unknown')


# Background job function (called by RQ worker)
def process_csv_job(job_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Background job function for processing CSV files
    
    Args:
        job_data: Job data dictionary
        
    Returns:
        Job results dictionary
    """
    import sys
    sys.path.append('.')
    
    from src.csv_processor import CSVProcessor
    from src.config_manager import ConfigManager
    
    job_id = job_data['job_id']
    session_id = job_data['session_id']
    
    logger.info(f"Starting background job {job_id} for session {session_id}")
    
    try:
        # Initialize components
        config_manager = ConfigManager('config/field_mappings.json')
        
        # Create progress callback
        def progress_callback(progress_data):
            """Callback to update job progress in Redis"""
            try:
                import redis
                from config.settings import Config
                
                redis_client = redis.from_url(Config.REDIS_URL, decode_responses=True)
                job_manager = JobManager(redis_client, Config)
                job_manager.update_progress(job_id, session_id, progress_data)
            except Exception as e:
                logger.error(f"Failed to update progress: {e}")
        
        # Initialize CSV processor with progress callback
        processor = CSVProcessor(config_manager, progress_callback)
        
        # Update job status to processing
        progress_callback({
            'message': 'Processing started',
            'percentage': 0,
            'status': 'processing'
        })
        
        # Process CSV files
        df, export_path = processor.process_files(
            job_data['file_paths'],
            job_data['table_type'],
            session_id
        )
        
        # Get processing statistics
        stats = processor.get_processing_stats()
        
        # Prepare results
        results = {
            'status': 'completed',
            'export_path': export_path,
            'stats': stats,
            'total_records': len(df),
            'processing_time': stats.get('processing_time', 0)
        }
        
        # If webhook mode, send webhooks
        if job_data.get('processing_mode') == 'webhook' and job_data.get('webhook_url'):
            # This will be implemented in the webhook sender
            results['webhook_status'] = 'pending'
            results['webhook_url'] = job_data['webhook_url']
        
        logger.info(f"Background job {job_id} completed successfully")
        return results
        
    except Exception as e:
        logger.error(f"Background job {job_id} failed: {e}")
        
        # Update progress with error
        try:
            import redis
            from config.settings import Config
            
            redis_client = redis.from_url(Config.REDIS_URL, decode_responses=True)
            job_manager = JobManager(redis_client, Config)
            job_manager.update_progress(job_id, session_id, {
                'message': f'Processing failed: {str(e)}',
                'percentage': 0,
                'status': 'failed'
            })
        except:
            pass
        
        raise


def start_worker():
    """Start RQ worker process"""
    import redis
    from config.settings import Config
    
    # Connect to Redis
    redis_connection = redis.from_url(Config.REDIS_URL, decode_responses=True)
    
    # Create worker
    worker = Worker(['csv_processing'], connection=redis_connection)
    
    logger.info("Starting RQ worker for CSV processing")
    worker.work() 