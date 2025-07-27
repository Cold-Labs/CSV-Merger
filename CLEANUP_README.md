# Upload Cleanup System

The CSV Merger now includes automatic cleanup of old upload files to prevent disk space issues.

## 🤖 Automatic Cleanup

When you start the main app (`python simple_app.py`), it automatically:

- **Runs cleanup on startup** - cleans old files immediately
- **Runs cleanup every hour** - background thread monitors and cleans
- **Removes files older than 24 hours** - keeps recent uploads safe
- **Logs cleanup activity** - shows what was deleted and space freed

```bash
🚀 Starting CSV Merger (Simplified)
🧹 Running automatic upload cleanup...
✅ Cleanup completed: No old files to remove
🕒 Background cleanup scheduled (runs every hour)
```

## 🛠️ Manual Cleanup

### Command Line Tool

Use the standalone cleanup utility for manual cleanup:

```bash
# Dry run (see what would be deleted)
python cleanup_uploads.py --dry-run

# Clean files older than 24 hours (default)
python cleanup_uploads.py

# Clean files older than 12 hours
python cleanup_uploads.py --max-age 12

# Clean specific directory
python cleanup_uploads.py --uploads-dir custom_uploads/

# Help
python cleanup_uploads.py --help
```

### API Endpoint

Trigger cleanup via HTTP API:

```bash
# Basic cleanup (24 hours, real deletion)
curl -X POST http://localhost:8000/api/cleanup \
  -H "Content-Type: application/json"

# Custom cleanup (dry run, 12 hours)
curl -X POST http://localhost:8000/api/cleanup \
  -H "Content-Type: application/json" \
  -d '{"max_age_hours": 12, "dry_run": true}'
```

Response:
```json
{
  "success": true,
  "message": "Cleanup completed",
  "stats": {
    "folders_deleted": 3,
    "files_deleted": 1,
    "total_size_freed": 15728640,
    "errors": 0,
    "skipped": 12
  }
}
```

## 📊 What Gets Cleaned

- **Upload directories** (UUID-named folders)
- **Temporary files** from processing 
- **Old CSV files** from completed jobs
- **Keeps recent files** (< 24 hours by default)
- **Skips system files** (.DS_Store, etc.)

## ⚙️ Configuration

**Default Settings:**
- **Max Age:** 24 hours
- **Schedule:** Every hour
- **Upload Dir:** `uploads/`

**Customization:**
- Modify `start_background_cleanup()` in `simple_app.py` for different schedule
- Change `max_age_hours=24` for different retention period
- Use command line options for one-time customization

## 🔍 Monitoring

The cleanup logs all activity to the console:

```bash
🧹 Running automatic upload cleanup...
📁 redis-data (0 B, 116.4h old)
  ✅ Deleted
📊 Cleanup Summary:
   📁 Folders deleted: 1
   💾 Space freed: 0 B
```

This keeps your `uploads/` directory clean and prevents it from growing indefinitely! 🚀 