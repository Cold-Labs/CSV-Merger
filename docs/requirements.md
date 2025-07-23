# CSV Merger Application - Requirements

## Project Overview
A web application for cold email agencies to merge, deduplicate, and standardize CSV files from multiple lead generation platforms, then distribute individual records via webhooks.

## User Stories

### Primary User Story
**As a cold email agency operator**, I want to upload CSV files from different lead platforms, automatically standardize their headers and deduplicate records, so that I can have clean, unified lead data sent to my CRM/automation tools via webhooks.

### Detailed User Stories

#### US-1: CSV Upload and Processing
**As a user**, I want to drag and drop multiple CSV files onto a web interface, so that I can easily upload lead data from different platforms without manual file selection.

**Acceptance Criteria:**
- Support drag and drop interface for CSV files
- Allow multiple file uploads simultaneously
- Display file names and sizes after upload
- Show upload progress indicators
- Enforce 20MB maximum file size limit
- Validate CSV format and provide error messages for invalid files

#### US-2: Table Type Selection
**As a user**, I want to choose between "Company" and "People" table types before processing, so that the application applies the correct data standardization rules.

**Acceptance Criteria:**
- Radio button or toggle to select table type
- Clear labels explaining the difference
- Cannot proceed without selection
- Different field mappings applied based on selection

#### US-3: Header Standardization
**As a user**, I want the application to automatically map messy headers from different platforms to my standardized naming convention, so that all my data follows consistent field names.

**Acceptance Criteria:**
- Fuzzy matching algorithm identifies similar headers
- **Company Table Standard Headers:**
  - Company Name
  - Company Domain  
  - Company Description
  - Industry
  - Company Employee Count
  - Company LinkedIn
  - Company LinkedIn Handle
  - Year Founded
  - Company Location
- **People Table Standard Headers:**
  - First Name, Last Name, Full Name
  - Job Title, LinkedIn Profile, Person Location
  - Company Name, Company Description, Company Website
  - Company LinkedIn URL, Company Employee Count
  - Company Location, Company Revenue
- Unmapped headers are preserved but flagged
- User can review mapping results before final processing

#### US-4: Data Deduplication
**As a user**, I want duplicate records automatically removed using intelligent matching, so that I don't send the same lead multiple times.

**Acceptance Criteria:**
- **Company Deduplication:** Company Name + Company Domain
- **People Deduplication:** Full Name + Company Name
- Fuzzy matching for slight variations in names/domains
- **Smart data merging:** Combine information from duplicate records to create the most complete record
- Prioritize non-empty fields when merging duplicates
- Show deduplication statistics (total removed, final count, fields merged)

#### US-5: Webhook Configuration
**As a user**, I want to specify a webhook URL where individual lead records will be sent, so that my CRM or automation tools receive the processed data in real-time.

**Acceptance Criteria:**
- Text input field for webhook URL
- URL validation (proper format, reachable endpoint)
- Option to test webhook with sample payload
- Webhook delivery with retry logic (3 attempts with exponential backoff)
- Error logging for failed deliveries

#### US-5b: Webhook Rate Control
**As a user**, I want to control the rate at which webhooks are sent, so that I don't overwhelm my receiving systems and can manage API rate limits.

**Acceptance Criteria:**
- Configurable webhook sending rate (requests per second/minute)
- Rate limit controls in the UI (slider or input field)
- Real-time rate adjustment during processing
- Rate limiting that respects the configured limits
- Display current sending rate in the progress dashboard
- Preset rate options (e.g., "1/sec", "10/sec", "60/sec", "No limit")

#### US-6: CSV Download Capability
**As a user**, I want to download the merged and deduplicated CSV file, so that I have a backup option and can import the data manually if webhook delivery fails.

**Acceptance Criteria:**
- Option to choose between "Send via Webhook" or "Download CSV" after processing
- "Download CSV" button always available, even during webhook sending
- Downloaded file uses standardized headers and clean data
- File naming includes timestamp and table type (e.g., "people_leads_2024-01-15_10-30.csv")
- Download preserves all merged and deduplicated data
- Session-based download access (only user who processed can download)

#### US-7: Easy Naming Convention Management
**As a user**, I want to easily modify the standard field names and mapping rules, so that I can adapt the tool to different naming conventions without code changes.

**Acceptance Criteria:**
- Configuration file with clear field mappings that's easy to edit
- Ability to add new field mappings without restarting the application
- Preview of current naming conventions in the UI
- Validation of configuration changes
- Backup and restore capability for naming configurations
- Documentation/examples of mapping syntax

#### US-8: Data Cleaning and Normalization
**As a user**, I want company domains and other data automatically cleaned and normalized, so that my data is consistent and usable.

**Acceptance Criteria:**
- **Domain cleaning:** Remove "https://", "http://", "www." prefixes from company domains
- Standardize domain format (lowercase, no trailing slashes)
- Clean and normalize other common data issues (extra spaces, inconsistent formatting)
- Preserve original data integrity while normalizing
- Show data cleaning statistics in processing results

#### US-9: Real-time Processing Dashboard
**As a user**, I want to see real-time progress of my CSV processing job, so that I know the status and can monitor completion.

**Acceptance Criteria:**
- Progress bar showing overall completion percentage
- Statistics display:
  - Total records uploaded
  - Records after deduplication
  - Records successfully sent via webhook
  - Failed webhook deliveries
  - Current processing status
- Real-time updates without page refresh
- Estimated time remaining

#### US-10: Background Processing
**As a system**, I need to process large CSV files in the background without blocking the web interface, so that users can continue working while data is being processed.

**Acceptance Criteria:**
- Redis queue for job management
- Background worker processes handle CSV processing
- Job status tracking and updates
- Ability to handle multiple concurrent jobs
- Graceful handling of worker failures

#### US-11: Multi-Tenant Session Management
**As a team of employees**, we want to use the application simultaneously without interfering with each other's work, so that multiple people can process CSVs concurrently.

**Acceptance Criteria:**
- Session-based user isolation (no login required)
- Each session gets unique workspace and job tracking
- Concurrent job processing without conflicts
- Session-specific file upload directories
- Resource limits per session to prevent abuse

#### US-12: Temporary Storage with Auto-Cleanup
**As a system administrator**, I want uploaded files and job data to be automatically cleaned up after 48 hours, so that storage doesn't grow indefinitely without requiring a database.

**Acceptance Criteria:**
- All uploaded files stored temporarily for 48 hours
- Job data in Redis with 48-hour TTL (Time To Live)
- Automated cleanup process runs every hour
- No persistent database required
- Storage usage monitoring and alerts
- Graceful handling of cleanup during active jobs

## JSON Output Schemas

### Company Table Webhook Payload
```json
{
  "company_name": "string",
  "company_domain": "string", 
  "company_description": "string",
  "industry": "string",
  "company_employee_count": "string",
  "company_linkedin": "string",
  "company_linkedin_handle": "string",
  "year_founded": "string",
  "company_location": "string"
}
```

### People Table Webhook Payload
```json
{
  "person": {
    "first_name": "string",
    "last_name": "string", 
    "full_name": "string",
    "job_title": "string",
    "linkedin_profile": "string",
    "person_location": "string"
  },
  "company": {
    "company_name": "string",
    "company_description": "string", 
    "company_website": "string",
    "company_linkedin_url": "string",
    "company_employee_count": "string",
    "company_location": "string",
    "company_revenue": "string"
  }
}
```

## Non-Functional Requirements

### Performance
- Support files up to 20MB in size
- Process 10,000 records within 5 minutes
- Handle up to 5 concurrent processing jobs

### Reliability  
- Webhook retry logic with exponential backoff
- Graceful error handling and user feedback
- Data persistence during processing failures

### Usability
- Single-page application with intuitive interface
- Mobile-responsive design using Tailwind CSS
- Clear error messages and status indicators

### Deployment
- Automatic deployment to Railway via GitHub integration
- Environment-based configuration management
- Easy configuration updates without code changes

## Success Criteria
- User can upload multiple CSV files and get standardized, deduplicated output
- All individual records successfully delivered via webhooks  
- Processing completes within reasonable time limits
- Clean, professional UI that works across devices
- Zero data loss during processing pipeline 