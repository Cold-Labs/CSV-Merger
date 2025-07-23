# CSV Merger Project - Complete Architecture Documentation

## Project Overview

The CSV Merger is a Flask-based web application designed for cold email agencies to process, standardize, and deduplicate lead data from multiple CSV sources. It features a three-phase processing pipeline with AI-powered header mapping and real-time progress tracking.

## Business Problem & Solution

**Problem:** Cold email agencies receive lead data from multiple sources (Apollo, ZoomInfo, Clay, etc.) with:
- Inconsistent column names (`email` vs `work_email` vs `contact_email`)
- Mixed data formats and quality
- Duplicate records across files
- Junk data and metadata

**Solution:** Automated three-phase processing pipeline that:
1. Merges raw files while preserving source information
2. Uses AI to intelligently map headers to standard fields
3. Enriches emails and performs smart deduplication

## Technology Stack

- **Backend:** Python Flask with Redis for job queuing
- **Frontend:** Alpine.js + Tailwind CSS (single-page app)
- **Processing:** Pandas for data manipulation
- **AI Integration:** n8n webhook with OpenAI for header mapping
- **Real-time Updates:** Flask-SocketIO for progress broadcasting
- **Job Queue:** RQ (Redis Queue) for background processing
- **Session Management:** Redis-based sessions (48h TTL)

## System Architecture

### Core Components

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend      │    │   Flask App     │    │   Background    │
│   (Alpine.js)   │◄──►│   (API & UI)    │◄──►│   Workers       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
                       ┌─────────────────┐    ┌─────────────────┐
                       │     Redis       │    │   n8n/OpenAI    │
                       │  (Jobs/Sessions)│    │  (AI Mapping)   │
                       └─────────────────┘    └─────────────────┘
```

### File Structure

```
CSV Merger/
├── app.py                      # Main Flask application
├── config/
│   ├── settings.py            # Configuration management
│   ├── field_mappings.json    # Standard field definitions
│   └── header_filters.json    # Junk column filters
├── src/
│   ├── csv_processor.py       # Main orchestrator (3-phase)
│   ├── phase1_merger.py       # Raw file merging
│   ├── phase2_standardizer.py # AI mapping application
│   ├── phase3_enricher.py     # Email enrichment & deduplication
│   ├── header_mapper.py       # n8n communication
│   ├── webhook_sender.py      # Webhook delivery system
│   ├── queue_manager.py       # Job & progress management
│   ├── session_manager.py     # Session handling
│   ├── config_manager.py      # Configuration loading
│   ├── cleanup_manager.py     # File cleanup (48h)
│   └── logging_config.py      # Centralized logging
├── templates/
│   └── index.html             # Frontend UI
└── uploads/                   # Session-based file storage
    └── {session_id}/          # Per-session directories
```

## Three-Phase Processing Pipeline

### Phase 1: Raw File Merger (`phase1_merger.py`)

**Purpose:** Combine all uploaded files without any processing

**Process:**
1. Read each CSV file individually
2. Add `Source` column to track file origin
3. Concatenate all DataFrames preserving ALL original columns
4. Return merged DataFrame with source tracking

**Key Features:**
- No data loss during merge
- Preserves file context for AI mapping
- Handles files with completely different structures

**Business Logic:** "Merge everything first, clean later"

### Phase 2: AI-Based Standardizer (`phase2_standardizer.py`)

**Purpose:** Apply intelligent header mappings using AI

**Process:**
1. Receive n8n response with per-file mappings
2. Parse priority-based mappings (primary → secondary → tertiary)
3. Apply mappings to create standardized columns
4. Fill standard headers using priority order

**n8n Response Format:**
```json
[{
  "mapped_files": [
    {
      "filename": "apollo.csv",
      "mapped_headers": {
        "First Name": {"primary": "first_name"},
        "Personal Email": {
          "primary": "personal_emails/1",
          "secondary": "personal_emails/0"
        }
      }
    }
  ]
}]
```

**Priority Logic:**
- **Primary:** Most reliable data source
- **Secondary:** Backup if primary is empty
- **Tertiary:** Last resort if both above are empty

**Business Logic:** "Let AI decide what columns mean, apply intelligently"

### Phase 3: Email Enricher & Deduplicator (`phase3_enricher.py`)

**Purpose:** Clean data and perform smart deduplication

**Email Enrichment Process:**
1. Find all email columns in standardized data
2. Classify as personal (Gmail, Yahoo, Outlook, Hotmail) or work emails
3. Rank personal emails: Gmail > Yahoo > Outlook > Hotmail
4. Consolidate into `Personal Email` and `Work Email` columns

**Deduplication Process:**
1. Create deduplication keys based on table type:
   - **People:** Work Email, Personal Email, Full Name + Company
   - **Company:** Company Name, Company Domain
2. Group records by deduplication key
3. Merge duplicate records (combine best data from each)
4. Preserve source information for all merged records

**Data Cleaning:**
- Remove protocols from domains (`https://company.com` → `company.com`)
- Standardize text formatting (proper case)
- Clean whitespace and invalid data

**Business Logic:** "Clean emails, rank by quality, merge duplicates intelligently"

## AI Integration (n8n/OpenAI)

### Header Mapping Flow

1. **Data Preparation:** Extract headers and sample data from each file
2. **Filtering:** Remove junk columns (IDs, empty columns, metadata)
3. **Payload Optimization:** Send only necessary data to reduce costs
4. **AI Processing:** n8n processes with OpenAI to generate mappings
5. **Priority Response:** Receive mappings with confidence-based priorities

### Payload Structure to n8n

```json
{
  "session_id": "abc123",
  "table_type": "people",
  "files": [
    {
      "filename": "apollo.csv",
      "header_count": 15,
      "sample_record": {"first_name": "John", "email": "john@example.com"}
    }
  ],
  "total_unique_headers": 25,
  "filtering_stats": {
    "headers_filtered_out": 10,
    "filtering_percentage": 28.6
  },
  "standard_headers": ["First Name", "Last Name", "Work Email", ...]
}
```

## Real-Time Progress System

### WebSocket Events

- **`job_progress`:** Processing progress updates
- **`job_status_change`:** Status changes (processing → completed)
- **`webhook_progress`:** Webhook delivery progress

### Progress Stages

1. **`n8n_mapping`:** Getting AI mappings
2. **`phase1`:** Raw file merging
3. **`phase2`:** AI standardization
4. **`phase3`:** Email enrichment & deduplication
5. **`webhook_preparation`:** Preparing webhook delivery
6. **`webhook_delivery`:** Sending webhooks
7. **`completed`:** Processing finished

## Session Management

### Session Lifecycle

1. **Creation:** Generate unique session ID on first upload
2. **File Storage:** Store files in `uploads/{session_id}/`
3. **Progress Tracking:** Redis-based job status and progress
4. **Cleanup:** Automatic cleanup after 48 hours

### Multi-Tenant Isolation

- Each session is completely isolated
- No database required - all state in Redis
- Session-based file organization
- Independent processing queues per session

## Webhook System

### Two-Step Processing

1. **CSV Processing:** Complete all three phases
2. **Webhook Delivery:** Separate step with rate limiting and retries

### Webhook Configuration

```json
{
  "url": "https://webhook.example.com",
  "rate_limit": 10,
  "retry_attempts": 3,
  "timeout": 30
}
```

### Payload Formats

**People Table:**
```json
{
  "person": {
    "first_name": "John",
    "last_name": "Smith",
    "work_email": "john@company.com",
    "personal_email": "john@gmail.com"
  },
  "company": {
    "company_name": "ACME Corp",
    "company_domain": "acme.com"
  },
  "source": "apollo.csv"
}
```

**Company Table:**
```json
{
  "company_name": "ACME Corp",
  "company_domain": "acme.com",
  "company_description": "Technology company",
  "source": "zoominfo.csv"
}
```

## Configuration System

### Field Mappings (`config/field_mappings.json`)

Defines standard headers and their variations:

```json
{
  "people_mappings": {
    "First Name": ["first_name", "fname", "given_name"],
    "Personal Email": ["personal_email", "gmail", "personal_email_address"]
  },
  "company_mappings": {
    "Company Name": ["company", "organization", "company_name"]
  }
}
```

### Header Filters (`config/header_filters.json`)

Lists unwanted header terms for filtering:

```json
{
  "unwanted_terms": [
    "id", "uuid", "score", "birthday", "financial_data",
    "tracking", "metadata", "nested_array"
  ]
}
```

## Error Handling & Logging

### Logging Structure

- **Module-level logging:** Each component has dedicated logger
- **Centralized configuration:** `src/logging_config.py`
- **Log files:** Stored in `logs/` directory
- **Structured logging:** JSON format for better parsing

### Error Recovery

- **RQ failures:** Fallback to synchronous processing
- **n8n timeout:** Continue with empty mappings
- **File errors:** Skip problematic files, continue processing
- **Webhook failures:** Retry with exponential backoff

## Performance Optimizations

### Data Processing

- **Vectorized operations:** Pandas-based processing
- **Memory efficiency:** Stream processing for large files
- **Async operations:** Non-blocking I/O for external APIs
- **Payload optimization:** Filter junk data before sending to AI

### Caching Strategy

- **Redis caching:** Job status and progress
- **Session persistence:** 48-hour TTL
- **Configuration caching:** In-memory config loading

## Security Considerations

### Data Protection

- **Session isolation:** Complete tenant separation
- **Temporary storage:** Automatic 48h cleanup
- **No persistent database:** Reduces data exposure
- **Input validation:** File type and size restrictions

### API Security

- **Rate limiting:** Webhook delivery throttling
- **Timeout protection:** All external calls have timeouts
- **Error sanitization:** No sensitive data in error messages

## Deployment Configuration

### Environment Variables

```bash
# Server Configuration
FLASK_PORT=5002
SECRET_KEY=production-secret-key

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# File Limits
MAX_FILE_SIZE_MB=20
MAX_FILES_PER_SESSION=10

# Session Management
SESSION_TTL_SECONDS=172800  # 48 hours

# n8n Integration
N8N_WEBHOOK_URL=https://n8n.coldlabs.ai/webhook/csv-header-mapping
```

### Required Dependencies

```bash
Flask==2.3.3
Flask-SocketIO==5.3.6
pandas==2.1.1
redis==5.0.0
rq==1.15.1
aiohttp==3.8.5
fuzzywuzzy==0.18.0
eventlet==0.33.3
```

## Current Status & Known Issues

### ✅ Working Features

- Three-phase processing pipeline
- n8n AI integration with priority mappings
- Real-time progress updates via WebSocket
- Webhook delivery with rate limiting
- Session-based multi-tenant isolation
- Automatic file cleanup
- Email ranking and consolidation
- Smart deduplication with record merging

### ⚠️ Known Issues

1. **Environment Variable:** `SESSION_TTL_SECONDS` can pick up comments if set incorrectly
2. **Large Files:** Memory usage can spike with very large CSVs (>100MB)
3. **n8n Timeout:** No retry mechanism if n8n is temporarily unavailable

### 🔄 Testing Status

- **Unit Tests:** Not implemented yet
- **Integration Tests:** Manual testing required
- **Load Testing:** Not performed
- **n8n Integration:** Ready for testing with real data

## Next Steps for Development

1. **Test with Real Data:** Upload actual CSV files and verify end-to-end processing
2. **Performance Testing:** Test with large files and multiple concurrent sessions
3. **Error Handling:** Test edge cases and error recovery mechanisms
4. **Unit Tests:** Implement comprehensive test suite
5. **Documentation:** API documentation for webhook integrations
6. **Monitoring:** Add metrics and performance monitoring

## API Endpoints

### Core Endpoints

- **`POST /api/upload`:** Upload CSV files
- **`POST /api/submit`:** Start processing job
- **`GET /api/status/{job_id}`:** Get job status
- **`GET /api/download/{file_path}`:** Download processed CSV
- **`POST /api/webhook/test-n8n`:** Test n8n connectivity

### WebSocket Events

- **`connect`:** Client connection
- **`join_session`:** Join session room for updates
- **`job_progress`:** Progress updates
- **`job_status_change`:** Status changes

## File Formats & Standards

### Input Requirements

- **Format:** CSV files only
- **Size Limit:** 20MB per file
- **File Limit:** 10 files per session
- **Encoding:** UTF-8 preferred

### Output Formats

- **CSV Export:** Standardized columns with clean data
- **Webhook JSON:** Structured payloads for API integration
- **Progress JSON:** Real-time status updates

---

*This documentation reflects the current state of the CSV Merger project as of the three-phase refactoring. All components are integrated and ready for testing with real data.* 