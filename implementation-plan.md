# CSV Merger Application - Implementation Plan

## Project Setup Tasks

### TASK-1: Project Structure and Dependencies
**Objective:** Create project foundation with proper structure and dependencies

**Implementation Steps:**
1. Create project directory structure:
   ```
   csv-merger/
   ├── app.py
   ├── requirements.txt
   ├── Dockerfile
   ├── railway.toml
   ├── .env.example
   ├── config/
   │   ├── __init__.py
   │   └── settings.py
   ├── src/
   │   ├── __init__.py
   │   ├── csv_processor.py
   │   ├── queue_manager.py
   │   ├── webhook_sender.py
   │   └── utils.py
   ├── static/
   │   ├── css/
   │   └── js/
   ├── templates/
   │   └── index.html
   ├── uploads/
   │   └── temp/
   └── tests/
   ```

2. Create `requirements.txt` with dependencies:
   ```
   Flask==3.0.0
   Flask-SocketIO==5.3.6
   pandas==2.1.4
   fuzzywuzzy==0.18.0
   python-Levenshtein==0.21.1
   redis==5.0.1
   rq==1.15.1
   requests==2.31.0
   python-dotenv==1.0.0
   gunicorn==21.2.0
   eventlet==0.33.3
   ```

3. Create basic `.env.example` file
4. Initialize Git repository and create `.gitignore`

### TASK-2: Configuration Management
**Objective:** Implement centralized configuration system

**Code to Write:**
- `config/settings.py` - Complete configuration class with all field mappings
- Environment variable loading
- Validation of required settings
- Easy configuration updates through file editing

**Key Features:**
- Company and people field mapping dictionaries
- Fuzzy matching thresholds  
- Webhook retry settings
- File upload limits

### TASK-3: Basic Flask Application Setup
**Objective:** Create minimal Flask app with routing structure

**Code to Write:**
- `app.py` - Main Flask application
- Basic routes: `/`, `/health`
- Flask-SocketIO initialization
- Error handlers for 404, 500
- CORS configuration if needed

## Core Backend Components

### TASK-4: CSV Processor Class
**Objective:** Implement CSV processing logic with fuzzy header matching

**Code to Write:**
```python
class CSVProcessor:
    def __init__(self, config):
        self.config = config
        self.field_mappings = config.get_field_mappings()
    
    def map_headers(self, csv_headers, table_type):
        """Use fuzzy matching to map CSV headers to standard names"""
        
    def merge_csv_files(self, file_paths, table_type):
        """Combine multiple CSV files into single DataFrame"""
        
    def deduplicate_records(self, df, table_type):
        """Remove duplicates based on configured criteria"""
        
    def validate_data(self, df):
        """Perform data quality checks"""
        
    def process_files(self, file_paths, table_type):
        """Main processing pipeline"""
```

**Implementation Details:**
- Use `fuzzywuzzy` for header similarity matching
- Implement pandas-based deduplication with smart data merging
- Domain cleaning and data normalization functions
- CSV export functionality for downloads
- Handle missing data and data type conversion
- Progress callback support for real-time updates

### TASK-5: Queue Manager
**Objective:** Implement Redis-based job queue management

**Code to Write:**
```python
class JobManager:
    def __init__(self, redis_connection):
        self.redis = redis_connection
        self.queue = Queue(connection=redis_connection)
    
    def enqueue_job(self, job_data):
        """Add CSV processing job to queue"""
        
    def get_job_status(self, job_id):
        """Retrieve current job status and progress"""
        
    def update_progress(self, job_id, progress_data):
        """Update job progress in Redis"""
        
    def mark_job_complete(self, job_id, results):
        """Mark job as completed with results"""
        
    def mark_job_failed(self, job_id, error):
        """Mark job as failed with error details"""
```

**Implementation Details:**
- RQ (Redis Queue) integration
- Job progress tracking in Redis
- Error handling and job failure management
- Job timeout configuration

### TASK-6: Webhook Sender
**Objective:** Implement reliable webhook delivery with retry logic

**Code to Write:**
```python
class WebhookSender:
    def __init__(self, config):
        self.config = config
        self.session = requests.Session()
    
    def send_record(self, record_data, webhook_url, table_type):
        """Send individual record to webhook with retry logic"""
        
    def format_payload(self, record_data, table_type):
        """Format record data according to JSON schema"""
        
    def retry_failed_webhooks(self, job_id):
        """Process failed webhook deliveries with exponential backoff"""
        
    def batch_send_records(self, records, webhook_url, table_type, job_id):
        """Send multiple records efficiently with progress updates"""
```

**Implementation Details:**
- Exponential backoff retry mechanism
- Request timeout handling
- Connection pooling for efficiency
- Failed delivery tracking in Redis
- Token bucket rate limiting algorithm
- Real-time rate adjustment capabilities
- Rate monitoring and statistics

### TASK-7: Background Worker
**Objective:** Create background worker process for CSV processing

**Code to Write:**
```python
def process_csv_job(job_data):
    """Background job function for processing CSV files"""
    # Initialize processor
    # Process files
    # Send webhooks
    # Update progress
    
def start_worker():
    """Start RQ worker process"""
```

**Implementation Details:**
- RQ worker setup
- Job progress reporting via Redis
- Error handling and logging
- Graceful shutdown handling

### TASK-8: Session Manager
**Objective:** Implement session-based multi-tenant functionality

**Code to Write:**
```python
class SessionManager:
    def __init__(self, redis_connection, config):
        self.redis = redis_connection
        self.config = config
    
    def create_session(self):
        """Generate unique session ID and initialize session data"""
        
    def get_session_workspace(self, session_id):
        """Get session-specific file directory"""
        
    def get_user_jobs(self, session_id):
        """List all jobs for current session"""
        
    def validate_session_limits(self, session_id):
        """Check if session is within resource limits"""
        
    def update_session_activity(self, session_id):
        """Update last activity timestamp"""
```

**Implementation Details:**
- UUID-based session generation
- Session-specific file directories
- Resource limit enforcement
- Redis-based session tracking with TTL

### TASK-9: Cleanup Manager
**Objective:** Implement automated cleanup for 48-hour data retention

**Code to Write:**
```python
class CleanupManager:
    def __init__(self, config):
        self.config = config
        
    def cleanup_expired_files(self):
        """Remove files older than 48 hours"""
        
    def cleanup_expired_jobs(self):
        """Clean up Redis job data past TTL"""
        
    def monitor_storage(self):
        """Track total storage usage"""
        
    def schedule_cleanup(self):
        """Run automated cleanup every hour"""
        
    def cleanup_session(self, session_id):
        """Clean up specific session data"""
```

**Implementation Details:**
- File system cleanup based on timestamps
- Redis TTL management
- Storage monitoring and alerts
- Scheduled cleanup with APScheduler
- Graceful cleanup during active jobs

### TASK-9a: Configuration Manager
**Objective:** Implement easy field mapping management and hot-reload capability

**Code to Write:**
```python
class ConfigManager:
    def __init__(self, config_file_path):
        self.config_file = config_file_path
        
    def load_field_mappings(self):
        """Load field mappings from JSON file"""
        
    def update_field_mappings(self, new_mappings):
        """Update mappings and hot-reload"""
        
    def validate_mappings(self, mappings):
        """Validate mapping structure and syntax"""
        
    def backup_config(self):
        """Create timestamped backup of current config"""
        
    def restore_config(self, backup_file):
        """Restore configuration from backup"""
        
    def get_mapping_preview(self):
        """Get current mappings for UI display"""
```

**Implementation Details:**
- JSON-based configuration file for easy editing
- File watcher for automatic hot-reload
- Configuration validation and error handling
- Backup/restore functionality with timestamps
- API endpoints for configuration management

## API Endpoints

### TASK-10: File Upload API
**Objective:** Implement secure file upload functionality

**Code to Write:**
- `POST /api/upload` endpoint
- File validation (size, type, format)
- Temporary file storage
- CSV record counting
- Upload session management

**Security Features:**
- File size limits
- File type validation
- Path traversal prevention
- Temporary file cleanup

### TASK-11: Processing API
**Objective:** Create job submission and status endpoints

**Code to Write:**
- `POST /api/process` - Submit processing job with rate limit
- `GET /api/jobs/{job_id}/status` - Get job status with rate info and download link
- `PUT /api/jobs/{job_id}/rate` - Update webhook rate during processing
- `POST /api/webhook/test` - Test webhook endpoint
- Input validation and error handling

### TASK-11a: Download API
**Objective:** Implement CSV download functionality

**Code to Write:**
- `GET /api/jobs/{job_id}/download` - Download processed CSV file
- Session-based download access control
- Proper file headers and naming conventions
- Download statistics tracking
- File cleanup after download expiry

**Implementation Details:**
- Generate CSV files after processing completion
- Session validation for download access
- Appropriate HTTP headers for file download
- Timestamped file naming (e.g., "people_leads_2024-01-15_10-30.csv")
- Track download statistics in job status

### TASK-11b: Configuration Management API
**Objective:** Create endpoints for field mapping management

**Code to Write:**
- `GET /api/config/mappings` - Get current field mappings
- `PUT /api/config/mappings` - Update field mappings with validation
- `POST /api/config/backup` - Create configuration backup
- `POST /api/config/restore` - Restore from backup
- `GET /api/config/preview` - Preview current naming conventions

**Implementation Details:**
- Configuration validation before updates
- Hot-reload of mappings without restart
- Backup management with timestamps
- Error handling for invalid configurations

### TASK-12: WebSocket Integration
**Objective:** Implement real-time progress updates

**Code to Write:**
- SocketIO event handlers
- Job progress broadcasting
- Client connection management
- Error event handling

## Frontend Implementation

### TASK-13: HTML Structure and Tailwind Styling
**Objective:** Create responsive single-page interface

**Code to Write:**
- `templates/index.html` - Main application layout
- Tailwind CSS classes for modern, clean design
- Responsive design for mobile/desktop
- Drag-and-drop zone styling
- Progress bar and statistics dashboard

**UI Components:**
- File upload drag-and-drop zone
- Table type selection (radio buttons)
- Processing mode selection: "Send via Webhook" or "Download CSV"
- Webhook URL input field (when webhook mode selected)
- Webhook rate control (slider/presets)
- Processing progress dashboard with:
  - Rate display and controls
  - Data cleaning statistics (domains cleaned, duplicates removed, fields merged)
  - Download button (always available after processing)
- Configuration management section (collapsible)
- Real-time rate adjustment controls
- Error/success notifications

### TASK-14: Alpine.js Data Management
**Objective:** Implement frontend reactivity and state management

**Code to Write:**
```javascript
// Alpine.js component for main application
document.addEventListener('alpine:init', () => {
    Alpine.data('csvMerger', () => ({
        // State
        files: [],
        tableType: '',
        processingMode: 'webhook', // 'webhook' or 'download'
        webhookUrl: '',
        webhookRateLimit: 10,
        processing: false,
        progress: {},
        downloadAvailable: false,
        downloadUrl: '',
        configExpanded: false,
        currentMappings: {},
        
        // Methods
        handleFileDrop(e) { },
        validateFiles() { },
        submitProcessing() { },
        updateProgress(data) { },
        downloadCSV() { },
        toggleConfigSection() { },
        loadMappings() { },
        updateMappings() { },
        backupConfig() { },
        restoreConfig() { }
    }))
})
```

**Features:**
- File upload management
- Processing mode selection (webhook vs download)
- Form validation with conditional fields
- Real-time progress updates with data cleaning statistics
- Download functionality with proper file handling
- Configuration management interface
- Error handling and user feedback
- WebSocket integration for live updates

### TASK-15: File Upload Interface
**Objective:** Implement drag-and-drop file upload

**Code to Write:**
- Drag and drop event handlers
- File validation on frontend
- Upload progress indicators
- File list display with remove options
- Integration with backend upload API

## Deployment and Infrastructure

### TASK-16: Docker Configuration
**Objective:** Create containerized deployment setup

**Code to Write:**
- `Dockerfile` for application container
- Multi-stage build for optimization
- Redis service configuration
- Environment variable handling

### TASK-17: Railway Deployment Configuration
**Objective:** Configure automatic Railway deployment

**Code to Write:**
- `railway.toml` configuration file
- GitHub Actions workflow (`.github/workflows/deploy.yml`)
- Environment variable setup
- Health check endpoint

### TASK-18: Production Configuration
**Objective:** Set up production-ready configuration

**Code to Write:**
- Production environment settings
- Logging configuration
- Error monitoring setup
- Performance optimization settings

## Testing Implementation

### TASK-19: Unit Tests
**Objective:** Test individual components

**Code to Write:**
- `tests/test_csv_processor.py` - Test header mapping and deduplication
- `tests/test_webhook_sender.py` - Test delivery and retry logic
- `tests/test_queue_manager.py` - Test job management
- `tests/test_config.py` - Test configuration loading

### TASK-20: Integration Tests
**Objective:** Test end-to-end workflows

**Code to Write:**
- `tests/test_upload_flow.py` - Test complete upload process
- `tests/test_processing_pipeline.py` - Test CSV processing workflow
- `tests/test_webhook_integration.py` - Test webhook delivery
- Sample test data files

### TASK-21: Frontend Tests
**Objective:** Test UI functionality

**Code to Write:**
- JavaScript tests for Alpine.js components
- File upload functionality tests
- Progress tracking tests
- Error handling tests

## Additional Features

### TASK-22: Logging and Monitoring
**Objective:** Implement comprehensive logging

**Code to Write:**
- Structured logging configuration
- Job processing logs
- Webhook delivery logs
- Error tracking and reporting

### TASK-23: Configuration Updates Interface
**Objective:** Easy configuration management

**Code to Write:**
- Configuration validation
- Hot-reload capability for mappings
- Configuration backup/restore
- Documentation for field mappings

## Implementation Order

### Phase 1: Foundation (Tasks 1-3)
- Project setup
- Configuration system
- Basic Flask app

### Phase 2: Core Backend (Tasks 4-9)
- CSV processing
- Queue management
- Webhook delivery
- Background worker
- Session management (multi-tenant)
- Cleanup manager (48h retention)

### Phase 3: API Layer (Tasks 10-12)
- Upload endpoints
- Processing endpoints  
- WebSocket integration

### Phase 4: Frontend (Tasks 13-15)
- HTML/CSS layout
- Alpine.js functionality
- File upload interface

### Phase 5: Deployment (Tasks 16-18)
- Docker setup
- Railway configuration
- Production setup

### Phase 6: Testing (Tasks 19-21)
- Unit tests
- Integration tests
- Frontend tests

### Phase 7: Polish (Tasks 22-24)
- Logging/monitoring
- Configuration management
- Webhook rate control feature

## Success Criteria for Each Task

Each task is considered complete when:
1. Code is implemented according to specifications
2. Basic functionality testing passes
3. Code follows Python/JavaScript best practices
4. Error handling is implemented
5. Integration with other components works
6. Documentation is updated

## Estimated Timeline

- **Phase 1:** 2-3 days (additional config setup)
- **Phase 2:** 5-7 days (smart merging, data cleaning, config management, multi-tenant + cleanup)
- **Phase 3:** 3-4 days (download API, config API, enhanced processing endpoints)
- **Phase 4:** 3-4 days (processing modes, download UI, config management interface)
- **Phase 5:** 1-2 days
- **Phase 6:** 4-5 days (testing all new features: smart merging, download, config management)
- **Phase 7:** 2-3 days

**Total Estimated Duration:** 20-28 days

This implementation plan provides a clear roadmap for building the CSV merger application systematically, following the spec-driven development approach inspired by Amazon Kiro. 