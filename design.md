# CSV Merger Application - Design Document

## System Architecture

### High-Level Architecture
```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Frontend      │    │   Flask API      │    │   Redis Queue   │
│   (Alpine.js)   │◄──►│   + Sessions     │◄──►│   + Worker      │
│   + Tailwind    │    │   + Multi-tenant │    │   + TTL Data    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │                          │
                              ▼                          ▼
                   ┌──────────────────┐         ┌─────────────────┐
                   │  Session-based   │         │  Webhook        │
                   │  File Storage    │         │  Delivery       │
                   │  (48h cleanup)   │         │  + Cleanup      │
                   └──────────────────┘         └─────────────────┘
```

### Technology Stack
- **Frontend:** HTML + Alpine.js + Tailwind CSS
- **Backend:** Python 3.11+ + Flask + Flask-SocketIO (for real-time updates)
- **Queue:** Redis + RQ (Redis Queue)
- **CSV Processing:** pandas + fuzzywuzzy + python-Levenshtein
- **HTTP Client:** requests (for webhook delivery)
- **Deployment:** Railway + GitHub Actions

## Component Structure

### Backend Components

#### 1. Flask Application (`app.py`)
```python
# Main application entry point
# Routes: /, /upload, /process, /status
# WebSocket handlers for real-time updates
```

#### 2. CSV Processor (`csv_processor.py`)
```python
class CSVProcessor:
    - header_mapping()      # Fuzzy match headers to standards
    - deduplicate_records() # Remove duplicates with smart data merging
    - merge_files()         # Combine multiple CSV files
    - validate_data()       # Data quality checks
    - clean_domains()       # Remove https, www from domains
    - normalize_data()      # Clean and standardize data formats
    - export_to_csv()       # Generate downloadable CSV file
```

#### 3. Queue Manager (`queue_manager.py`)
```python
class JobManager:
    - enqueue_job()         # Add processing job to queue
    - get_job_status()      # Monitor job progress
    - update_progress()     # Update job completion status
```

#### 4. Webhook Sender (`webhook_sender.py`)
```python
class WebhookSender:
    - send_record()         # Send individual record
    - retry_failed()        # Exponential backoff retry logic
    - batch_send()          # Send multiple records efficiently
    - set_rate_limit()      # Configure sending rate (requests/sec)
    - get_current_rate()    # Get actual sending rate
    - rate_limiter()        # Token bucket rate limiting implementation
```

#### 5. Configuration Manager (`config.py`)
```python
# Centralized configuration management
# Field mappings, file limits, retry settings
```

#### 6. Session Manager (`session_manager.py`)
```python
class SessionManager:
    - create_session()          # Generate unique session ID
    - get_session_workspace()   # Get session-specific file directory
    - get_user_jobs()          # List jobs for current session
    - cleanup_session()        # Clean up expired session data
    - get_session_limits()     # Get resource limits per session
```

#### 7. Cleanup Manager (`cleanup_manager.py`)
```python
class CleanupManager:
    - cleanup_expired_files()  # Remove files older than 48h
    - cleanup_expired_jobs()   # Remove job data with expired TTL
    - monitor_storage()        # Track storage usage
    - schedule_cleanup()       # Automated cleanup scheduler
```

#### 8. Configuration Manager (`config_manager.py`)
```python
class ConfigManager:
    - load_field_mappings()    # Load naming conventions from file
    - update_field_mappings()  # Hot-reload field mappings
    - validate_mappings()      # Validate mapping syntax
    - backup_config()          # Create configuration backup
    - restore_config()         # Restore from backup
    - get_mapping_preview()    # Preview current mappings
```

### Frontend Components

#### 1. Main Interface (`index.html`)
- Single-page application layout
- Drag-and-drop zone
- Processing dashboard
- Real-time status updates

#### 2. Alpine.js Data Management
```javascript
// State management for:
// - File uploads
// - Processing status  
// - Progress tracking
// - Error handling
```

## Data Flow Design

### 1. Upload Phase
```
User drops files → Frontend validation → Upload to Flask → Store in temp directory
```

### 2. Processing Phase  
```
User clicks process → Job queued in Redis → Worker picks up job → Process CSV files
                                                    ↓
CSV merge → Header mapping → Deduplication → Individual record webhook sending
```

### 3. Delivery Phase
```
For each record → Format JSON → Send webhook → Retry on failure → Update progress
```

## Configuration Management

### Configuration File Structure 

#### Main Settings (`config/settings.py`)
```python
class Config:
    # File Processing Settings
    MAX_FILE_SIZE_MB = 20
    ALLOWED_EXTENSIONS = ['csv']
    TEMP_UPLOAD_DIR = 'uploads/temp'
    SESSION_BASED_STORAGE = True
    
    # Multi-tenant Settings
    MAX_CONCURRENT_JOBS_PER_SESSION = 3
    MAX_FILES_PER_SESSION = 10
    MAX_STORAGE_PER_SESSION_MB = 100
    
    # Webhook Settings
    WEBHOOK_TIMEOUT = 30
    WEBHOOK_RETRY_ATTEMPTS = 3
    WEBHOOK_RETRY_BACKOFF = [1, 3, 9]  # seconds
    WEBHOOK_RATE_LIMIT = 10  # requests per second (default)
    WEBHOOK_RATE_PRESETS = [1, 5, 10, 30, 60, 0]  # 0 = no limit
    
    # Deduplication Settings
    FUZZY_MATCH_THRESHOLD = 85  # percentage similarity
    SMART_MERGE_ENABLED = True
    
    # Data Cleaning Settings
    CLEAN_DOMAINS = True
    NORMALIZE_DATA = True
    
    # Queue Settings
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
    JOB_TIMEOUT = 3600  # 1 hour
    
    # Cleanup Settings
    DATA_RETENTION_HOURS = 48
    CLEANUP_INTERVAL_MINUTES = 60
    SESSION_TTL_HOURS = 48
    MAX_TOTAL_STORAGE_GB = 10
    
    # Field Mappings File
    FIELD_MAPPINGS_FILE = 'config/field_mappings.json'
```

#### Field Mappings (`config/field_mappings.json`)
```json
{
  "company_mappings": {
    "Company Name": ["company name", "business name", "organization", "company", "firm", "corp"],
    "Company Domain": ["domain", "website", "url", "web site", "company domain", "site"],
    "Company Description": ["description", "about", "company description", "business description"],
    "Industry": ["industry", "sector", "business type", "category", "vertical"],
    "Company Employee Count": ["employees", "employee count", "staff size", "team size", "headcount"],
    "Company LinkedIn": ["linkedin", "linkedin url", "company linkedin", "linkedin page"],
    "Company LinkedIn Handle": ["linkedin handle", "linkedin username", "handle"],
    "Year Founded": ["founded", "year founded", "established", "inception"],
    "Company Location": ["location", "address", "city", "headquarters", "hq"]
  },
  "people_mappings": {
    "First Name": ["first name", "fname", "given name", "first", "firstname"],
    "Last Name": ["last name", "lname", "surname", "family name", "last", "lastname"],
    "Full Name": ["full name", "name", "contact name", "person name", "fullname"],
    "Job Title": ["title", "job title", "position", "role", "designation"],
    "LinkedIn Profile": ["linkedin", "linkedin profile", "linkedin url", "profile"],
    "Person Location": ["location", "city", "address", "person location"],
    "Company Name": ["company", "company name", "organization", "employer"],
    "Company Description": ["company description", "about company", "description"],
    "Company Website": ["website", "company website", "url", "domain"],
    "Company LinkedIn URL": ["company linkedin", "linkedin company", "company linkedin url"],
    "Company Employee Count": ["employees", "company size", "employee count"],
    "Company Location": ["company location", "company address", "company city"],
    "Company Revenue": ["revenue", "company revenue", "annual revenue", "turnover"]
  },
  "data_cleaning_rules": {
    "domain_prefixes_to_remove": ["https://", "http://", "www.", "www2.", "m."],
    "domain_suffixes_to_remove": ["/", "/#", "?"],
    "normalize_whitespace": true,
    "remove_extra_spaces": true,
    "standardize_case": {
      "domains": "lowercase",
      "names": "title_case"
    }
  }
}
```

### Environment Configuration (`.env`)
```bash
FLASK_ENV=development
REDIS_URL=redis://localhost:6379
SECRET_KEY=your-secret-key
WEBHOOK_TIMEOUT=30
MAX_FILE_SIZE_MB=20
```

## Database Design

### Redis Data Structures

#### Job Status Tracking (48h TTL)
```redis
job:{session_id}:{job_id} = {
    "status": "pending|processing|completed|failed",
    "session_id": "session-uuid",
    "total_records": 1000,
    "processed_records": 750,
    "successful_webhooks": 720,
    "failed_webhooks": 30,
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:35:00Z",
    "expires_at": "2024-01-17T10:30:00Z",
    "error_message": null
}
```

#### Session Management (48h TTL)
```redis
session:{session_id} = {
    "created_at": "2024-01-15T10:30:00Z",
    "last_activity": "2024-01-15T10:35:00Z",
    "active_jobs": ["job1", "job2"],
    "total_files_uploaded": 5,
    "storage_used_mb": 45.2
}

session:{session_id}:jobs = ["job1", "job2", "job3"]
```

#### Failed Webhook Queue
```redis
failed_webhooks:{job_id} = [
    {
        "record_data": {...},
        "webhook_url": "https://...",
        "attempt_count": 2,
        "last_error": "Connection timeout",
        "next_retry": "2024-01-15T10:40:00Z"
    }
]
```

## API Design

### REST Endpoints

#### 1. Session Management
```http
GET /api/session
# Creates new session if none exists, returns existing session info

Response:
{
    "session_id": "session-uuid",
    "created_at": "2024-01-15T10:30:00Z",
    "active_jobs": 2,
    "storage_used_mb": 45.2,
    "storage_limit_mb": 100,
    "expires_at": "2024-01-17T10:30:00Z"
}
```

#### 2. File Upload
```http
POST /api/upload
Content-Type: multipart/form-data

Response:
{
    "status": "success",
    "files": [
        {
            "filename": "leads.csv", 
            "size": 1024576,
            "records": 1500
        }
    ],
    "upload_id": "uuid-string"
}
```

#### 3. Start Processing
```http
POST /api/process
Content-Type: application/json

{
    "upload_id": "uuid-string",
    "table_type": "company|people", 
    "webhook_url": "https://your-webhook.com/endpoint",
    "webhook_rate_limit": 10
}

Response:
{
    "status": "success",
    "job_id": "job-uuid",
    "estimated_duration": 300
}
```

#### 4. Job Status
```http
GET /api/jobs/{job_id}/status

Response:
{
    "job_id": "job-uuid",
    "status": "processing",
    "progress": {
        "total_records": 1000,
        "processed": 750,
        "successful_webhooks": 720,
        "failed_webhooks": 30,
        "percentage": 75,
        "current_rate": 8.5,
        "rate_limit": 10,
        "duplicates_removed": 45,
        "fields_merged": 23,
        "domains_cleaned": 12,
        "download_available": true,
        "download_url": "/api/jobs/job-uuid/download"
    }
}
```

#### 5. Update Webhook Rate
```http
PUT /api/jobs/{job_id}/rate
Content-Type: application/json

{
    "rate_limit": 15
}

Response:
{
    "status": "success",
    "new_rate_limit": 15,
    "previous_rate_limit": 10
}
```

#### 6. CSV Download
```http
GET /api/jobs/{job_id}/download

Response: 
# Direct file download with headers:
Content-Type: text/csv
Content-Disposition: attachment; filename="people_leads_2024-01-15_10-30.csv"

# Returns the merged, deduplicated, and cleaned CSV data
```

#### 7. Configuration Management
```http
GET /api/config/mappings
# Get current field mappings

PUT /api/config/mappings
Content-Type: application/json
{
    "company_mappings": {...},
    "people_mappings": {...}
}

POST /api/config/backup
# Create configuration backup

POST /api/config/restore
# Restore from backup
```

#### 8. Storage and Cleanup Status
```http
GET /api/storage/status

Response:
{
    "total_storage_used_mb": 892.5,
    "total_storage_limit_mb": 10240,
    "session_count": 15,
    "active_jobs": 8,
    "next_cleanup": "2024-01-15T11:00:00Z",
    "last_cleanup": "2024-01-15T10:00:00Z",
    "files_cleaned_last_run": 42
}
```

### WebSocket Events
```javascript
// Real-time progress updates
socket.on('job_progress', (data) => {
    // Update progress bar and statistics
});

socket.on('job_completed', (data) => {
    // Show completion notification
});

socket.on('webhook_failed', (data) => {
    // Show failed webhook notification
});
```

## Error Handling Strategy

### 1. File Upload Errors
- File size validation (client + server)
- File format validation
- Malformed CSV handling
- Clear error messages to user

### 2. Processing Errors
- Invalid data format handling
- Memory management for large files
- Graceful worker failure recovery
- Partial processing completion

### 3. Webhook Delivery Errors
- Connection timeouts
- HTTP error status codes
- Exponential backoff retry logic
- Failed delivery tracking and reporting

### 4. System Errors
- Redis connection failures
- Disk space limitations
- Worker process crashes
- Comprehensive logging

## Testing Strategy

### 1. Unit Tests
```python
# Test individual components
test_csv_processor.py      # Header mapping, deduplication
test_webhook_sender.py     # Delivery logic, retry mechanism
test_config_manager.py     # Configuration loading
```

### 2. Integration Tests
```python
# Test component interactions
test_upload_flow.py        # End-to-end upload process
test_processing_pipeline.py # Full CSV processing workflow
test_webhook_integration.py # Webhook delivery testing
```

### 3. Frontend Tests
```javascript
// Alpine.js component testing
// File upload UI testing
// Progress tracking testing
```

### 4. Performance Tests
- Large file processing (up to 20MB)
- Concurrent job handling
- Memory usage monitoring
- Webhook delivery performance

## Security Considerations

### 1. File Upload Security
- File type validation
- File size limits
- Temporary file cleanup
- Path traversal prevention

### 2. Webhook Security
- URL validation
- Request timeout limits
- Rate limiting considerations
- Sensitive data handling

### 3. General Security
- Environment variable management
- Input validation and sanitization
- Error message information disclosure
- CSRF protection for forms

## Deployment Strategy

### 1. Railway Configuration
```yaml
# railway.toml
[build]
builder = "DOCKERFILE"

[deploy]
healthcheckPath = "/health"
healthcheckTimeout = 300
restartPolicyType = "ON_FAILURE"
```

### 2. GitHub Actions Pipeline
```yaml
# .github/workflows/deploy.yml
# Automated testing and deployment on push to main
# Environment variable management
# Database migration handling
```

### 3. Environment Management
- Development, staging, production configs
- Redis instance configuration
- File storage management
- Monitoring and logging setup

## Performance Optimization

### 1. CSV Processing
- Chunk-based file reading for large files
- Parallel processing where possible
- Memory-efficient pandas operations
- Progress tracking granularity

### 2. Webhook Delivery
- Connection pooling for HTTP requests
- Batch processing where applicable
- Async webhook sending
- Failed delivery queue management

### 3. Frontend Performance
- Minimal JavaScript bundle size
- Efficient Alpine.js reactivity
- Progress update batching
- File upload optimization 