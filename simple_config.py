"""
Simple Configuration
Just the essentials - no complex settings
"""

import os


class Config:
    """Simple configuration class"""

    # Redis
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # n8n AI Mapping
    N8N_WEBHOOK_URL = os.getenv(
        "N8N_WEBHOOK_URL", "https://n8n.coldlabs.ai/webhook/csv-header-mapping"
    )

    # File handling
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
    ALLOWED_EXTENSIONS = {".csv"}

    # Processing
    DEFAULT_BATCH_SIZE = 100
    MAX_RETRIES = 3
    WEBHOOK_TIMEOUT = 30

    # Directories
    UPLOAD_DIR = "uploads"

    def __init__(self):
        # Ensure directories exist
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)
