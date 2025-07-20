import os
import uuid
import logging
from flask import Flask, render_template, request, jsonify, session
import redis
from config.settings import Config
from src.config_manager import ConfigManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_app():
    """Application factory pattern"""
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize Redis connection (optional for testing)
    try:
        redis_client = redis.from_url(app.config['REDIS_URL'])
        redis_client.ping()  # Test connection
        logger.info("Redis connection established")
    except redis.ConnectionError:
        logger.warning("Redis not available - continuing without it")
        redis_client = None
    
    # Initialize Configuration Manager
    config_manager = ConfigManager(app.config['FIELD_MAPPINGS_FILE'])
    
    # Store components in app context
    app.redis = redis_client
    app.config_manager = config_manager
    
    # Register routes
    register_routes(app)
    register_error_handlers(app)
    
    return app

def register_routes(app):
    """Register application routes"""
    
    @app.route('/')
    def index():
        """Main application page"""
        # Ensure user has session
        if 'session_id' not in session:
            session['session_id'] = str(uuid.uuid4())
            logger.info(f"New session created: {session['session_id']}")
        
        return render_template('index.html', session_id=session['session_id'])
    
    @app.route('/health')
    def health_check():
        """Health check endpoint for deployment"""
        status = {
            'status': 'healthy',
            'redis_connected': app.redis is not None,
            'config_loaded': app.config_manager.mappings is not None
        }
        
        # Test Redis connection
        if app.redis:
            try:
                app.redis.ping()
                status['redis_status'] = 'connected'
            except:
                status['redis_status'] = 'disconnected'
                status['status'] = 'degraded'
        else:
            status['redis_status'] = 'not_configured'
            status['status'] = 'degraded'
        
        return jsonify(status), 200 if status['status'] == 'healthy' else 503
    
    @app.route('/api/session', methods=['GET'])
    def get_session_info():
        """Get or create session information"""
        if 'session_id' not in session:
            session['session_id'] = str(uuid.uuid4())
        
        session_id = session['session_id']
        
        # Get session data from Redis
        session_data = {
            'session_id': session_id,
            'created_at': session.get('created_at'),
            'active_jobs': 0,  # Will be populated by queue manager
            'storage_used_mb': 0,  # Will be calculated by session manager
            'storage_limit_mb': app.config['MAX_STORAGE_PER_SESSION_MB'],
            'expires_at': None  # Will be calculated based on TTL
        }
        
        return jsonify(session_data)
    
    @app.route('/api/config/mappings', methods=['GET'])
    def get_field_mappings():
        """Get current field mappings"""
        try:
            mappings = {
                'company_mappings': app.config_manager.get_company_mappings(),
                'people_mappings': app.config_manager.get_people_mappings(),
                'data_cleaning_rules': app.config_manager.get_cleaning_rules(),
                'preview': app.config_manager.get_mapping_preview()
            }
            return jsonify({'status': 'success', 'data': mappings})
        except Exception as e:
            logger.error(f"Error getting field mappings: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

def register_error_handlers(app):
    """Register error handlers"""
    
    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 errors"""
        if request.path.startswith('/api/'):
            return jsonify({'status': 'error', 'message': 'Endpoint not found'}), 404
        return render_template('index.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 errors"""
        logger.error(f"Internal server error: {error}")
        if request.path.startswith('/api/'):
            return jsonify({'status': 'error', 'message': 'Internal server error'}), 500
        return render_template('index.html'), 500

# Create application instance
app = create_app()

if __name__ == '__main__':
    logger.info("Starting CSV Merger Application (Test Version)")
    app.run(debug=app.config['DEBUG'], host='0.0.0.0', port=5000) 