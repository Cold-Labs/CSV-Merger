# CSV Merger

Professional lead processing for cold email agencies with AI-powered header mapping.

## Features

- 🤖 **AI-Powered Mapping**: Intelligent CSV header mapping via n8n integration
- 🚀 **Real-time Processing**: WebSocket-based progress updates
- 📊 **Multi-tenant Support**: Session-based isolation
- 🔗 **Webhook Delivery**: Send processed data to external systems (Clay.com, etc.)
- 📥 **Download Option**: Direct CSV download for processed data
- 🧹 **Smart Deduplication**: Combines data from duplicate records
- 🌐 **Domain Cleaning**: Removes https, www, etc. from domains
- ⚡ **Rate Control**: Configurable webhook rate limiting

## Tech Stack

- **Backend**: Python Flask with Redis queue
- **Frontend**: Alpine.js + Tailwind CSS
- **Processing**: Pandas for CSV operations
- **AI Integration**: n8n webhook for header mapping
- **Storage**: Session-based file storage (48h cleanup)
- **Queue**: Redis Queue (RQ) for background processing

## Quick Start

### Local Development

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd csv-merger
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up Redis**
   ```bash
   # Using Docker
   docker run -d -p 6379:6379 redis:alpine
   
   # Or install locally (macOS)
   brew install redis
   redis-server
   ```

4. **Configure environment**
   ```bash
   export FLASK_ENV=development
   export REDIS_URL=redis://localhost:6379
   export SECRET_KEY=your-secret-key
   ```

5. **Run the application**
   ```bash
   python app.py
   ```

Visit `http://localhost:5002` to access the application.

## Railway Deployment

### Prerequisites

1. Railway account
2. GitHub repository
3. Redis add-on on Railway

### Deploy Steps

1. **Connect to Railway**
   ```bash
   # Install Railway CLI
   npm install -g @railway/cli
   
   # Login and link project
   railway login
   railway link
   ```

2. **Add Redis Service**
   - Go to Railway dashboard
   - Add Redis service to your project
   - Railway will automatically set `REDIS_URL`

3. **Configure Environment Variables**
   ```bash
   railway variables set FLASK_ENV=production
   railway variables set SECRET_KEY=your-production-secret-key
   railway variables set LOG_LEVEL=INFO
   ```

4. **Deploy**
   ```bash
   railway up
   ```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FLASK_ENV` | Environment (development/production) | development |
| `REDIS_URL` | Redis connection URL | redis://localhost:6379 |
| `SECRET_KEY` | Flask secret key | (required) |
| `LOG_LEVEL` | Logging level | INFO |
| `MAX_FILE_SIZE_MB` | Maximum file size | 20 |
| `MAX_FILES_PER_SESSION` | Files per session limit | 10 |
| `WEBHOOK_TIMEOUT` | Webhook timeout seconds | 30 |

## Project Structure

```
csv-merger/
├── app.py                 # Main Flask application
├── config/
│   ├── field_mappings.json     # Standard field mappings
│   ├── header_filters.json     # Header filtering rules
│   └── settings.py            # Configuration management
├── src/
│   ├── csv_processor.py       # Main CSV processing pipeline
│   ├── header_mapper.py       # n8n integration
│   ├── webhook_sender.py      # Webhook delivery
│   ├── session_manager.py     # Session handling
│   ├── queue_manager.py       # Job queue management
│   └── cleanup_manager.py     # File cleanup
├── templates/
│   └── index.html            # Frontend UI
├── static/
│   └── js/app.js            # Alpine.js frontend logic
├── Dockerfile.railway       # Railway deployment
└── railway.toml            # Railway configuration
```

## Usage

### 1. Login
- Enter your username to start a session
- Your files and jobs are isolated to your session

### 2. Upload CSV Files
- Upload multiple CSV files for processing
- Files are automatically analyzed for record counts
- Maximum 10 files per session (configurable)

### 3. Choose Processing Mode
- **Download**: Process and download merged CSV
- **Webhook**: Send data to external webhook (e.g., Clay.com)

### 4. Select Table Type
- **People**: Individual contacts with company data
- **Company**: Company-focused data structure

### 5. Configure Webhooks (if applicable)
- Enter webhook URL
- Set rate limit (requests per second)
- Optional: Set record limit for testing

### 6. Monitor Progress
- Real-time WebSocket updates
- Visual progress indicators
- AI mapping visualization

### 7. Download or Access Results
- Download processed CSV file
- Or receive data via webhook delivery

## API Endpoints

### Core Endpoints
- `GET /` - Main application UI
- `POST /api/login` - User authentication
- `POST /api/upload` - File upload
- `POST /api/jobs` - Submit processing job
- `GET /api/jobs/<id>/download` - Download processed CSV

### Utility Endpoints
- `GET /api/health` - Health check for monitoring
- `POST /api/webhook/test` - Test webhook connectivity
- `POST /api/webhook/test-n8n` - Test n8n integration

### WebSocket Events
- `job_progress` - Real-time progress updates
- `job_status_change` - Job status changes
- `session_jobs` - Session job history

## Configuration

### Field Mappings
Edit `config/field_mappings.json` to customize standard field mappings:

```json
{
  "people_mappings": {
    "First Name": ["first_name", "fname", "given_name"],
    "Last Name": ["last_name", "lname", "surname"],
    "Work Email": ["email", "work_email", "business_email"]
  }
}
```

### Header Filters
Edit `config/header_filters.json` to filter unwanted headers:

```json
{
  "unwanted_header_terms": [
    "avatar", "photo", "timestamp", "internal_id"
  ]
}
```

## Monitoring

### Health Check
The application provides a comprehensive health check endpoint at `/api/health`:

```json
{
  "status": "healthy",
  "redis": "connected",
  "config": "loaded",
  "session_manager": "active",
  "job_manager": "active",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### Logging
Logs are structured and include:
- Request/response tracking
- Processing pipeline steps
- Error handling and debugging
- Performance metrics

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

Copyright 2024 Cold Labs. All rights reserved. 