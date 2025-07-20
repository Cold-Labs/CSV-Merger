#!/usr/bin/env python3
"""
CSV Merger - Main Flask Application
Professional lead processing for cold email agencies
"""

import os
import sys
import logging
from datetime import datetime, timezone
from functools import wraps

import redis
from flask import Flask, render_template, request, jsonify, session, send_file
from flask_socketio import SocketIO, emit, join_room, leave_room
import eventlet

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config.settings import Config
from src.session_manager import SessionManager
from src.queue_manager import JobManager
from src.config_manager import ConfigManager

# Configure eventlet for async operations
eventlet.monkey_patch()

# Configure logging
def setup_logging():
    """Setup logging configuration for production and development"""
    Config.create_directories()
    
    # Configure root logger
    log_config = Config.get_logging_config()
    
    # Setup formatters
    formatter = logging.Formatter(log_config['format'])
    
    # Setup handlers
    handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)
    
    # File handler for production
    if Config.IS_PRODUCTION:
        file_handler = logging.handlers.RotatingFileHandler(
            filename=os.path.join(Config.LOG_DIR, 'app.log'),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL),
        handlers=handlers,
        format=Config.LOG_FORMAT
    )
    
    # Set specific logger levels
    logging.getLogger('werkzeug').setLevel(logging.WARNING if Config.IS_PRODUCTION else logging.INFO)
    logging.getLogger('socketio').setLevel(logging.WARNING if Config.IS_PRODUCTION else logging.INFO)
    logging.getLogger('engineio').setLevel(logging.WARNING if Config.IS_PRODUCTION else logging.INFO)

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
    
    # Initialize Redis connection
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
        logger.info("Redis connection established")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        if Config.IS_PRODUCTION:
            raise
        redis_client = None
    
    # Initialize managers
    config_manager = ConfigManager(Config.FIELD_MAPPINGS_FILE)
    session_manager = SessionManager(redis_client, Config) if redis_client else None
    job_manager = JobManager(redis_client, Config, socketio) if redis_client else None
    
    # Store managers in app context
    app.redis = redis_client
    app.config_manager = config_manager
    app.session_manager = session_manager
    app.job_manager = job_manager
    app.socketio = socketio
    
    # Set SocketIO reference in job manager for real-time updates
    if job_manager and socketio:
        job_manager.set_socketio(socketio)
    
    def validate_session_id(session_id: str) -> bool:
        """Validate session ID"""
        return session_manager.validate_session(session_id) if session_manager else True
    
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
            response.headers['Content-Security-Policy'] = "default-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://cdn.socket.io"
        
        return response

    # Health check endpoint
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
                    health_data['status'] = 'degraded'
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

    # Add all the existing routes here (file upload, jobs, etc.)
    @app.route('/api/upload', methods=['POST'])
    def upload_files():
        """Handle file upload and store in session"""
        try:
            # Validate session
            session_id = session.get('session_id')
            if not session_id or not validate_session_id(session_id):
                return jsonify({'error': 'Invalid or expired session'}), 401
            
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
                
                if file_size > config_instance.MAX_FILE_SIZE_BYTES:
                    return jsonify({'error': f'File {file.filename} exceeds maximum size limit'}), 400
                
                total_size += file_size
                
                # Store file using session manager
                file_info = app.session_manager.store_file(session_id, file, file.filename)
                uploaded_files.append(file_info)
            
            # Update session with uploaded files info
            session_info = app.session_manager.get_session(session_id)
            if session_info:
                session_info.files_uploaded = True
                session_info.uploaded_files = uploaded_files
                session_info.total_file_size = total_size
                app.session_manager._save_session(session_info)
            
            logger.info(f"Successfully uploaded {len(uploaded_files)} files for session {session_id}")
            
            return jsonify({
                'success': True,
                'message': f'Successfully uploaded {len(uploaded_files)} files',
                'files': uploaded_files,
                'total_size': total_size
            }), 200
        
        except Exception as e:
            logger.error(f"File upload error: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/jobs', methods=['POST'])
    def submit_job():
        """Submit a new CSV processing job"""
        try:
            # Validate session
            session_id = session.get('session_id')
            if not session_id or not validate_session_id(session_id):
                return jsonify({'error': 'Invalid or expired session'}), 401
            
            # Validate job manager availability
            if not app.job_manager:
                return jsonify({'error': 'Job manager not available'}), 503
            
            # Get request data
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Request data required'}), 400
            
            # Extract job parameters
            table_type = data.get('table_type', 'company')  # 'company' or 'people'
            processing_mode = data.get('processing_mode', 'webhook')  # 'webhook' or 'download'
            webhook_url = data.get('webhook_url')
            webhook_rate_limit = data.get('webhook_rate_limit', 10)
            
            # Validate processing mode requirements
            if processing_mode == 'webhook' and not webhook_url:
                return jsonify({'error': 'Webhook URL required for webhook processing mode'}), 400
            
            # Get session file list (assume files were already uploaded)
            if not app.session_manager:
                return jsonify({'error': 'Session manager not available'}), 503
            
            session_info = app.session_manager.get_session(session_id)
            if not session_info or not getattr(session_info, 'files_uploaded', False):
                return jsonify({'error': 'No files uploaded for processing'}), 400
            
            # Prepare job data
            job_data = {
                'session_id': session_id,
                'table_type': table_type,
                'processing_mode': processing_mode,
                'webhook_url': webhook_url,
                'webhook_rate_limit': webhook_rate_limit,
                'files': getattr(session_info, 'uploaded_files', []),
                'created_by': request.remote_addr,
                'user_agent': request.headers.get('User-Agent')
            }
            
            # Submit job to queue
            job_id = app.job_manager.enqueue_job(job_data)
            
            # Get initial job status
            job_status = app.job_manager.get_job_status(job_id, session_id)
            
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
            # Validate session
            session_id = session.get('session_id')
            if not session_id or not validate_session_id(session_id):
                return jsonify({'error': 'Invalid or expired session'}), 401
                
            # Validate job manager availability
            if not app.job_manager:
                return jsonify({'error': 'Job manager not available'}), 503
                
            # Verify job access and get job status
            if not app.job_manager._verify_job_access(job_id, session_id):
                return jsonify({'error': 'Job not found or access denied'}), 404
                
            # Get detailed job status
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
            
            if not download_info:
                return jsonify({'error': 'Download information not found'}), 404
                
            # Validate file exists and is accessible
            file_path = download_info.get('file_path')
            if not file_path or not os.path.exists(file_path):
                return jsonify({'error': 'CSV file not found or has been cleaned up'}), 404
                
            # Security check: ensure file is within upload directory
            upload_dir = os.path.abspath(Config.TEMP_UPLOAD_DIR)
            file_abs_path = os.path.abspath(file_path)
            if not file_abs_path.startswith(upload_dir):
                logger.warning(f"Security violation: attempted access to {file_path} outside upload directory")
                return jsonify({'error': 'Access denied'}), 403
                
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
                'X-CSV-Deduplicated': str(file_stats.get('duplicates_removed', 0)),
                'X-Processing-Time': str(job_status.get('processing_time_seconds', 0)),
                'X-Session-ID': session_id[:8] + '...'  # Partial session ID for tracking
            }
            
            logger.info(f"Starting CSV download: {safe_filename} ({file_size} bytes) for session {session_id}")
            
            # Send file with proper cleanup
            try:
                return send_file(
                    file_path,
                    as_attachment=True,
                    download_name=safe_filename,
                    mimetype='text/csv'
                ), 200, headers
                
            except Exception as e:
                logger.error(f"Error sending file {file_path}: {e}")
                return jsonify({'error': 'Failed to send file'}), 500
                
        except Exception as e:
            logger.error(f"Download error for job {job_id}: {e}", exc_info=True)
            return jsonify({'error': 'Download failed', 'details': str(e)}), 500

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

    # SocketIO event handlers
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection"""
        session_id = session.get('session_id')
        if session_id:
            join_room(f"session_{session_id}")
            emit('connected', {
                'session_id': session_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            logger.info(f"Client connected to session {session_id}")
        else:
            emit('error', {'message': 'No session found'})

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection"""
        session_id = session.get('session_id')
        if session_id:
            leave_room(f"session_{session_id}")
            logger.info(f"Client disconnected from session {session_id}")

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
        """Get jobs for current session"""
        session_id = session.get('session_id')
        if not session_id:
            emit('error', {'message': 'Session required'})
            return
        
        if app.job_manager:
            try:
                completed_jobs = app.job_manager.get_completed_jobs(session_id)
                emit('session_jobs', {'jobs': completed_jobs})
            except Exception as e:
                emit('error', {'message': f'Failed to get jobs: {str(e)}'})
        else:
            emit('error', {'message': 'Job manager not available'})

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
            emit('error', {'message': 'Job manager not available'})

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
            use_reloader=True
        ) 