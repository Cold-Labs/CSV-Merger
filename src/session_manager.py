import os
import json
import time
import logging
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta, timezone
import redis
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from config.settings import Config

from src.logging_config import setup_module_logger
logger = setup_module_logger(__name__)

@dataclass
class SessionInfo:
    """Session information data class"""
    session_id: str
    created_at: datetime
    last_accessed: datetime
    expires_at: datetime
    storage_used_bytes: int = 0
    storage_used_mb: float = 0.0
    active_jobs: int = 0
    total_jobs: int = 0
    files_uploaded: int = 0
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        # Convert datetime objects to ISO strings
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionInfo':
        """Create SessionInfo from dictionary"""
        # Convert ISO strings back to datetime objects
        for key in ['created_at', 'last_accessed', 'expires_at']:
            if key in data and isinstance(data[key], str):
                data[key] = datetime.fromisoformat(data[key])
        return cls(**data)

class SessionManager:
    """Manages multi-tenant sessions with resource tracking and limits"""
    
    def __init__(self, redis_connection: redis.Redis, config):
        """
        Initialize session manager
        
        Args:
            redis_connection: Redis connection instance
            config: Application configuration
        """
        self.redis = redis_connection
        self.config = config
        
        # Create config instance to access properties
        config_instance = Config()
        
        # Configuration values - use config instance for properties
        self.session_ttl = config_instance.SESSION_TTL_SECONDS
        self.max_storage_per_session = config_instance.get_max_storage_per_session_bytes()  # Use the bytes method
        self.max_files_per_session = Config.MAX_FILES_PER_SESSION
        self.max_concurrent_jobs = Config.MAX_CONCURRENT_JOBS_PER_SESSION
        self.upload_dir = Config.TEMP_UPLOAD_DIR
        
        # Correct the max storage to use the session limit, not file size limit
        self.max_storage_per_session = Config.MAX_STORAGE_PER_SESSION_MB * 1024 * 1024
        
        # Redis key prefixes
        self.session_key_prefix = "session_data:"
        self.session_files_prefix = "session_files:"
        self.session_jobs_prefix = "session:"  # Used by job manager
        self.session_index_key = "sessions:active"
        
        logger.info("Session Manager initialized")
    
    def create_session(self, ip_address: Optional[str] = None, user_agent: Optional[str] = None, session_id_override: Optional[str] = None) -> SessionInfo:
        """
        Create a new session
        
        Args:
            ip_address: Client IP address
            user_agent: Client user agent
            session_id_override: Optional specific session ID to use
            
        Returns:
            SessionInfo object
        """
        session_id = session_id_override or str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.session_ttl)
        
        session_info = SessionInfo(
            session_id=session_id,
            created_at=now,
            last_accessed=now,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        # Store session data in Redis
        session_key = f"{self.session_key_prefix}{session_id}"
        self.redis.setex(session_key, self.session_ttl, json.dumps(session_info.to_dict()))
        
        # Add to active sessions index
        self.redis.sadd(self.session_index_key, session_id)
        self.redis.expire(self.session_index_key, self.session_ttl)
        
        # Create session directory
        session_dir = self._get_session_dir(session_id)
        os.makedirs(session_dir, exist_ok=True)
        
        logger.info(f"Created new session: {session_id}")
        return session_info
    
    def get_session(self, session_id: str, update_access: bool = True) -> Optional[SessionInfo]:
        """
        Get session information
        
        Args:
            session_id: Session ID
            update_access: Whether to update last accessed time
            
        Returns:
            SessionInfo object or None if not found
        """
        session_key = f"{self.session_key_prefix}{session_id}"
        session_data = self.redis.get(session_key)
        
        if not session_data:
            return None
        
        try:
            session_dict = json.loads(session_data)
            session_info = SessionInfo.from_dict(session_dict)
            
            # Update storage and job counts
            self._update_session_stats(session_info)
            
            # Update last accessed time if requested
            if update_access:
                session_info.last_accessed = datetime.now(timezone.utc)
                self._save_session(session_info)
            
            return session_info
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Error parsing session data for {session_id}: {e}")
            return None
    
    def validate_session(self, session_id: str) -> bool:
        """
        Validate if session exists and is not expired
        
        Args:
            session_id: Session ID to validate
            
        Returns:
            True if session is valid
        """
        session_info = self.get_session(session_id, update_access=False)
        if not session_info:
            return False
        
        # Check if expired
        if datetime.now(timezone.utc) > session_info.expires_at:
            logger.info(f"Session {session_id} has expired")
            self.delete_session(session_id)
            return False
        
        return True
    
    def extend_session(self, session_id: str) -> bool:
        """
        Extend session TTL
        
        Args:
            session_id: Session ID
            
        Returns:
            True if session was extended
        """
        session_info = self.get_session(session_id, update_access=False)
        if not session_info:
            return False
        
        # Extend expiration time
        now = datetime.now(timezone.utc)
        session_info.expires_at = now + timedelta(seconds=self.session_ttl)
        session_info.last_accessed = now
        
        # Update Redis TTL
        session_key = f"{self.session_key_prefix}{session_id}"
        self.redis.setex(session_key, self.session_ttl, json.dumps(session_info.to_dict()))
        
        logger.debug(f"Extended session TTL for {session_id}")
        return True
    
    def check_storage_limit(self, session_id: str, additional_size: int = 0) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if session is within storage limits
        
        Args:
            session_id: Session ID
            additional_size: Additional bytes to check
            
        Returns:
            Tuple of (within_limit, limit_info)
        """
        session_info = self.get_session(session_id, update_access=False)
        if not session_info:
            return False, {'error': 'Session not found'}
        
        current_usage = session_info.storage_used_bytes
        projected_usage = current_usage + additional_size
        
        limit_info = {
            'current_usage_bytes': current_usage,
            'current_usage_mb': round(current_usage / (1024 * 1024), 2),
            'projected_usage_bytes': projected_usage,
            'projected_usage_mb': round(projected_usage / (1024 * 1024), 2),
            'limit_bytes': self.max_storage_per_session,
            'limit_mb': round(self.max_storage_per_session / (1024 * 1024), 2),
            'percentage_used': round((projected_usage / self.max_storage_per_session) * 100, 1),
            'within_limit': projected_usage <= self.max_storage_per_session
        }
        
        return limit_info['within_limit'], limit_info
    
    def check_file_limit(self, session_id: str, additional_files: int = 1) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if session is within file count limits
        
        Args:
            session_id: Session ID
            additional_files: Additional files to check
            
        Returns:
            Tuple of (within_limit, limit_info)
        """
        session_info = self.get_session(session_id, update_access=False)
        if not session_info:
            return False, {'error': 'Session not found'}
        
        current_files = session_info.files_uploaded
        projected_files = current_files + additional_files
        
        limit_info = {
            'current_files': current_files,
            'projected_files': projected_files,
            'limit_files': self.max_files_per_session,
            'percentage_used': round((projected_files / self.max_files_per_session) * 100, 1),
            'within_limit': projected_files <= self.max_files_per_session
        }
        
        return limit_info['within_limit'], limit_info
    
    def check_job_limit(self, session_id: str, additional_jobs: int = 1) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if session is within concurrent job limits
        
        Args:
            session_id: Session ID
            additional_jobs: Additional jobs to check
            
        Returns:
            Tuple of (within_limit, limit_info)
        """
        session_info = self.get_session(session_id, update_access=False)
        if not session_info:
            return False, {'error': 'Session not found'}
        
        current_jobs = session_info.active_jobs
        projected_jobs = current_jobs + additional_jobs
        
        limit_info = {
            'current_jobs': current_jobs,
            'projected_jobs': projected_jobs,
            'limit_jobs': self.max_concurrent_jobs,
            'percentage_used': round((projected_jobs / self.max_concurrent_jobs) * 100, 1),
            'within_limit': projected_jobs <= self.max_concurrent_jobs
        }
        
        return limit_info['within_limit'], limit_info
    
    def add_file_to_session(self, session_id: str, file_path: str, file_size: int) -> bool:
        """
        Register a file upload with the session
        
        Args:
            session_id: Session ID
            file_path: Path to uploaded file
            file_size: File size in bytes
            
        Returns:
            True if file was registered successfully
        """
        # Check storage and file limits
        storage_ok, storage_info = self.check_storage_limit(session_id, file_size)
        if not storage_ok:
            logger.warning(f"Storage limit exceeded for session {session_id}: {storage_info}")
            return False
        
        files_ok, files_info = self.check_file_limit(session_id, 1)
        if not files_ok:
            logger.warning(f"File limit exceeded for session {session_id}: {files_info}")
            return False
        
        # Register file
        files_key = f"{self.session_files_prefix}{session_id}"
        file_info = {
            'path': file_path,
            'size': file_size,
            'uploaded_at': datetime.now(timezone.utc).isoformat()
        }
        
        self.redis.hset(files_key, file_path, json.dumps(file_info))
        self.redis.expire(files_key, self.session_ttl)
        
        # Update session stats
        session_info = self.get_session(session_id, update_access=False)
        if session_info:
            session_info.storage_used_bytes += file_size
            session_info.storage_used_mb = round(session_info.storage_used_bytes / (1024 * 1024), 2)
            session_info.files_uploaded += 1
            self._save_session(session_info)
        
        logger.info(f"File registered for session {session_id}: {file_path} ({file_size} bytes)")
        return True
    
    def get_session_files(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get all files for a session
        
        Args:
            session_id: Session ID
            
        Returns:
            List of file information dictionaries
        """
        files_key = f"{self.session_files_prefix}{session_id}"
        files_data = self.redis.hgetall(files_key)
        
        files = []
        for file_path, file_info_json in files_data.items():
            try:
                file_info = json.loads(file_info_json)
                file_info['path'] = file_path.decode('utf-8') if isinstance(file_path, bytes) else file_path
                files.append(file_info)
            except json.JSONDecodeError:
                continue
        
        return files
    
    def delete_session(self, session_id: str) -> bool:
        """
        Delete session and all associated data
        
        Args:
            session_id: Session ID
            
        Returns:
            True if session was deleted
        """
        logger.info(f"Deleting session: {session_id}")
        
        try:
            # Remove session data
            session_key = f"{self.session_key_prefix}{session_id}"
            self.redis.delete(session_key)
            
            # Remove files data
            files_key = f"{self.session_files_prefix}{session_id}"
            self.redis.delete(files_key)
            
            # Remove jobs data (handled by job manager)
            jobs_key = f"{self.session_jobs_prefix}{session_id}:jobs"
            self.redis.delete(jobs_key)
            
            # Remove from active sessions index
            self.redis.srem(self.session_index_key, session_id)
            
            # Delete session directory and files
            session_dir = self._get_session_dir(session_id)
            if os.path.exists(session_dir):
                import shutil
                shutil.rmtree(session_dir, ignore_errors=True)
                logger.info(f"Deleted session directory: {session_dir}")
            
            logger.info(f"Session {session_id} deleted successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {e}")
            return False
    
    def get_all_sessions(self) -> List[SessionInfo]:
        """
        Get all active sessions
        
        Returns:
            List of SessionInfo objects
        """
        session_ids = self.redis.smembers(self.session_index_key)
        sessions = []
        
        for session_id_bytes in session_ids:
            session_id = session_id_bytes.decode('utf-8') if isinstance(session_id_bytes, bytes) else session_id_bytes
            session_info = self.get_session(session_id, update_access=False)
            if session_info:
                sessions.append(session_info)
        
        return sessions
    
    def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions
        
        Returns:
            Number of sessions cleaned up
        """
        logger.info("Starting expired session cleanup")
        
        sessions = self.get_all_sessions()
        cleaned_count = 0
        now = datetime.now(timezone.utc)
        
        for session in sessions:
            if now > session.expires_at:
                self.delete_session(session.session_id)
                cleaned_count += 1
        
        logger.info(f"Cleaned up {cleaned_count} expired sessions")
        return cleaned_count
    
    def get_storage_summary(self) -> Dict[str, Any]:
        """
        Get storage usage summary across all sessions
        
        Returns:
            Storage summary dictionary
        """
        sessions = self.get_all_sessions()
        
        total_storage = sum(session.storage_used_bytes for session in sessions)
        total_files = sum(session.files_uploaded for session in sessions)
        active_jobs = sum(session.active_jobs for session in sessions)
        
        summary = {
            'total_sessions': len(sessions),
            'total_storage_bytes': total_storage,
            'total_storage_mb': round(total_storage / (1024 * 1024), 2),
            'total_files': total_files,
            'active_jobs': active_jobs,
            'avg_storage_per_session_mb': round((total_storage / len(sessions)) / (1024 * 1024), 2) if sessions else 0,
            'sessions': [session.to_dict() for session in sessions[:10]]  # First 10 sessions
        }
        
        return summary
    
    def _get_session_dir(self, session_id: str) -> str:
        """Get session directory path"""
        return os.path.join(self.upload_dir, session_id)
    
    def _update_session_stats(self, session_info: SessionInfo):
        """Update session statistics from actual data"""
        # Update storage usage from files
        files = self.get_session_files(session_info.session_id)
        total_size = sum(file_info.get('size', 0) for file_info in files)
        session_info.storage_used_bytes = total_size
        session_info.storage_used_mb = round(total_size / (1024 * 1024), 2)
        session_info.files_uploaded = len(files)
        
        # Update job count (this would be called by job manager)
        jobs_key = f"{self.session_jobs_prefix}{session_info.session_id}:jobs"
        job_count = self.redis.scard(jobs_key)
        session_info.active_jobs = job_count if job_count else 0
    
    def _save_session(self, session_info: SessionInfo):
        """Save session info to Redis"""
        session_key = f"{self.session_key_prefix}{session_info.session_id}"
        self.redis.setex(session_key, self.session_ttl, json.dumps(session_info.to_dict())) 
    
    def store_file(self, session_id: str, file_obj, filename: str, force_clear: bool = False) -> Dict[str, Any]:
        """
        Store an uploaded file for a session
        
        Args:
            session_id: Session ID
            file_obj: File object from request
            filename: Original filename
            force_clear: If True, clear existing files before checking limits
            
        Returns:
            Dictionary with file information
            
        Raises:
            ValueError: If storage or file limits exceeded
        """
        # If force_clear is enabled, clear all existing files first
        if force_clear:
            logger.info(f"Force clearing files for session {session_id}")
            self._force_clear_session_files(session_id)
        
        # Clean filename for security
        safe_filename = self._clean_filename(filename)
        
        # Get file size
        file_obj.seek(0, 2)  # Seek to end
        file_size = file_obj.tell()
        file_obj.seek(0)  # Reset to beginning
        
        # Check limits before saving
        storage_ok, storage_info = self.check_storage_limit(session_id, file_size)
        if not storage_ok:
            current_mb = storage_info.get('current_usage_mb', 0)
            limit_mb = storage_info.get('limit_mb', 0)
            projected_mb = storage_info.get('projected_usage_mb', 0)
            raise ValueError(f"Storage limit exceeded: {projected_mb}MB would exceed {limit_mb}MB limit (currently using {current_mb}MB)")
        
        files_ok, files_info = self.check_file_limit(session_id, 1)
        if not files_ok:
            current_files = files_info.get('current_files', 0)
            limit_files = files_info.get('limit_files', 0)
            projected_files = files_info.get('projected_files', 0)
            raise ValueError(f"File limit exceeded: {projected_files} files would exceed {limit_files} file limit (currently have {current_files} files)")
        
        # Create session directory if it doesn't exist
        session_dir = self._get_session_dir(session_id)
        os.makedirs(session_dir, exist_ok=True)
        
        # Save file
        file_path = os.path.join(session_dir, safe_filename)
        
        # Handle duplicate filenames by adding timestamp
        if os.path.exists(file_path):
            name, ext = os.path.splitext(safe_filename)
            timestamp = int(datetime.now(timezone.utc).timestamp())
            safe_filename = f"{name}_{timestamp}{ext}"
            file_path = os.path.join(session_dir, safe_filename)
        
        # Save the file
        file_obj.save(file_path)
        actual_size = os.path.getsize(file_path)
        
        # Register with session
        success = self.add_file_to_session(session_id, file_path, actual_size)
        if not success:
            # Clean up if registration failed
            try:
                os.remove(file_path)
            except OSError:
                pass
            raise ValueError("Failed to register file with session")
        
        # Return file information
        file_info = {
            'filename': safe_filename,
            'original_filename': filename,
            'path': file_path,
            'size': actual_size,
            'uploaded_at': datetime.now(timezone.utc).isoformat()
        }
        
        logger.info(f"File stored for session {session_id}: {safe_filename} ({actual_size} bytes)")
        return file_info
    
    def _force_clear_session_files(self, session_id: str):
        """Force clear all files for a session, bypassing normal checks"""
        try:
            logger.info(f"Force clearing session files for {session_id}")
            
            # Clear Redis file data
            files_key = f"{self.session_files_prefix}{session_id}"
            deleted_count = self.redis.delete(files_key)
            logger.info(f"Deleted Redis files key {files_key}: {deleted_count}")
            
            # Clear session directory
            session_dir = self._get_session_dir(session_id)
            if os.path.exists(session_dir):
                import shutil
                shutil.rmtree(session_dir, ignore_errors=True)
                logger.info(f"Deleted session directory: {session_dir}")
            
            # Reset session file count
            session_info = self.get_session(session_id, update_access=False)
            if session_info:
                session_info.files_uploaded = 0
                session_info.storage_used_bytes = 0
                session_info.storage_used_mb = 0.0
                self._save_session(session_info)
                logger.info(f"Reset session stats for {session_id}")
                
        except Exception as e:
            logger.error(f"Error force clearing session files: {e}")
            # Don't raise - this is a cleanup operation
    
    def _clean_filename(self, filename: str) -> str:
        """
        Clean filename for security
        
        Args:
            filename: Original filename
            
        Returns:
            Cleaned filename
        """
        # Remove directory components
        filename = os.path.basename(filename)
        
        # Replace unsafe characters
        safe_chars = "-_.() abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        filename = ''.join(c for c in filename if c in safe_chars)
        
        # Ensure it ends with .csv
        if not filename.lower().endswith('.csv'):
            filename += '.csv'
        
        # Limit length
        if len(filename) > 100:
            name, ext = os.path.splitext(filename)
            filename = name[:95] + ext
        
        return filename 

    def update_session(self, session_id: str, session_data: Dict[str, Any]) -> bool:
        """
        Update session data
        
        Args:
            session_id: Session ID
            session_data: Updated session data dictionary
            
        Returns:
            True if update was successful
        """
        try:
            # Get current session
            session_info = self.get_session(session_id, update_access=False)
            if not session_info:
                return False
            
            # Update fields that are allowed to be modified
            updatable_fields = ['files_uploaded', 'uploaded_files', 'total_file_size']
            
            for field in updatable_fields:
                if field in session_data:
                    setattr(session_info, field, session_data[field])
            
            # Save updated session
            self._save_session(session_info)
            return True
            
        except Exception as e:
            logger.error(f"Error updating session {session_id}: {e}")
            return False 