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

from src.logging_config import setup_module_logger
logger = setup_module_logger(__name__)

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
        
        # Initialize RQ queue (using default serialization)
        self.queue = Queue('csv_processing', connection=redis_connection)
        
        # Clear any corrupt jobs from the queue on startup
        try:
            self.queue.empty()
            logger.info("Cleared any existing jobs from queue on startup")
        except Exception as e:
            logger.warning(f"Could not clear queue on startup: {e}")
        
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
    
    def _broadcast_webhook_status(self, job_id: str, session_id: str, webhook_data: Dict[str, Any]):
        """Broadcast webhook-specific status updates"""
        if self.socketio:
            enhanced_data = {
                'job_id': job_id,
                'session_id': session_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'webhook_stage': webhook_data.get('stage', 'unknown'),
                'webhook_status': webhook_data.get('status', 'unknown'),
                'webhook_progress': webhook_data.get('progress', {}),
                'webhook_error': webhook_data.get('error')
            }
            
            # Broadcast to job room and session room
            self._broadcast_to_job(job_id, 'webhook_status', enhanced_data)
            self._broadcast_to_session(session_id, 'webhook_status', enhanced_data)
    
    def update_webhook_status(self, job_id: str, session_id: str, webhook_data: Dict[str, Any]):
        """
        Update webhook-specific status and progress
        
        Args:
            job_id: Job ID
            session_id: Session ID
            webhook_data: Webhook status information
        """
        try:
            # Store webhook status with TTL
            webhook_key = f"webhook_status:{session_id}:{job_id}"
            self.redis.setex(
                webhook_key,
                self.session_ttl,
                json.dumps(webhook_data)
            )
            
            # Broadcast webhook status
            self._broadcast_webhook_status(job_id, session_id, webhook_data)
            
            logger.debug(f"Updated webhook status for job {job_id}: {webhook_data.get('stage', 'unknown')}")
            
        except Exception as e:
            logger.error(f"Error updating webhook status: {e}")
    
    def get_webhook_status(self, job_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current webhook status
        
        Args:
            job_id: Job ID
            session_id: Session ID
            
        Returns:
            Webhook status data or None if not found
        """
        try:
            webhook_key = f"webhook_status:{session_id}:{job_id}"
            webhook_data = self.redis.get(webhook_key)
            
            if webhook_data:
                return json.loads(webhook_data)
            return None
            
        except Exception as e:
            logger.error(f"Error getting webhook status: {e}")
            return None
    
    def get_job_status(self, job_id: str, session_id: str) -> Dict[str, Any]:
        """
        Retrieve current job status and progress with enhanced webhook information
        
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
            # Check if this is a synchronous job (starts with 'sync_')
            if job_id.startswith('sync_'):
                return self._get_sync_job_status(job_id, session_id)
            else:
                return self._get_rq_job_status(job_id, session_id)
                
        except Exception as e:
            logger.error(f"Error getting job status for {job_id}: {e}")
            raise ValueError(f"Failed to get job status: {str(e)}")
    
    def _get_sync_job_status(self, job_id: str, session_id: str) -> Dict[str, Any]:
        """Get status for synchronous jobs stored directly in Redis"""
        try:
            # Get job metadata from Redis
            job_key = f"job:{session_id}:{job_id}"
            job_data = self.redis.get(job_key)
            
            if not job_data:
                raise ValueError(f"Synchronous job metadata not found: {job_id}")
            
            job_metadata = json.loads(job_data)
            
            # Get job results
            job_results = self._get_job_results(job_id, session_id)
            
            # Prepare status response for sync job
            status_data = {
                'job_id': job_id,
                'session_id': session_id,
                'status': job_metadata.get('status', 'completed'),
                'created_at': job_metadata.get('created_at'),
                'started_at': job_metadata.get('started_at'),
                'completed_at': job_metadata.get('completed_at'),
                'progress': {
                    'percentage': job_metadata.get('progress', 100),
                    'message': job_metadata.get('message', 'Processing completed'),
                    'stats': job_metadata.get('stats', {}),
                    'stage': 'completed'
                },
                'result_path': job_metadata.get('result_path'),
                'results': job_results,
                'error': job_metadata.get('error')
            }
            
            logger.info(f"Retrieved sync job status for {job_id}: {status_data['status']}")
            return status_data
            
        except Exception as e:
            logger.error(f"Error getting sync job status for {job_id}: {e}")
            raise
    
    def _get_rq_job_status(self, job_id: str, session_id: str) -> Dict[str, Any]:
        """Get status for RQ jobs"""
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
            
            # Get webhook status if available
            webhook_status = self.get_webhook_status(job_id, session_id)
            
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
                    'stage': progress.get('stage', 'unknown')
                },
                'webhook': webhook_status if webhook_status else None,
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
                # Use the actual status from metadata instead of hardcoding 'expired'
                status = job_metadata.get('status', 'unknown')
                return {
                    'job_id': job_id,
                    'session_id': session_id,
                    'status': status,
                    'created_at': job_metadata.get('created_at'),
                    'completed_at': job_metadata.get('completed_at'),
                    'progress': job_metadata.get('progress', 0),
                    'webhook': self.get_webhook_status(job_id, session_id),
                    'results': self._get_job_results(job_id, session_id)
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
    
    def update_job_progress(self, job_id: str, stage: str, message: str, percentage: float = None, stats: dict = None, webhook_stats: dict = None):
        """
        Update job progress and broadcast via WebSocket
        
        Args:
            job_id: Job ID
            stage: Current processing stage
            message: Progress message
            percentage: Optional progress percentage
            stats: Optional processing statistics
            webhook_stats: Optional webhook delivery statistics
        """
        try:
            # Get job metadata
            job_metadata = self._get_job_metadata(job_id)
            if not job_metadata:
                logger.error(f"Cannot update progress - job {job_id} not found")
                return
            
            session_id = job_metadata.get('session_id')
            if not session_id:
                logger.error(f"Cannot update progress - no session ID for job {job_id}")
                return
            
            # Update job metadata
            job_metadata['last_update'] = datetime.now(timezone.utc).isoformat()
            job_metadata['stage'] = stage
            job_metadata['progress'] = percentage or job_metadata.get('progress', 0)
            
            # Store updated metadata
            self._store_job_metadata(job_id, session_id, job_metadata)
            
            # Prepare progress data
            progress_data = {
                'job_id': job_id,
                'stage': stage,
                'status': job_metadata.get('status', 'processing'),
                'message': message,
                'percentage': percentage if percentage is not None else job_metadata.get('progress', 0),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            # Add processing stats if provided
            if stats:
                progress_data['stats'] = stats
            
            # Add webhook stats if provided
            if webhook_stats:
                progress_data['webhook_stats'] = webhook_stats
            
            # Add stage-specific information
            if stage == 'setup':
                progress_data['stage_info'] = {
                    'files_uploaded': len(job_metadata.get('files', [])),
                    'table_type': job_metadata.get('table_type'),
                    'processing_mode': job_metadata.get('processing_mode')
                }
            elif stage == 'processing':
                progress_data['stage_info'] = {
                    'current_operation': message,
                    'files_processed': stats.get('files_processed', 0) if stats else 0,
                    'total_records': stats.get('total_records', 0) if stats else 0
                }
            elif stage == 'webhook_delivery':
                progress_data['stage_info'] = {
                    'records_sent': webhook_stats.get('sent', 0) if webhook_stats else 0,
                    'records_failed': webhook_stats.get('failed', 0) if webhook_stats else 0,
                    'current_rate': webhook_stats.get('current_rate', 0) if webhook_stats else 0
                }
            
            # Broadcast progress update
            logger.info(f"Broadcasting progress for job {job_id}: {progress_data}")
            
            # Emit to both job-specific and session-specific rooms
            if self.socketio:
                self.socketio.emit('job_progress', progress_data, room=f"job_{job_id}")
                self.socketio.emit('job_progress', progress_data, room=f"session_{session_id}")
            
            # Store progress data in Redis for recovery
            progress_key = f"job_progress:{job_id}"
            self.redis.setex(progress_key, self.session_ttl, json.dumps(progress_data))
            
        except Exception as e:
            logger.error(f"Failed to update job progress: {e}")
            
    def update_job_status(self, job_id: str, new_status: str, error: str = None):
        """
        Update job status and broadcast via WebSocket
        
        Args:
            job_id: Job ID
            new_status: New job status
            error: Optional error message
        """
        try:
            # Get job metadata
            job_metadata = self._get_job_metadata(job_id)
            if not job_metadata:
                logger.error(f"Cannot update status - job {job_id} not found")
                return
            
            session_id = job_metadata.get('session_id')
            if not session_id:
                logger.error(f"Cannot update status - no session ID for job {job_id}")
                return
            
            # Get old status for change notification
            old_status = job_metadata.get('status')
            
            # Update job metadata
            job_metadata['status'] = new_status
            job_metadata['last_update'] = datetime.now(timezone.utc).isoformat()
            if new_status == 'completed':
                job_metadata['completed_at'] = datetime.now(timezone.utc).isoformat()
            if error:
                job_metadata['error'] = error
            
            # Store updated metadata
            self._store_job_metadata(job_id, session_id, job_metadata)
            
            # Prepare status change data
            status_data = {
                'job_id': job_id,
                'old_status': old_status,
                'new_status': new_status,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': error if error else None,
                'processing_mode': job_metadata.get('processing_mode'),
                'table_type': job_metadata.get('table_type')
            }
            
            # Add completion info if job completed
            if new_status == 'completed':
                status_data['completion_info'] = {
                    'processing_time': (
                        datetime.fromisoformat(job_metadata['completed_at']) -
                        datetime.fromisoformat(job_metadata['created_at'])
                    ).total_seconds(),
                    'files_processed': len(job_metadata.get('files', [])),
                    'download_available': job_metadata.get('processing_mode') == 'download'
                }
            
            # Broadcast status change
            logger.info(f"Broadcasting status change for job {job_id}: {status_data}")
            
            if self.socketio:
                self.socketio.emit('job_status_change', status_data, room=f"job_{job_id}")
                self.socketio.emit('job_status_change', status_data, room=f"session_{session_id}")
            
            # Store status data in Redis for recovery
            status_key = f"job_status:{job_id}"
            self.redis.setex(status_key, self.session_ttl, json.dumps(status_data))
            
        except Exception as e:
            logger.error(f"Failed to update job status: {e}")
            
    def get_job_status(self, job_id: str, session_id: str = None) -> dict:
        """
        Get detailed job status
        
        Args:
            job_id: Job ID
            session_id: Optional session ID for validation
            
        Returns:
            Dictionary with job status information
        """
        try:
            # Get job metadata from RQ Job object if possible
            job = Job.fetch(job_id, connection=self.redis)
            job_metadata = job.meta or {}
            
            # Add session_id if it's not already in the metadata
            if 'session_id' not in job_metadata and session_id:
                job_metadata['session_id'] = session_id
            
            # Fallback for sync jobs not in RQ
            if not job_metadata and session_id:
                 job_key = f"job:{session_id}:{job_id}"
                 job_data = self.redis.get(job_key)
                 if job_data:
                     job_metadata = json.loads(job_data)

            if not job_metadata:
                raise ValueError(f"Job {job_id} not found in RQ meta or Redis")
            
            # Validate session access if provided
            if session_id and job_metadata.get('session_id') != session_id:
                raise ValueError("Access denied")
            
            # Get latest progress data
            progress_key = f"job_progress:{job_id}"
            progress_data = self.redis.get(progress_key)
            progress = json.loads(progress_data) if progress_data else {}
            
            # Get latest status data
            status_key = f"job_status:{job_id}"
            status_data = self.redis.get(status_key)
            status = json.loads(status_data) if status_data else {}
            
            # Get job results if completed
            results = None
            if job_metadata.get('status') == 'completed':
                results_key = f"job_results:{job_metadata['session_id']}:{job_id}"
                results_data = self.redis.get(results_key)
                results = json.loads(results_data) if results_data else None
            
            # Combine all information
            return {
                'job_id': job_id,
                'status': job_metadata.get('status', 'unknown'),
                'stage': progress.get('stage', 'unknown'),
                'message': progress.get('message', ''),
                'percentage': progress.get('percentage', 0),
                'created_at': job_metadata.get('created_at'),
                'last_update': job_metadata.get('last_update'),
                'completed_at': job_metadata.get('completed_at'),
                'processing_mode': job_metadata.get('processing_mode'),
                'table_type': job_metadata.get('table_type'),
                'error': job_metadata.get('error'),
                'progress': progress,
                'status_info': status,
                'results': results,
                'files': [
                    {
                        'name': f.get('filename'),
                        'size': f.get('size'),
                        'upload_time': f.get('upload_time')
                    }
                    for f in job_metadata.get('files', [])
                ]
            }
            
        except ValueError as e:
            raise
        except Exception as e:
            logger.error(f"Failed to get job status: {e}")
            raise
    
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
                self.update_job_progress(job_id, progress_data.get('stage', 'unknown'), progress_data.get('message', ''), progress_data.get('percentage'), progress_data.get('stats'), progress_data.get('webhook_stats'))
            except Exception as e:
                logger.error(f"Error in progress callback: {e}")
        
        return progress_callback
    
    def get_session_jobs(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get all jobs for a session with robust error handling
        
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
                    # Try to get job status, but handle errors gracefully
                    job_status = self.get_job_status(job_id, session_id)
                    jobs.append(job_status)
                except Exception as e:
                    logger.warning(f"Error getting status for job {job_id}: {e}")
                    # Try to get basic job info from Redis directly
                    try:
                        job_metadata_key = f"job:{session_id}:{job_id}"
                        job_data = self.redis.get(job_metadata_key)
                        if job_data:
                            job_metadata = json.loads(job_data)
                            # Create a basic job status from metadata
                            basic_job = {
                                'job_id': job_id,
                                'status': job_metadata.get('status', 'unknown'),
                                'created_at': job_metadata.get('created_at'),
                                'completed_at': job_metadata.get('completed_at'),
                                'processing_mode': job_metadata.get('processing_mode', 'download'),
                                'progress': {
                                    'percentage': 100 if job_metadata.get('status') == 'completed' else 0,
                                    'message': job_metadata.get('message', 'Processing completed'),
                                    'stage': 'completed' if job_metadata.get('status') == 'completed' else 'unknown',
                                    'result_path': job_metadata.get('result_path'),
                                    'stats': job_metadata.get('stats', {})
                                }
                            }
                            jobs.append(basic_job)
                            logger.info(f"Retrieved basic job info for {job_id} from metadata")
                    except Exception as meta_error:
                        logger.error(f"Failed to get metadata for job {job_id}: {meta_error}")
                        # Remove invalid job from session
                        self.redis.srem(job_key, job_id)
                        continue
        
            # Sort by creation time (newest first)
            jobs.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            logger.info(f"Retrieved {len(jobs)} jobs for session {session_id}")
            return jobs
        
        except Exception as e:
            logger.error(f"Error getting session jobs: {e}")
            return []
    
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
    
    def _get_job_results(self, job_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        """Get job results from Redis"""
        try:
            job_results_key = f"job_results:{session_id}:{job_id}"
            job_results_data = self.redis.get(job_results_key)
            if job_results_data:
                return json.loads(job_results_data)
            return None
        except Exception as e:
            logger.error(f"Error getting job results: {e}")
            return None
    
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
            logger.info(f"=== JOB ACCESS VERIFICATION ===")
            logger.info(f"Checking access for job_id: {job_id}")
            logger.info(f"Session ID: {session_id}")
            
            job_key = f"session:{session_id}:jobs"
            logger.info(f"Checking session jobs key: {job_key}")
            
            is_member = self.redis.sismember(job_key, job_id)
            logger.info(f"Job {job_id} found in session jobs: {is_member}")
            
            # If not found in session jobs, but it's a sync job, check if job metadata exists
            if not is_member and job_id.startswith('sync_'):
                logger.info(f"Job not in session list but is sync job, checking metadata...")
                job_metadata_key = f"job:{session_id}:{job_id}"
                logger.info(f"Checking metadata key: {job_metadata_key}")
                metadata_exists = self.redis.exists(job_metadata_key)
                logger.info(f"Sync job {job_id} metadata exists: {metadata_exists}")
                
                if metadata_exists:
                    logger.info(f"ACCESS GRANTED via metadata check for sync job {job_id}")
                    return True
                else:
                    logger.error(f"ACCESS DENIED: No metadata found for sync job {job_id}")
                    return False
                
            if is_member:
                logger.info(f"ACCESS GRANTED via session jobs list for job {job_id}")
            else:
                logger.error(f"ACCESS DENIED: Job {job_id} not found in session {session_id}")
                
            return is_member
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