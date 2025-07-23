"""
Centralized logging configuration for CSV Merger
"""

import os
import logging
import logging.handlers
from typing import Optional
from config.settings import Config

def setup_module_logger(module_name: str, log_file: Optional[str] = None) -> logging.Logger:
    """
    Setup a logger for a specific module
    
    Args:
        module_name: Name of the module (e.g., 'csv_processor', 'webhook_sender')
        log_file: Optional specific log file name, defaults to module_name.log
        
    Returns:
        Configured logger instance
    """
    # Ensure logs directory exists
    Config.create_directories()
    
    # Get logger
    logger = logging.getLogger(module_name)
    
    # Skip if logger is already configured
    if logger.handlers:
        return logger
    
    # Setup formatter
    formatter = logging.Formatter(Config.LOG_FORMAT)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler
    if log_file is None:
        log_file = f"{module_name.split('.')[-1]}.log"
    
    file_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(Config.LOG_DIR, log_file),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Set level
    logger.setLevel(getattr(logging, Config.LOG_LEVEL))
    
    return logger

def setup_app_logging():
    """Setup application-wide logging configuration"""
    # Ensure logs directory exists
    Config.create_directories()
    
    # Setup formatters
    formatter = logging.Formatter(Config.LOG_FORMAT)
    
    # Setup handlers
    handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)
    
    # File handlers for different components
    log_files = {
        'app': 'app.log',
        'server': 'server.log',
        'worker': 'worker.log',
        'debug': 'debug.log'
    }
    
    for name, filename in log_files.items():
        file_handler = logging.handlers.RotatingFileHandler(
            filename=os.path.join(Config.LOG_DIR, filename),
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
    
    # Redirect Flask's built-in server logs to server.log
    werkzeug_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(Config.LOG_DIR, 'server.log'),
        maxBytes=10 * 1024 * 1024,
        backupCount=5
    )
    werkzeug_handler.setFormatter(formatter)
    logging.getLogger('werkzeug').addHandler(werkzeug_handler) 