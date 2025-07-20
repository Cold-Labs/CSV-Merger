import os
from typing import Dict, Any

class Config:
    """Application configuration with environment variable support"""
    
    # Environment detection
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    IS_PRODUCTION = FLASK_ENV == 'production'
    IS_TESTING = FLASK_ENV == 'testing'
    
    # Redis Configuration
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
    REDIS_DB = int(os.getenv('REDIS_DB', '0'))
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')
    
    # Queue Configuration
    QUEUE_NAME = 'csv_processing'
    
    # Session Configuration
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    SESSION_TTL_SECONDS = int(os.getenv('SESSION_TTL_SECONDS', '172800'))  # 48 hours
    
    # File Upload Limits
    MAX_FILE_SIZE_MB = int(os.getenv('MAX_FILE_SIZE_MB', '20'))
    MAX_FILES_PER_SESSION = int(os.getenv('MAX_FILES_PER_SESSION', '10'))
    MAX_STORAGE_PER_SESSION_MB = int(os.getenv('MAX_STORAGE_PER_SESSION_MB', '200'))
    MAX_CONCURRENT_JOBS_PER_SESSION = int(os.getenv('MAX_CONCURRENT_JOBS_PER_SESSION', '3'))
    
    # Directory Configuration
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    TEMP_UPLOAD_DIR = os.getenv('TEMP_UPLOAD_DIR', os.path.join(BASE_DIR, 'temp_uploads'))
    EXPORT_DIR = os.getenv('EXPORT_DIR', os.path.join(BASE_DIR, 'exports'))
    CONFIG_DIR = os.getenv('CONFIG_DIR', os.path.join(BASE_DIR, 'config'))
    FIELD_MAPPINGS_FILE = os.path.join(CONFIG_DIR, 'field_mappings.json')
    LOG_DIR = os.getenv('LOG_DIR', os.path.join(BASE_DIR, 'logs'))
    
    # Webhook Configuration
    WEBHOOK_TIMEOUT = int(os.getenv('WEBHOOK_TIMEOUT', '30'))
    WEBHOOK_RETRY_ATTEMPTS = int(os.getenv('WEBHOOK_RETRY_ATTEMPTS', '3'))
    WEBHOOK_RETRY_DELAY = int(os.getenv('WEBHOOK_RETRY_DELAY', '1'))
    
    # Cleanup Configuration
    CLEANUP_INTERVAL_MINUTES = int(os.getenv('CLEANUP_INTERVAL_MINUTES', '60'))
    
    # Logging Configuration
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO' if IS_PRODUCTION else 'DEBUG')
    LOG_FORMAT = os.getenv('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Flask Configuration
    FLASK_HOST = os.getenv('FLASK_HOST', '0.0.0.0')
    FLASK_PORT = int(os.getenv('PORT', os.getenv('FLASK_PORT', '5001')))  # Railway uses PORT
    FLASK_DEBUG = not IS_PRODUCTION and not IS_TESTING
    
    # Security Configuration
    SECURE_HEADERS = IS_PRODUCTION
    
    # Worker Configuration
    WORKER_PROCESSES = int(os.getenv('WORKER_PROCESSES', '2'))
    
    @property
    def MAX_FILE_SIZE_BYTES(self) -> int:
        """Maximum file size in bytes"""
        return self.MAX_FILE_SIZE_MB * 1024 * 1024
    
    @property
    def MAX_STORAGE_PER_SESSION_BYTES(self) -> int:
        """Maximum storage per session in bytes"""
        return self.MAX_STORAGE_PER_SESSION_MB * 1024 * 1024
    
    @classmethod
    def get_redis_config(cls) -> Dict[str, Any]:
        """Get Redis connection configuration"""
        if cls.REDIS_URL:
            return {'connection_pool': cls.REDIS_URL}
        
        config = {
            'host': cls.REDIS_HOST,
            'port': cls.REDIS_PORT,
            'db': cls.REDIS_DB,
            'decode_responses': True,
            'socket_connect_timeout': 5,
            'socket_timeout': 5,
            'retry_on_timeout': True
        }
        
        if cls.REDIS_PASSWORD:
            config['password'] = cls.REDIS_PASSWORD
            
        return config
    
    @classmethod
    def validate_environment(cls) -> bool:
        """Validate that all required environment variables are set"""
        required_vars = []
        
        if cls.IS_PRODUCTION:
            required_vars.extend([
                'SECRET_KEY',
                'REDIS_URL'
            ])
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        return True
    
    @classmethod
    def create_directories(cls):
        """Create necessary directories if they don't exist"""
        directories = [
            cls.TEMP_UPLOAD_DIR,
            cls.EXPORT_DIR,
            cls.LOG_DIR,
            os.path.join(cls.TEMP_UPLOAD_DIR, 'redis-data')  # For Docker Redis data
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
    
    @classmethod
    def get_flask_config(cls) -> Dict[str, Any]:
        """Get Flask application configuration"""
        return {
            'SECRET_KEY': cls.SECRET_KEY,
            'MAX_CONTENT_LENGTH': cls.MAX_FILE_SIZE_BYTES,
            'UPLOAD_FOLDER': cls.TEMP_UPLOAD_DIR,
            'JSON_SORT_KEYS': False,
            'JSONIFY_PRETTYPRINT_REGULAR': not cls.IS_PRODUCTION,
            'TESTING': cls.IS_TESTING,
            'DEBUG': cls.FLASK_DEBUG
        }
    
    @classmethod
    def get_logging_config(cls) -> Dict[str, Any]:
        """Get logging configuration"""
        return {
            'level': cls.LOG_LEVEL,
            'format': cls.LOG_FORMAT,
            'handlers': {
                'file': {
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': os.path.join(cls.LOG_DIR, 'app.log'),
                    'maxBytes': 10 * 1024 * 1024,  # 10 MB
                    'backupCount': 5,
                    'formatter': 'default'
                },
                'console': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'default'
                }
            }
        } 