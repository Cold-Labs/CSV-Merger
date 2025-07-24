#!/usr/bin/env python3
"""
CSV Merger - Main Flask Application
Professional lead processing for cold email agencies
"""

# CRITICAL: Eventlet monkey patch MUST be first, before any other imports
import eventlet
eventlet.monkey_patch()

import os
import sys
import json
import logging
import asyncio
from datetime import datetime, timezone
from functools import wraps

import redis
from flask import Flask, render_template, request, jsonify, session, send_file
from flask_socketio import SocketIO, emit, join_room, leave_room

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config.settings import Config
from src.session_manager import SessionManager
from src.queue_manager import JobManager
from src.config_manager import ConfigManager
# Removed csv_processor_minimal import - using CSVProcessor instead

# Configure eventlet for async operations
eventlet.monkey_patch()

# Configure logging
def setup_logging():
    """Setup logging configuration for production and development"""
    from src.logging_config import setup_app_logging
    setup_app_logging()

def create_app():
    """Create and configure Flask application"""
    
    # Validate environment
    Config.validate_environment()
    
    # Setup logging
    setup_logging()
    
    # Create directories
    Config.create_directories()
    
    logger = logging.getLogger(__name__)
    
    # Initialize Flask app
    app = Flask(__name__)
    app.config.update(Config.get_flask_config())
    
    # Initialize SocketIO
    socketio = SocketIO(
        app,
        cors_allowed_origins="*" if not Config.IS_PRODUCTION else None,
        async_mode='eventlet',
        logger=not Config.IS_PRODUCTION,
        engineio_logger=not Config.IS_PRODUCTION
    )
    
    # Initialize Redis connection with retry logic for Railway
    redis_client = None
    max_retries = 5
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            redis_config = Config.get_redis_config()
            if 'connection_pool' in redis_config:
                # Use Redis URL
                redis_client = redis.from_url(Config.REDIS_URL, decode_responses=True)
            else:
                # Use individual Redis settings
                redis_client = redis.Redis(**redis_config)
            
            # Test connection
            redis_client.ping()
            logger.info(f"Redis connection established on attempt {attempt + 1}")
            break
        except Exception as e:
            logger.warning(f"Redis connection attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying Redis connection in {retry_delay} seconds...")
                import time
                time.sleep(retry_delay)
            else:
                logger.error("All Redis connection attempts failed. App will start without Redis (degraded mode)")
                redis_client = None
    
    # Initialize managers with debug logging
    logger.info("Initializing ConfigManager...")
    config_manager = ConfigManager(Config.FIELD_MAPPINGS_FILE)
    logger.info("ConfigManager initialized successfully")
    
    logger.info("Initializing SessionManager...")
    session_manager = SessionManager(redis_client, Config()) if redis_client else None
    logger.info("SessionManager initialized successfully" if session_manager else "SessionManager skipped (no Redis)")
    
    logger.info("Initializing JobManager...")  
    job_manager = JobManager(redis_client, Config()) if redis_client else None
    logger.info("JobManager initialized successfully" if job_manager else "JobManager skipped (no Redis)")
    
    # Store managers in app context
    logger.info("Storing managers in app context...")
    app.redis = redis_client
    app.config_manager = config_manager
    app.session_manager = session_manager
    app.job_manager = job_manager
    app.socketio = socketio
    logger.info("Managers stored successfully")
    
    # Set SocketIO reference in job manager for real-time updates
    # if job_manager and socketio:
    #     job_manager.set_socketio(socketio)
    
    def validate_session_id(session_id: str) -> bool:
        """Validate session ID"""
        return app.session_manager.validate_session(session_id) if app.session_manager else True
    
    @app.before_request
    def before_request():
        """Initialize session for new users"""
        if 'session_id' not in session and session_manager:
            user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
            user_agent = request.headers.get('User-Agent')
            
            session_info = session_manager.create_session(user_ip, user_agent)
            session['session_id'] = session_info.session_id
            session.permanent = True
            
            logger.info(f"Created new session: {session_info.session_id}")

    # Add security headers for production
    @app.after_request
    def after_request(response):
        """Add security headers"""
        if Config.SECURE_HEADERS:
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['X-XSS-Protection'] = '1; mode=block'
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
            # Temporarily disable CSP for debugging on Railway
            # response.headers['Content-Security-Policy'] = "default-src 'self' 'unsafe-inline' 'unsafe-eval' https: data: blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://cdn.socket.io; style-src 'self' 'unsafe-inline' https:; connect-src 'self' wss: ws: https:"
        
        return response

    # Favicon route to prevent 404 errors
    @app.route('/favicon.ico')
    def favicon():
        """Serve favicon to prevent 404 errors"""
        return '', 204
    
    # Simple health check for Railway (no dependencies)
    @app.route('/health')
    def simple_health():
        """Simple health check without dependencies"""
        return jsonify({'status': 'ok', 'timestamp': datetime.now(timezone.utc).isoformat()}), 200
    
    # Detailed health check endpoint
    @app.route('/api/health')
    def health_check():
        """Health check endpoint for Railway and monitoring"""
        try:
            health_data = {
                'status': 'healthy',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'environment': Config.FLASK_ENV,
                'version': '1.0.0'
            }
            
            # Check Redis connection
            if redis_client:
                try:
                    redis_client.ping()
                    health_data['redis'] = 'connected'
                except:
                    health_data['redis'] = 'disconnected'
                    # Don't mark as degraded - app can function without Redis temporarily
            else:
                health_data['redis'] = 'not_configured'
            
            # Check managers
            health_data['config'] = 'loaded' if config_manager else 'error'
            health_data['session_manager'] = 'active' if session_manager else 'inactive'
            health_data['job_manager'] = 'active' if job_manager else 'inactive'
            
            status_code = 200 if health_data['status'] == 'healthy' else 503
            return jsonify(health_data), status_code
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return jsonify({
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }), 503

    # Main route
    @app.route('/')
    def index():
        """Main application page"""
        return render_template('index.html')

    # WebSocket test page
    @app.route('/test/websocket')
    def websocket_test():
        """Serve WebSocket test page"""
        return render_template('websocket_test.html')

    # Debug endpoint to test session validation
    @app.route('/api/debug/session', methods=['GET', 'POST'])
    def debug_session():
        """Debug endpoint to test session handling"""
        session_id = session.get('session_id')
        
        if not session_id:
            # Create session like upload endpoint does
            if app.session_manager:
                user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
                user_agent = request.headers.get('User-Agent')
                session_info = app.session_manager.create_session(user_ip, user_agent)
                session_id = session_info.session_id
                session['session_id'] = session_id
                session.permanent = True
                logger.info(f"DEBUG: Created new session: {session_id}")
            else:
                import uuid
                session_id = f"temp_{str(uuid.uuid4())[:8]}"
                session['session_id'] = session_id
                logger.info(f"DEBUG: Created temporary session: {session_id}")
        
        return jsonify({
            'session_id': session_id,
            'session_valid': validate_session_id(session_id),
            'request_method': request.method,
            'has_session_manager': app.session_manager is not None,
            'cookies_received': dict(request.cookies),
            'headers': dict(request.headers)
        })
    
    @app.route('/api/debug/clear-redis', methods=['POST'])
    def debug_clear_redis():
        """TEMPORARY: Clear Redis for debugging path issues"""
        try:
            if not app.redis:
                return jsonify({'error': 'Redis not available'}), 503
            
            # Clear all session data
            keys_deleted = 0
            for pattern in ['session_data:*', 'session_files:*', 'job:*', 'job_results:*']:
                keys = app.redis.keys(pattern)
                if keys:
                    app.redis.delete(*keys)
                    keys_deleted += len(keys)
            
            # Clear sessions index
            app.redis.delete('sessions:active')
            
            logger.info(f"DEBUG: Cleared {keys_deleted} Redis keys")
            return jsonify({
                'success': True, 
                'message': f'Cleared {keys_deleted} Redis keys',
                'cleared_patterns': ['session_data:*', 'session_files:*', 'job:*', 'job_results:*']
            })
            
        except Exception as e:
            logger.error(f"Error clearing Redis: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/config', methods=['GET', 'POST'])
    def api_config():
        """Get or update application configuration"""
        try:
            if request.method == 'POST':
                # Update config (for admin/authorized users)
                data = request.get_json()
                app.config_manager.update_config(data)
                return jsonify({'success': True, 'message': 'Configuration updated'})
            else:
                # Get current config
                return jsonify(app.config_manager.get_config())
        except Exception as e:
            logger.error(f"Error handling config: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500


    @app.route('/api/login', methods=['POST'])
    def login():
        """Login a user and set their ID in the session"""
        data = request.json
        user_id = data.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': 'User ID is required'}), 400
        
        session['user_id'] = user_id
        # Use the user_id as the primary session identifier
        session['session_id'] = user_id 
        logger.info(f"User '{user_id}' logged in. Session ID set to '{user_id}'.")
        
        return jsonify({'success': True, 'user_id': user_id, 'session_id': user_id})


    @app.route('/api/logout', methods=['POST'])
    def logout():
        """Logout a user and clear their session"""
        user_id = session.get('user_id')
        if user_id and app.session_manager:
            # The session_id is the user_id, so this deletes the user's data
            app.session_manager.delete_session(user_id)
            logger.info(f"Cleared session data for user '{user_id}'.")
        
        session.clear()
        logger.info(f"User '{user_id}' logged out.")
        return jsonify({'success': True, 'message': 'Logged out successfully'})


    @app.route('/api/upload', methods=['POST'])
    def upload_files():
        """Handle file upload and store in session"""
        try:
            user_id = session.get('user_id')
            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401

            session_id = user_id # Use user_id as the session_id

            # Ensure a session exists for the user
            if app.session_manager and not app.session_manager.get_session(session_id):
                user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
                user_agent = request.headers.get('User-Agent')
                app.session_manager.create_session(user_ip, user_agent, session_id_override=session_id)
                logger.info(f"Created a new session for user '{user_id}' with session_id '{session_id}'.")
            
            logger.info(f"=== UPLOAD REQUEST DEBUG ===")
            logger.info(f"Request method: {request.method}")
            logger.info(f"User ID: {user_id}")
            logger.info(f"Session ID: {session_id}")
            logger.info(f"Session manager available: {app.session_manager is not None}")
            
            # Check if files were uploaded
            if 'files' not in request.files:
                return jsonify({'error': 'No files uploaded'}), 400
            
            files = request.files.getlist('files')
            if not files or all(f.filename == '' for f in files):
                return jsonify({'error': 'No files selected'}), 400
            
            # Create config instance for property access
            config_instance = Config()
            
            # Validate and store files
            uploaded_files = []
            total_size = 0
            
            for file in files:
                if not file or file.filename == '':
                    continue
                
                # Validate file type
                if not file.filename.lower().endswith('.csv'):
                    return jsonify({'error': f'File {file.filename} is not a CSV file'}), 400
                
                # Check file size
                file.seek(0, 2)  # Seek to end of file
                file_size = file.tell()
                file.seek(0)  # Reset to beginning
                
                if file_size > config_instance.get_max_file_size_bytes():
                    return jsonify({'error': f'File {file.filename} exceeds maximum size limit'}), 400
                
                total_size += file_size
                
                # Store file using session manager
                if app.session_manager:
                    # Check current files in session instead of total uploaded count
                    session_files = app.session_manager.get_session_files(session_id)
                    force_clear = False
                    
                    # Only force clear if there are actually 10+ files currently in the session
                    if len(session_files) >= 10:
                        logger.warning(f"Session has {len(session_files)} current files, force clearing before upload")
                        force_clear = True
                    
                    file_info = app.session_manager.store_file(session_id, file, file.filename, force_clear=force_clear)
                    logger.info(f"Stored file {file.filename} for session {session_id}: {file_info}")
                else:
                    # Temporary storage when session manager is disabled
                    import tempfile
                    import os
                    temp_dir = tempfile.mkdtemp(prefix=f"csv_merger_{session_id}_")
                    file_path = os.path.join(temp_dir, file.filename)
                    file.save(file_path)
                    file_info = {
                        'filename': file.filename,
                        'size': file_size,
                        'path': file_path,
                        'upload_time': datetime.now(timezone.utc).isoformat()
                    }
                    logger.info(f"Stored file {file.filename} temporarily: {file_info}")
                uploaded_files.append(file_info)
            
            # Set Flask session for download access
            session['session_id'] = session_id
            session['user_id'] = user_id
            
            # Verify the session and files after upload
            if app.session_manager:
                verification_session = app.session_manager.get_session(session_id)
                verification_files = app.session_manager.get_session_files(session_id)
                logger.info(f"POST-UPLOAD VERIFICATION:")
                logger.info(f"Session exists: {verification_session is not None}")
                if verification_session:
                    logger.info(f"Session files_uploaded count: {verification_session.files_uploaded}")
                logger.info(f"Files in session: {len(verification_files)}")
                logger.info(f"File details: {verification_files}")
            
            logger.info(f"Successfully uploaded {len(uploaded_files)} files for session {session_id}")
            logger.info(f"Uploaded files: {[f['filename'] for f in uploaded_files]}")
            
            return jsonify({
                'success': True,
                'message': f'Successfully uploaded {len(uploaded_files)} files',
                'files': uploaded_files,
                'total_size': total_size,
                'session_id': session_id
            }), 200
        
        except Exception as e:
            logger.error(f"File upload error: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/session/clear', methods=['POST'])
    def clear_session():
        """Clear all files for the current user's session"""
        try:
            user_id = session.get('user_id')
            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401
            
            logger.info(f"=== CLEARING SESSION FOR USER: {user_id} ===")

            if app.session_manager:
                # Check session state before deletion
                session_info_before = app.session_manager.get_session(user_id)
                if session_info_before:
                    logger.info(f"Session before deletion - files: {session_info_before.files_uploaded}, storage: {session_info_before.storage_used_mb}MB")
                    files_before = app.session_manager.get_session_files(user_id)
                    logger.info(f"Files in session before deletion: {len(files_before)}")
                else:
                    logger.info("No session found before deletion")

                # The session_id is the user_id, so this deletes the user's files and session data
                deleted = app.session_manager.delete_session(user_id)
                logger.info(f"Session deletion result: {deleted}")
                
                if deleted:
                    logger.info(f"Cleared session for user '{user_id}'")
            
                    # Wait a moment to ensure deletion is complete
                    import time
                    time.sleep(0.1)
                    
                    # Re-create a fresh session for the user
                    user_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
                    user_agent = request.headers.get('User-Agent')
                    new_session = app.session_manager.create_session(ip_address=user_ip, user_agent=user_agent, session_id_override=user_id)
                    logger.info(f"Created fresh session: {new_session.session_id}, files: {new_session.files_uploaded}")
                    
                    # Verify the new session is clean
                    verification_session = app.session_manager.get_session(user_id)
                    if verification_session:
                        logger.info(f"Verification - new session files: {verification_session.files_uploaded}, storage: {verification_session.storage_used_mb}MB")
                        verification_files = app.session_manager.get_session_files(user_id)
                        logger.info(f"Verification - files in new session: {len(verification_files)}")
                    
                    return jsonify({'success': True, 'message': 'Session cleared and reset successfully.'})
                else:
                     return jsonify({'success': False, 'message': 'Failed to clear session.'}), 500
            
            return jsonify({'success': True, 'message': 'Session cleared (no session manager).'})
        
        except Exception as e:
            logger.error(f"Error clearing session: {e}", exc_info=True)
            return jsonify({'error': f'Failed to clear session: {str(e)}'}), 500


    @app.route('/api/jobs', methods=['POST'])
    def submit_job():
        """Submit a new CSV processing job"""
        try:
            user_id = session.get('user_id')
            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401

            session_id = user_id # Use user_id as the session_id
            
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Request data required'}), 400
            
            # The flask_session_id and upload_session_id are now just the session_id
            flask_session_id = session_id
            upload_session_id = session_id
            
            # Check job manager availability - if disabled, return mock response
            logger.info(f"Job manager available: {app.job_manager is not None}")
            if not app.job_manager:
                import uuid
                mock_job_id = f"mock_{str(uuid.uuid4())[:8]}"
                return jsonify({
                    'success': True,
                    'job_id': mock_job_id,
                    'message': 'Job manager temporarily disabled - mock job created',
                    'status': {
                        'job_id': mock_job_id,
                        'status': 'pending',
                        'progress': 0,
                        'message': 'Job manager temporarily disabled'
                    },
                    'mode': 'mock'
                }), 200
            
            # Get request data
            logger.info("Getting request data...")
            data = request.get_json()
            logger.info(f"Request data parsed: {data}")
            if not data:
                return jsonify({'error': 'Request data required'}), 400
            
            # Extract job parameters
            table_type = data.get('table_type', 'company')  # 'company' or 'people'
            processing_mode = data.get('processing_mode', 'webhook')  # 'webhook' or 'download'
            webhook_url = data.get('webhook_url')
            webhook_rate_limit = int(data.get('webhook_rate_limit', 10))
            webhook_limit = int(data.get('webhook_limit', 0))  # 0 = no limit
            logger.info(f"Job parameters - table_type: {table_type}, mode: {processing_mode}, webhook: {webhook_url}, limit: {webhook_limit}")
            
            # Validate processing mode requirements
            if processing_mode == 'webhook' and not webhook_url:
                return jsonify({'error': 'Webhook URL required for webhook processing mode'}), 400
            
            # Get session file list (from upload session)
            logger.info("Getting uploaded files from upload session...")
            logger.info(f"Looking for files in session: {upload_session_id}")
            if app.session_manager and upload_session_id:
                logger.info("Using session manager to get files from upload session")
                session_info = app.session_manager.get_session(upload_session_id)
                logger.info(f"Upload session info: {session_info}")
                if session_info:
                    logger.info(f"Session files_uploaded: {session_info.files_uploaded}")
                    logger.info(f"Session storage_used_bytes: {session_info.storage_used_bytes}")
                
                if not session_info:
                    logger.error(f"Session not found: {upload_session_id}")
                    return jsonify({'error': 'Session not found'}), 400
                elif session_info.files_uploaded == 0:
                    logger.error(f"No files uploaded - files_uploaded count is 0")
                    # Let's also check the raw files list to see if there's a mismatch
                    raw_files = app.session_manager.get_session_files(upload_session_id)
                    logger.error(f"But raw files list shows: {len(raw_files)} files: {raw_files}")
                    return jsonify({'error': 'No files uploaded for processing'}), 400
                
                # Get files using the correct method
                uploaded_files = app.session_manager.get_session_files(upload_session_id)
                logger.info(f"Uploaded files from session manager: {len(uploaded_files)} files")
                logger.info(f"File details: {uploaded_files}")
            else:
                logger.error(f"Session manager not available ({app.session_manager is not None}) or no upload session ID ({upload_session_id})")
                return jsonify({'error': 'No files uploaded for processing'}), 400
            
            # Prepare job data
            job_data = {
                'session_id': flask_session_id,  # Use Flask session for job history
                'table_type': table_type,
                'processing_mode': processing_mode,
                'webhook_url': webhook_url,
                'webhook_rate_limit': webhook_rate_limit,
                'webhook_limit': webhook_limit,
                'files': uploaded_files,
                'created_by': request.remote_addr,
                'user_agent': request.headers.get('User-Agent')
            }
            
            # Submit job to queue with fallback to synchronous processing
            logger.info(f"Submitting job with data: {job_data}")
            try:
                logger.info("Attempting to enqueue job...")
                job_id = app.job_manager.enqueue_job(job_data)
                logger.info(f"Job enqueued successfully with ID: {job_id}")
                
                # Get initial job status
                logger.info("Getting initial job status...")
                job_status = app.job_manager.get_job_status(job_id, flask_session_id)
                logger.info(f"Job status: {job_status}")
                
                return jsonify({
                    'success': True,
                    'job_id': job_id,
                    'message': 'Job submitted successfully',
                    'status': job_status,
                    'websocket_events': [
                        'job_progress',
                        'job_status_change'
                    ]
                }), 201
                
            except Exception as e:
                # Fall back to synchronous processing due to RQ/UTF-8 issue
                import uuid
                from src.csv_processor import CSVProcessor
                
                sync_job_id = f"sync_{str(uuid.uuid4())[:8]}"
                logger.warning(f"RQ error ({str(e)}), processing synchronously: {sync_job_id}")
                
                try:
                    # Process synchronously with better error handling
                    logger.info(f"Starting synchronous processing for {len(uploaded_files)} files")
                    logger.info(f"Uploaded files: {uploaded_files}")
                    
                    logger.info("Creating CSV processor...")
                    try:
                        # Create a simple progress callback for synchronous processing
                        def sync_progress_callback(*args, **kwargs):
                            """Progress callback for synchronous jobs"""
                            message = kwargs.get('message', 'Processing...')
                            logger.info(f"Sync progress for {sync_job_id}: {message} | args: {args} | kwargs: {kwargs}")
                            
                            # SIMPLE: Use user's name for progress updates
                            user_name = session.get('user_id', 'anonymous')
                            
                            # Emit to both job room and user room
                            socketio.emit('job_progress', {
                                'job_id': sync_job_id,
                                **kwargs
                            }, room=f"job_{sync_job_id}")
                            
                            # Also emit to user room
                            socketio.emit('job_progress', {
                                'job_id': sync_job_id,
                                **kwargs
                            }, room=f"session_{user_name}")
                            
                            socketio.sleep(0.1)
                        
                        # Use the updated CSV processor with three-phase processing
                        from src.csv_processor import CSVProcessor
                        processor = CSVProcessor(app.config_manager, sync_progress_callback, session_manager=app.session_manager)
                        logger.info("CSV processor created successfully")
                    except Exception as e:
                        logger.error(f"Failed to create CSV processor: {e}")
                        raise Exception(f"CSV processor creation failed: {e}")
                    
                    file_paths = [f['path'] for f in uploaded_files]
                    logger.info(f"File paths to process: {file_paths}")
                    
                    # Verify files exist
                    for file_path in file_paths:
                        if not os.path.exists(file_path):
                            logger.error(f"File not found: {file_path}")
                            raise FileNotFoundError(f"File not found: {file_path}")
                        logger.info(f"File exists: {file_path} ({os.path.getsize(file_path)} bytes)")
                    
                    # Add timeout and memory monitoring for large datasets
                    import signal
                    import resource
                    
                    # Set memory limit (1GB) to prevent system crashes
                    try:
                        resource.setrlimit(resource.RLIMIT_AS, (1024*1024*1024, 1024*1024*1024))
                    except:
                        pass  # Ignore if cannot set limit
                    
                    logger.info("Calling process_files with n8n header mapping...")
                    try:
                        # Use the actual CSVProcessor with n8n mapping
                        logger.info("🔍 Using CSVProcessor with n8n header mapping...")
                        
                        # Get file paths from session
                        file_paths = [file_info['path'] for file_info in uploaded_files]
                        logger.info(f"File paths: {file_paths}")
                        
                        # Check if files exist
                        for file_path in file_paths:
                            if not os.path.exists(file_path):
                                logger.error(f"File does not exist: {file_path}")
                                raise FileNotFoundError(f"File not found: {file_path}")
                            logger.info(f"File exists: {file_path}")
                        
                        # Create event loop for async processing
                        try:
                            loop = asyncio.get_event_loop()
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                        
                        # Process files asynchronously (for n8n mapping)
                        result_df, export_path, n8n_response = loop.run_until_complete(
                            processor.process_files(file_paths, table_type, upload_session_id)
                        )
                        logger.info(f"Processing completed. Result shape: {result_df.shape}, Export path: {export_path}")
                        
                        logger.info("n8n-based CSV processing completed successfully")
                        
                    except Exception as e:
                        logger.error(f"n8n-based CSV processing failed: {e}")
                        logger.error(f"Exception type: {type(e).__name__}")
                        import traceback
                        logger.error(f"Full traceback: {traceback.format_exc()}")
                        raise
                    
                    # Use the export path from process_files
                    result_path = export_path
                    
                    # Handle webhook processing if needed
                    logger.info(f"DEBUG: processing_mode = '{processing_mode}', webhook_url = '{webhook_url}', webhook_limit = {webhook_limit}")
                    # Extra debug before webhook block
                    logger.info(f"WEBHOOK DEBUG: About to process webhooks. processing_mode={processing_mode}, webhook_url={webhook_url}, webhook_limit={webhook_limit}")
                    logger.info(f"WEBHOOK DEBUG: result_df shape={result_df.shape}, records preview={result_df.to_dict('records')[:1]}")
                    if processing_mode == 'webhook' and webhook_url:
                        logger.info(f"Starting webhook delivery for {len(result_df)} records (limit: {webhook_limit})")
                        try:
                            from src.webhook_sender import WebhookSender, WebhookConfig
                            # Apply webhook limit if specified
                            records = result_df.to_dict('records')
                            if webhook_limit > 0 and len(records) > webhook_limit:
                                records = records[:webhook_limit]
                                logger.info(f"Webhook limit applied: sending {webhook_limit} records out of {len(result_df)} total")
                            # Initialize webhook sender
                            webhook_config = WebhookConfig(webhook_url, webhook_rate_limit)
                            webhook_sender = WebhookSender(webhook_config, sync_progress_callback)
                            # Send records
                            webhook_results = webhook_sender.send_records_sync(records)
                            logger.info(f"WEBHOOK DEBUG: webhook_results={webhook_results}")
                            logger.info(f"Webhook delivery completed: {webhook_results.get('success_rate', 0):.1f}% success rate")
                            
                            # Update job results with webhook info
                            job_results = {
                                'webhook_status': 'completed',
                                'webhook_results': webhook_results,
                                'webhook_success_rate': webhook_results.get('success_rate', 0),
                                'webhook_failed_records': webhook_results.get('failed_records', 0),
                                'webhook_limit_applied': webhook_limit if webhook_limit > 0 else None,
                                'webhook_records_sent': len(records),
                                'webhook_total_available': len(result_df),
                                'download_info': {
                                    'file_path': result_path,
                                    'filename': os.path.basename(result_path),
                                    'stats': {
                                        'total_records': len(result_df) if hasattr(result_df, '__len__') else 0,
                                        'duplicates_removed': 0,
                                        'processing_time_seconds': 0
                                    }
                                },
                                'processing_stats': {
                                    'total_records': len(result_df) if hasattr(result_df, '__len__') else 0,
                                    'duplicates_removed': 0,
                                    'files_processed': len(uploaded_files)
                                }
                            }
                            
                        except Exception as webhook_error:
                            logger.error(f"Webhook delivery failed: {webhook_error}")
                            # Continue with download info only
                            job_results = {
                                'webhook_status': 'failed',
                                'webhook_error': str(webhook_error),
                                'download_info': {
                                    'file_path': result_path,
                                    'filename': os.path.basename(result_path),
                                    'stats': {
                                        'total_records': len(result_df) if hasattr(result_df, '__len__') else 0,
                                        'duplicates_removed': 0,
                                        'processing_time_seconds': 0
                                    }
                                },
                                'processing_stats': {
                                    'total_records': len(result_df) if hasattr(result_df, '__len__') else 0,
                                    'duplicates_removed': 0,
                                    'files_processed': len(uploaded_files)
                                }
                            }
                    else:
                        # Download mode - use original job results structure
                        logger.info(f"DEBUG: Using download mode job results structure")
                        job_results = {
                            'download_info': {
                                'file_path': result_path,
                                'filename': os.path.basename(result_path),
                                'stats': {
                                    'total_records': len(result_df) if hasattr(result_df, '__len__') else 0,
                                    'duplicates_removed': 0,
                                    'processing_time_seconds': 0
                                }
                            },
                            'processing_stats': {
                                'total_records': len(result_df) if hasattr(result_df, '__len__') else 0,
                                'duplicates_removed': 0,
                                'files_processed': len(uploaded_files)
                            }
                        }
                    
                    logger.info(f"About to store job {sync_job_id} in job manager...")
                    
                    # Store job information in job manager for download access
                    logger.info(f"Job manager available: {app.job_manager is not None}")
                    if app.job_manager:
                        # SIMPLE: Use user_id (user's name) as the ONLY session identifier
                        user_name = session.get('user_id', 'anonymous')
                        
                        logger.info(f"Storing job {sync_job_id} under user: {user_name}")
                        
                        # Create job metadata
                        job_metadata = {
                            'session_id': user_name,  # Use user name as session
                            'user_id': user_name,  # Same as session
                            'table_type': table_type,
                            'processing_mode': processing_mode,
                            'webhook_url': webhook_url,
                            'webhook_rate_limit': webhook_rate_limit,
                            'webhook_limit': webhook_limit,
                            'files': uploaded_files,
                            'created_by': request.remote_addr,
                            'user_agent': request.headers.get('User-Agent'),
                            'created_at': datetime.now(timezone.utc).isoformat(),
                            'completed_at': datetime.now(timezone.utc).isoformat(),
                            'status': 'completed',
                            'progress': 100,
                            'result_path': export_path,
                            'stats': processor.get_processing_stats(),
                            'message': 'Processing completed successfully'
                        }
                        
                        # Store job metadata using user name as session
                        app.job_manager._store_job_metadata(sync_job_id, user_name, job_metadata)
                        app.job_manager._add_job_to_session(user_name, sync_job_id)
                        
                        # job_results is now defined above based on processing mode
                        
                        # Store job results using user name
                        job_results_key = f"job_results:{user_name}:{sync_job_id}"
                        app.job_manager.redis.setex(job_results_key, app.job_manager.session_ttl, json.dumps(job_results))
                        
                        logger.info(f"Stored synchronous job {sync_job_id} in job manager for download access")
                    else:
                        logger.warning(f"Job manager not available, cannot store job {sync_job_id} for download access")
                    
                    return jsonify({
                        'success': True,
                        'job_id': sync_job_id,
                        'message': 'Job processed synchronously (RQ workaround)',
                        'status': {
                            'job_id': sync_job_id,
                            'status': 'completed',
                            'progress': 100,
                            'message': 'Processing completed synchronously',
                            'result_path': export_path,
                            'records_processed': len(result_df) if hasattr(result_df, '__len__') else 0,
                            'stats': processor.get_processing_stats(),
                            'n8n_response': n8n_response
                        },
                        'mode': 'synchronous'
                    }), 201
                    
                except Exception as sync_error:
                    logger.error(f"REAL ERROR: {sync_error}")
                    logger.error(f"REAL ERROR TYPE: {type(sync_error).__name__}")
                    import traceback
                    logger.error(f"REAL TRACEBACK: {traceback.format_exc()}")
                    return jsonify({
                        'error': f'REAL ERROR: {str(sync_error)} (Type: {type(sync_error).__name__})'
                    }), 500
        
        except Exception as e:
            logger.error(f"Job submission error: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/jobs')
    def get_session_jobs():
        """Get all jobs for current session"""
        try:
            if not app.job_manager:
                return jsonify({'error': 'Job manager not available'}), 503
            
            session_id = session.get('session_id')
            if not session_id:
                return jsonify({'error': 'Session not found'}), 400
            
            # Get all jobs for session
            jobs = app.job_manager.get_session_jobs(session_id)
            
            return jsonify({
                'jobs': jobs,
                'session_id': session_id,
                'total_jobs': len(jobs)
            })
        
        except Exception as e:
            logger.error(f"Get session jobs error: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/jobs/<job_id>/status')
    def get_job_status(job_id):
        """Get job status"""
        try:
            if not app.job_manager:
                return jsonify({'error': 'Job manager not available'}), 503
            
            session_id = session.get('session_id')
            if not session_id:
                return jsonify({'error': 'Session not found'}), 400
            
            # Get job status
            status = app.job_manager.get_job_status(job_id, session_id)
            return jsonify(status)
        
        except ValueError as e:
            return jsonify({'error': str(e)}), 404
        except Exception as e:
            logger.error(f"Status check error: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/jobs/<job_id>/cancel', methods=['POST'])
    def cancel_job(job_id):
        """Cancel a running job"""
        try:
            if not app.job_manager:
                return jsonify({'error': 'Job manager not available'}), 503
            
            session_id = session.get('session_id')
            if not session_id:
                return jsonify({'error': 'Session not found'}), 400
            
            # Cancel job
            success = app.job_manager.cancel_job(job_id, session_id)
            
            if success:
                return jsonify({'success': True, 'message': 'Job cancelled successfully'})
            else:
                return jsonify({'error': 'Job not found or cannot be cancelled'}), 404
        
        except Exception as e:
            logger.error(f"Job cancellation error: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/jobs/<job_id>/rate', methods=['PUT'])
    def update_job_rate(job_id):
        """Update job webhook rate limit"""
        try:
            if not app.job_manager:
                return jsonify({'error': 'Job manager not available'}), 503
            
            session_id = session.get('session_id')
            if not session_id:
                return jsonify({'error': 'Session not found'}), 400
            
            data = request.get_json()
            new_rate_limit = data.get('rate_limit')
            
            if not isinstance(new_rate_limit, int) or new_rate_limit < 1:
                return jsonify({'error': 'Invalid rate limit'}), 400
            
            # Update rate limit
            success = app.job_manager.update_webhook_rate(job_id, session_id, new_rate_limit)
            
            if success:
                return jsonify({'success': True, 'new_rate_limit': new_rate_limit})
            else:
                return jsonify({'error': 'Failed to update rate limit'}), 404
        
        except Exception as e:
            logger.error(f"Rate update error: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/jobs/<job_id>/download')
    def download_csv(job_id):
        """Enhanced CSV download with session validation and proper headers"""
        try:
            logger.info(f"=== DOWNLOAD REQUEST DEBUG for job_id: {job_id} ===")
            
            user_id = session.get('user_id')
            logger.info(f"User ID from session: {user_id}")
            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401
            
            session_id = user_id # Use user_id as the session_id
            logger.info(f"Session ID set to: {session_id}")
            
            # For sync jobs, try direct Redis lookup first
            if job_id.startswith('sync_'):
                logger.info(f"Detected sync job, attempting direct lookup...")
                return handle_sync_job_download(job_id, session_id)
            
            # For regular RQ jobs, use the job manager
            if not validate_session_id(session_id):
                logger.error(f"Session validation failed for: {session_id}")
                return jsonify({'error': 'Invalid or expired session'}), 401
                
            # Validate job manager availability
            if not app.job_manager:
                return jsonify({'error': 'Job manager not available'}), 503
            
            logger.info(f"About to verify job access for job_id: {job_id}, session_id: {session_id}")
            
            # Debug: Check what's actually in Redis for this session
            try:
                session_jobs_key = f"session:{session_id}:jobs"
                all_jobs = app.job_manager.redis.smembers(session_jobs_key)
                logger.info(f"All jobs in session {session_id}: {all_jobs}")
                
                # Check if job metadata exists
                job_metadata_key = f"job:{session_id}:{job_id}"
                metadata_exists = app.job_manager.redis.exists(job_metadata_key)
                logger.info(f"Job metadata exists at {job_metadata_key}: {metadata_exists}")
                
                if metadata_exists:
                    metadata = app.job_manager.redis.get(job_metadata_key)
                    logger.info(f"Job metadata: {metadata}")
                
                # Check job results
                job_results_key = f"job_results:{session_id}:{job_id}"
                results_exist = app.job_manager.redis.exists(job_results_key)
                logger.info(f"Job results exist at {job_results_key}: {results_exist}")
                
            except Exception as debug_e:
                logger.error(f"Debug info gathering failed: {debug_e}")
                
            # Verify job access and get job status
            if not app.job_manager._verify_job_access(job_id, session_id):
                logger.error(f"Job access verification FAILED for job_id: {job_id}, session_id: {session_id}")
                return jsonify({'error': 'Job not found or access denied'}), 404
            
            logger.info(f"Job access verification PASSED")
                
            # Get detailed job status
            logger.info(f"Getting job status...")
            job_status = app.job_manager.get_job_status(job_id, session_id)
            
            # Check if job is completed
            if job_status.get('status') != 'completed':
                return jsonify({
                    'error': 'Job not completed yet',
                    'current_status': job_status.get('status'),
                    'message': 'CSV download is only available for completed jobs'
                }), 400
                
            # Get download info from job results
            results = job_status.get('results', {})
            download_info = results.get('download_info')
            
            # For sync jobs, also check if result_path is directly in job_status
            if not download_info and job_status.get('result_path'):
                download_info = {
                    'file_path': job_status.get('result_path'),
                    'filename': os.path.basename(job_status.get('result_path')),
                    'stats': job_status.get('progress', {}).get('stats', {})
                }
                logger.info(f"Using result_path from job_status for download: {download_info}")
            
            if not download_info:
                logger.error(f"No download info found. job_status keys: {list(job_status.keys())}")
                logger.error(f"results keys: {list(results.keys()) if results else 'No results'}")
                return jsonify({'error': 'Download information not found'}), 404
                
            # Validate file exists and is accessible
            file_path = download_info.get('file_path')
            if not file_path or not os.path.exists(file_path):
                return jsonify({'error': 'CSV file not found or has been cleaned up'}), 404
                
            return send_csv_file(file_path, download_info)
            
        except Exception as e:
            logger.error(f"Download error for job {job_id}: {e}", exc_info=True)
            return jsonify({'error': 'Download failed', 'details': str(e)}), 500


    def handle_sync_job_download(job_id: str, session_id: str):
        """Handle download for synchronous jobs directly from Redis"""
        try:
            logger.info(f"=== SYNC JOB DOWNLOAD HANDLER ===")
            logger.info(f"Job ID: {job_id}, Session ID: {session_id}")
            
            # Check job metadata directly in Redis
            job_metadata_key = f"job:{session_id}:{job_id}"
            logger.info(f"Checking metadata key: {job_metadata_key}")
            
            job_metadata_raw = app.job_manager.redis.get(job_metadata_key)
            if not job_metadata_raw:
                logger.error(f"No job metadata found at {job_metadata_key}")
                return jsonify({'error': 'Job not found'}), 404
            
            job_metadata = json.loads(job_metadata_raw)
            logger.info(f"Found job metadata: {job_metadata}")
            
            # Check if job is completed
            if job_metadata.get('status') != 'completed':
                return jsonify({
                    'error': 'Job not completed yet',
                    'current_status': job_metadata.get('status'),
                    'message': 'CSV download is only available for completed jobs'
                }), 400
            
            # Get job results
            job_results_key = f"job_results:{session_id}:{job_id}"
            logger.info(f"Checking results key: {job_results_key}")
            
            job_results_raw = app.job_manager.redis.get(job_results_key)
            if job_results_raw:
                job_results = json.loads(job_results_raw)
                logger.info(f"Found job results: {list(job_results.keys())}")
                
                # Try to get download info from results
                download_info = job_results.get('download_info')
                if download_info:
                    file_path = download_info.get('file_path')
                    logger.info(f"Found file path in download_info: {file_path}")
                else:
                    logger.info("No download_info in results")
            else:
                logger.info("No job results found")
                job_results = {}
                download_info = None
            
            # Fallback to result_path from metadata
            if not download_info:
                result_path = job_metadata.get('result_path')
                if result_path:
                    download_info = {
                        'file_path': result_path,
                        'filename': os.path.basename(result_path),
                        'stats': job_metadata.get('stats', {})
                    }
                    logger.info(f"Using result_path from metadata: {result_path}")
                else:
                    logger.error("No file path found in either results or metadata")
                    return jsonify({'error': 'Download file path not found'}), 404
            
            # Validate file exists
            file_path = download_info.get('file_path')
            if not file_path or not os.path.exists(file_path):
                logger.error(f"File not found at path: {file_path}")
                return jsonify({'error': 'CSV file not found or has been cleaned up'}), 404
            
            logger.info(f"File exists at: {file_path}")
            return send_csv_file(file_path, download_info)
            
        except Exception as e:
            logger.error(f"Error in sync job download handler: {e}", exc_info=True)
            return jsonify({'error': 'Sync job download failed', 'details': str(e)}), 500


    def send_csv_file(file_path: str, download_info: dict):
        """Send CSV file with proper headers"""
        try:
            # Generate secure filename for download
            original_filename = download_info.get('filename', 'merged_data.csv')
            safe_filename = clean_filename(original_filename)
            
            # Add timestamp to filename if not present
            if not any(char.isdigit() for char in safe_filename.split('.')[0][-10:]):
                name_part, ext = os.path.splitext(safe_filename)
                timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
                safe_filename = f"{name_part}_{timestamp}{ext}"
                
            # Get file info for headers
            file_size = os.path.getsize(file_path)
            file_stats = download_info.get('stats', {})

            # Prepare headers for CSV download
            headers = {
                'Content-Type': 'text/csv; charset=utf-8',
                'Content-Disposition': f'attachment; filename="{safe_filename}"',
                'Content-Length': str(file_size),
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
                'X-CSV-Records': str(file_stats.get('total_records', 0)),
                'X-CSV-Deduplicated': str(file_stats.get('duplicates_removed', 0))
            }
            
            logger.info(f"Sending CSV file: {safe_filename} ({file_size} bytes)")
            
            return send_file(
                file_path,
                as_attachment=True,
                download_name=safe_filename,
                mimetype='text/csv'
            )
                
        except Exception as e:
            logger.error(f"Error sending CSV file: {e}", exc_info=True)
            return jsonify({'error': 'Failed to send file', 'details': str(e)}), 500

    @app.route('/api/webhook/test', methods=['POST'])
    def test_webhook():
        """Test webhook endpoint connectivity"""
        try:
            data = request.get_json()
            webhook_url = data.get('webhook_url')
            
            if not webhook_url:
                return jsonify({'error': 'Webhook URL required'}), 400
            
            # Create test payload
            test_payload = {
                'test': True,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'message': 'CSV Merger webhook test',
                'sample_record': {
                    'company_name': 'Test Company',
                    'domain': 'example.com',
                    'industry': 'Technology'
                }
            }
            
            # Test webhook delivery
            try:
                import requests
                response = requests.post(
                    webhook_url,
                    json=test_payload,
                    timeout=10,
                    headers={'Content-Type': 'application/json'}
                )
                
                return jsonify({
                    'success': True,
                    'status_code': response.status_code,
                    'response_time_ms': int(response.elapsed.total_seconds() * 1000),
                    'response_headers': dict(response.headers),
                    'webhook_url': webhook_url
                })
                
            except requests.exceptions.Timeout:
                return jsonify({
                    'success': False,
                    'error': 'Webhook request timed out (10s)',
                    'webhook_url': webhook_url
                }), 408
                
            except requests.exceptions.ConnectionError:
                return jsonify({
                    'success': False,
                    'error': 'Could not connect to webhook URL',
                    'webhook_url': webhook_url
                }), 502
                
            except requests.exceptions.RequestException as e:
                return jsonify({
                    'success': False,
                    'error': f'Webhook request failed: {str(e)}',
                    'webhook_url': webhook_url
                }), 502
        
        except Exception as e:
            logger.error(f"Webhook test error: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/webhook/test-n8n', methods=['POST'])
    def test_n8n_webhook():
        """Test n8n webhook endpoint connectivity"""
        try:
            from src.header_mapper import N8NHeaderMapper
            
            # Create header mapper instance
            header_mapper = N8NHeaderMapper()
            
            # Test webhook connectivity
            is_accessible = header_mapper.validate_webhook_url()
            
            if is_accessible:
                return jsonify({
                    'success': True,
                    'message': 'n8n webhook is accessible',
                    'webhook_url': header_mapper.webhook_url
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'n8n webhook is not accessible',
                    'webhook_url': header_mapper.webhook_url
                }), 502
                
        except Exception as e:
            logger.error(f"n8n webhook test error: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    # SocketIO event handlers
    @socketio.on('connect')
    def handle_connect():
        """Handle WebSocket connections"""
        user_id = session.get('user_id')
        if not user_id:
            logger.warning(f"Socket connected without authenticated user. SID: {request.sid}")
            # Don't reject the connection, just emit a warning
            emit('connection_status', {
                'authenticated': False, 
                'message': 'User not authenticated. Please log in.',
                'session_id': None,
                'user_id': None
            })
            return

        session_id = user_id
        join_room(f"session_{session_id}")
        logger.info(f"User '{user_id}' connected via WebSocket. SID: {request.sid}. Joined room: session_{session_id}")
        emit('connected', {'session_id': session_id, 'user_id': user_id})
        emit('connection_status', {
            'authenticated': True,
            'message': 'Connected successfully',
            'session_id': session_id,
            'user_id': user_id
        })

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection"""
        user_id = session.get('user_id')
        if user_id:
            session_id = user_id
            leave_room(f"session_{session_id}")
            logger.info(f"User '{user_id}' disconnected from WebSocket. SID: {request.sid}. Left room: session_{session_id}")

    @socketio.on('ping')
    def handle_ping():
        """Handle ping requests"""
        emit('pong', {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'server_status': 'healthy'
        })

    @socketio.on('join_job')
    def handle_join_job(data):
        """Join job room for progress updates"""
        job_id = data.get('job_id')
        session_id = session.get('session_id')
        
        if job_id and session_id:
            join_room(f"job_{job_id}")
            emit('job_joined', {'job_id': job_id})
            logger.debug(f"Client joined job room: {job_id}")

    @socketio.on('leave_job')
    def handle_leave_job(data):
        """Leave job room"""
        job_id = data.get('job_id')
        if job_id:
            leave_room(f"job_{job_id}")
            emit('job_left', {'job_id': job_id})

    @socketio.on('get_session_jobs')
    def handle_get_session_jobs():
        """Get jobs for current user"""
        user_id = session.get('user_id')
        if not user_id:
            logger.warning(f"get_session_jobs requested without authenticated user.")
            emit('session_jobs', {'jobs': [], 'error': 'Not authenticated'})
            return
        
        session_id = user_id
        if app.job_manager:
            try:
                completed_jobs = app.job_manager.get_completed_jobs(session_id)
                logger.info(f"Found {len(completed_jobs)} jobs for user {user_id}")
                emit('session_jobs', {'jobs': completed_jobs})
            except Exception as e:
                logger.error(f"Failed to get jobs for user {user_id}: {e}", exc_info=True)
                emit('error', {'message': f'Failed to get jobs: {str(e)}'})
        else:
            emit('session_jobs', {'jobs': [], 'message': 'Job manager temporarily disabled'})

    @socketio.on('get_job_status')
    def handle_get_job_status(data):
        """Get status of specific job"""
        job_id = data.get('job_id')
        session_id = session.get('session_id')
        
        if not job_id or not session_id:
            emit('error', {'message': 'Job ID and session required'})
            return
        
        if app.job_manager:
            try:
                status = app.job_manager.get_job_status(job_id, session_id)
                emit('job_status', status)
            except Exception as e:
                emit('error', {'message': f'Failed to get job status: {str(e)}'})
        else:
            # Return mock status when job manager is disabled
            emit('job_status', {
                'job_id': job_id,
                'status': 'not_available',
                'message': 'Job manager temporarily disabled'
            })

    logger.info("create_app() completed successfully - returning app and socketio")
    return app, socketio

def clean_filename(filename: str) -> str:
    """Clean filename for security"""
    import re
    # Remove path components and dangerous characters
    filename = os.path.basename(filename)
    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    return filename

# Create the application
app, socketio = create_app()

# Make app available for gunicorn
# gunicorn will import this module and look for 'app'
application = app

if __name__ == '__main__':
    logger = logging.getLogger(__name__)
    logger.info("Starting CSV Merger Application")
    
    # Start the application
    if Config.IS_PRODUCTION:
        # Production mode with eventlet
        socketio.run(
            app,
            host=Config.FLASK_HOST,
            port=Config.FLASK_PORT,
            debug=False,
            use_reloader=False
        )
    else:
        # Development mode
        socketio.run(
            app,
            host=Config.FLASK_HOST,
            port=Config.FLASK_PORT,
            debug=Config.FLASK_DEBUG,
            use_reloader=False  # Disable reloader to fix startup issues
        ) 