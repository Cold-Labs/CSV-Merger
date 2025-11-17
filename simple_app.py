#!/usr/bin/env python3
"""
CSV Merger - Simplified Application
No WebSockets, no auth, no multi-tenancy - just core CSV processing
"""

import os
import tempfile
import threading
import time
import uuid
from datetime import datetime

import redis
from flask import Flask, jsonify, render_template, request, send_file
from rq import Queue
from werkzeug.utils import secure_filename

from cleanup_uploads import UploadCleanup
from simple_config import Config
from simple_csv_processor import CSVProcessor


# Redis configuration for Railway deployment
def get_redis_config():
    """Get Redis configuration from environment variables"""
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        # Railway Redis addon provides REDIS_URL
        return redis.from_url(redis_url)
    else:
        # Fallback to localhost for development
        return redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=int(os.getenv("REDIS_DB", 0)),
        )


# Redis client for shared state
redis_client = get_redis_config()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB max file size
app.config["UPLOAD_FOLDER"] = "uploads"

# Ensure upload directory exists
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Redis connection for job queue (use same config as main Redis client)
redis_conn = redis_client
job_queue = Queue("csv_processing", connection=redis_conn)

# Global storage for job status (simplified)
job_status = {}


@app.route("/")
def index():
    """Main page"""
    return render_template("simple_index.html")


@app.route("/ping")
def ping():
    """Simple ping endpoint"""
    return "pong"


@app.route("/api/upload", methods=["POST"])
def upload_files():
    """Upload CSV files"""
    try:
        if "files" not in request.files:
            return jsonify({"error": "No files provided"}), 400

        files = request.files.getlist("files")
        if not files or all(f.filename == "" for f in files):
            return jsonify({"error": "No files selected"}), 400

        uploaded_files = []
        job_id = str(uuid.uuid4())
        job_folder = os.path.join(app.config["UPLOAD_FOLDER"], job_id)
        os.makedirs(job_folder, exist_ok=True)

        for file in files:
            if file and file.filename and file.filename.lower().endswith(".csv"):
                filename = secure_filename(file.filename)
                file_path = os.path.join(job_folder, filename)
                file.save(file_path)

                # Get file info
                file_size = os.path.getsize(file_path)

                uploaded_files.append(
                    {"filename": filename, "path": file_path, "size": file_size}
                )

        if not uploaded_files:
            return jsonify({"error": "No valid CSV files uploaded"}), 400

        return jsonify(
            {
                "success": True,
                "job_id": job_id,
                "files": uploaded_files,
                "message": f"Uploaded {len(uploaded_files)} files successfully",
            }
        )

    except Exception as e:
        return jsonify({"error": f"Upload failed: {str(e)}"}), 500


@app.route("/api/count-records", methods=["POST"])
def count_records():
    """Count records in uploaded files"""
    try:
        data = request.get_json()
        job_id = data.get("job_id")

        if not job_id:
            return jsonify({"error": "No job_id provided"}), 400

        job_folder = os.path.join(app.config["UPLOAD_FOLDER"], job_id)
        if not os.path.exists(job_folder):
            return jsonify({"error": "Job not found"}), 404

        processor = CSVProcessor()
        file_counts = []
        total_records = 0

        for filename in os.listdir(job_folder):
            if filename.endswith(".csv"):
                file_path = os.path.join(job_folder, filename)
                try:
                    record_count = processor.count_records(file_path)
                    file_counts.append({"filename": filename, "records": record_count})
                    total_records += record_count
                except Exception as e:
                    file_counts.append(
                        {"filename": filename, "records": 0, "error": str(e)}
                    )

        return jsonify(
            {
                "success": True,
                "job_id": job_id,
                "file_counts": file_counts,
                "total_records": total_records,
            }
        )

    except Exception as e:
        return jsonify({"error": f"Count failed: {str(e)}"}), 500


@app.route("/api/process", methods=["POST"])
def process_files():
    """Start processing files"""
    try:
        data = request.get_json()
        job_id = data.get("job_id")
        processing_mode = data.get(
            "processing_mode", "download"
        )  # 'download' or 'webhook'
        webhook_url = data.get("webhook_url")
        table_type = data.get("table_type", "companies")
        rate_limit = data.get("rate_limit", 10)  # requests per second (Clay's sustained limit per workspace)
        record_limit = data.get("record_limit")  # limit for testing

        if not job_id:
            return jsonify({"error": "No job_id provided"}), 400

        if processing_mode == "webhook" and not webhook_url:
            return jsonify({"error": "Webhook URL required for webhook mode"}), 400

        job_folder = os.path.join(app.config["UPLOAD_FOLDER"], job_id)
        if not os.path.exists(job_folder):
            return jsonify({"error": "Job not found"}), 404

        # Get list of files
        file_paths = []
        for filename in os.listdir(job_folder):
            if filename.endswith(".csv"):
                file_paths.append(os.path.join(job_folder, filename))

        if not file_paths:
            return jsonify({"error": "No CSV files found"}), 400

        # Initialize job status
        job_status[job_id] = {
            "job_id": job_id,
            "status": "processing",
            "progress": 0,
            "message": "Starting processing...",
            "created_at": datetime.now().isoformat(),
            "processing_mode": processing_mode,
            "webhook_url": webhook_url,
            "table_type": table_type,
        }

        # BOTH modes now use the EXACT SAME 3-phase processing
        try:
            processor = CSVProcessor()

            # Update status as we go through phases (also save to Redis for consistency)
            status_update = {
                "status": "processing",
                "progress": 10,
                "message": "Starting Phase 1: Merging files...",
            }
            job_status[job_id].update(status_update)

            # Also store in Redis so status polling is consistent
            import json

            try:
                redis_client.hset(
                    f"job_status:{job_id}",
                    mapping={"data": json.dumps(job_status[job_id], default=str)},
                )
            except Exception as e:
                print(f"⚠️ Redis update failed: {e}")

            result_path = processor.process_files_sync(
                file_paths=file_paths,
                job_id=job_id,
                table_type=table_type,
                output_dir=job_folder,
                record_limit=record_limit,
            )

            # Update status after processing completes
            status_update = {
                "status": "processing",
                "progress": 75,
                "message": "All 3 phases completed successfully",
            }
            job_status[job_id].update(status_update)
            try:
                redis_client.hset(
                    f"job_status:{job_id}",
                    mapping={"data": json.dumps(job_status[job_id], default=str)},
                )
            except Exception as e:
                print(f"⚠️ Redis update failed: {e}")

            print(f"✅ All 3 phases completed for job {job_id}, result: {result_path}")

            # At this point, all 3 phases are complete for BOTH modes
            if processing_mode == "download":
                # Download mode: Mark as completed, ready for download
                job_status[job_id].update(
                    {
                        "status": "completed",
                        "progress": 100,
                        "message": "Processing completed successfully",
                        "result_path": result_path,
                        "download_ready": True,
                        "completed_at": datetime.now().isoformat(),
                    }
                )

                # Store final status in Redis (like webhook mode does)
                try:
                    redis_client.hset(
                        f"job_status:{job_id}",
                        mapping={"data": json.dumps(job_status[job_id], default=str)},
                    )
                except Exception as e:
                    print(f"⚠️ Redis update failed: {e}")

                return jsonify(
                    {
                        "success": True,
                        "job_id": job_id,
                        "status": job_status[job_id],
                        "download_ready": True,
                    }
                )

            else:
                # Webhook mode: Send webhooks directly in main process (no worker to avoid macOS fork issues)
                try:
                    print(f"🔄 Webhook mode: Sending webhooks directly for {job_id}")
                    print(f"📄 Result file: {result_path}")
                    print(f"🔗 Webhook URL: {webhook_url}")

                    status_update = {
                        "status": "processing",
                        "progress": 80,
                        "message": "Phases complete, starting webhook delivery...",
                    }
                    job_status[job_id].update(status_update)

                    # Safe JSON serialization
                    try:
                        redis_client.hset(
                            f"job_status:{job_id}",
                            mapping={
                                "data": json.dumps(job_status[job_id], default=str)
                            },
                        )
                    except Exception as e:
                        print(f"⚠️ Redis update failed: {e}")

                    # Enqueue webhook sending to RQ worker (parallel processing)
                    from simple_worker import send_processed_data_webhook_sync

                    # Mark download ready and enqueue webhook job
                    job_status[job_id].update(
                        {
                            "status": "processing",
                            "progress": 80,
                            "message": "Queuing webhook delivery to worker...",
                            "result_path": result_path,
                            "download_ready": True,
                            "webhook_status": "queued",
                            "can_cancel": True,
                        }
                    )
                    # Safe JSON serialization
                    try:
                        redis_client.hset(
                            f"job_status:{job_id}",
                            mapping={
                                "data": json.dumps(job_status[job_id], default=str)
                            },
                        )
                    except Exception as e:
                        print(f"⚠️ Redis update failed: {e}")

                    # Read processed CSV and enqueue records data (not file path)
                    print(f"📤 Reading processed CSV and enqueueing data to RQ worker...")
                    
                    try:
                        # Read the processed CSV file into memory
                        import pandas as pd
                        
                        final_df = pd.read_csv(result_path)
                        records = final_df.to_dict("records")
                        
                        print(f"📊 Read {len(records)} records from CSV, enqueueing to worker...")
                        
                        # Enqueue job with records data (passed through Redis)
                        rq_job = job_queue.enqueue(
                            send_processed_data_webhook_sync,
                            app_job_id=job_id,
                            records=records,  # Pass data, not file path!
                            webhook_url=webhook_url,
                            rate_limit=rate_limit,
                            record_limit=record_limit,
                            table_type=table_type,
                            job_timeout='2h',  # Allow 2 hours for large jobs
                            result_ttl=86400,  # Keep result for 24 hours
                        )
                        
                        print(f"✅ Webhook job enqueued with ID: {rq_job.id} (data passed through Redis)")
                        
                        # Update job status with RQ job ID
                        job_status[job_id].update({
                            "webhook_status": "queued",
                            "rq_job_id": rq_job.id,
                            "message": f"Webhook job queued with {len(records)} records - worker will process in parallel"
                        })
                        
                        try:
                            redis_client.hset(
                                f"job_status:{job_id}",
                                mapping={
                                    "data": json.dumps(job_status[job_id], default=str)
                                },
                            )
                        except Exception as e:
                            print(f"⚠️ Redis update failed: {e}")
                    
                    except Exception as enqueue_error:
                        print(f"❌ Failed to enqueue webhook job: {enqueue_error}")
                        import traceback
                        traceback.print_exc()
                        job_status[job_id].update({
                            "status": "completed",
                            "progress": 100,
                            "message": f"Processing completed but webhook queueing failed: {str(enqueue_error)}",
                            "webhook_status": "failed",
                            "can_cancel": False,
                        })

                    # Return immediately - RQ worker will process webhooks in parallel
                    return jsonify(
                        {
                            "success": True,
                            "job_id": job_id,
                            "message": "Processing complete! Webhook delivery queued to worker.",
                            "status": job_status[job_id],
                            "download_ready": True,
                        }
                    )

                except Exception as webhook_error:
                    print(f"❌ Failed to send webhooks: {webhook_error}")
                    import traceback

                    traceback.print_exc()

                    # Still mark as completed even if webhook fails - download is still available
                    job_status[job_id].update(
                        {
                            "status": "completed",
                            "progress": 100,
                            "message": f"Processing completed but webhook failed: {str(webhook_error)}",
                            "result_path": result_path,
                            "completed_at": datetime.now().isoformat(),
                            "download_ready": True,
                            "webhook_status": "failed",
                            "can_cancel": False,
                        }
                    )
                    # Safe JSON serialization
                    try:
                        redis_client.hset(
                            f"job_status:{job_id}",
                            mapping={
                                "data": json.dumps(job_status[job_id], default=str)
                            },
                        )
                    except Exception as e:
                        print(f"⚠️ Redis update failed: {e}")

                    return jsonify(
                        {
                            "success": True,
                            "job_id": job_id,
                            "status": job_status[job_id],
                            "download_ready": True,
                            "warning": f"Webhook failed: {str(webhook_error)}",
                        }
                    )

        except Exception as e:
            job_status[job_id].update(
                {
                    "status": "failed",
                    "message": f"Processing failed: {str(e)}",
                    "error": str(e),
                }
            )
            return jsonify({"error": f"Processing failed: {str(e)}"}), 500

    except Exception as e:
        return jsonify({"error": f"Processing failed: {str(e)}"}), 500


@app.route("/api/status/<job_id>")
def get_job_status(job_id):
    """Get job status from Redis"""
    import json

    # Try to get from Redis first (worker updates)
    redis_data = redis_client.hget(f"job_status:{job_id}", "data")
    if redis_data:
        try:
            status_data = json.loads(redis_data)
            return jsonify({"success": True, "job_id": job_id, "status": status_data})
        except json.JSONDecodeError:
            pass

    # Fallback to local storage
    if job_id not in job_status:
        return jsonify({"error": "Job not found"}), 404

    return jsonify({"success": True, "job_id": job_id, "status": job_status[job_id]})


@app.route("/api/logs", methods=["GET"])
def get_logs():
    """
    Query logs with filters - accessible from Cursor/CLI
    
    Query parameters:
        start: Start date (ISO format or relative: '1d', '2d', '7d', 'yesterday', 'today')
        end: End date (ISO format, defaults to now)
        job_id: Filter by job ID
        level: Filter by log level (INFO, WARNING, ERROR, CRITICAL)
        error_type: Filter by error type
        limit: Max number of logs (default: 1000)
    
    Examples:
        /api/logs?start=yesterday
        /api/logs?start=2d&level=ERROR
        /api/logs?job_id=abc123
    """
    from src.log_collector import get_log_collector
    from datetime import datetime, timedelta, timezone
    
    try:
        log_collector = get_log_collector()
        
        # Parse parameters
        start_param = request.args.get("start")
        end_param = request.args.get("end")
        job_id = request.args.get("job_id")
        level = request.args.get("level")
        error_type = request.args.get("error_type")
        limit = int(request.args.get("limit", 1000))
        
        # Parse time parameters
        now = datetime.now(timezone.utc)
        end_time = now
        
        if end_param:
            try:
                end_time = datetime.fromisoformat(end_param.replace('Z', '+00:00'))
            except ValueError:
                return jsonify({"error": "Invalid end time format. Use ISO format."}), 400
        
        # Parse start time (support relative dates)
        if start_param:
            if start_param == "today":
                start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif start_param == "yesterday":
                start_time = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            elif start_param.endswith("d"):
                # Relative days (e.g., "2d" = 2 days ago)
                try:
                    days = int(start_param[:-1])
                    start_time = now - timedelta(days=days)
                except ValueError:
                    return jsonify({"error": "Invalid start time format"}), 400
            elif start_param.endswith("h"):
                # Relative hours (e.g., "24h" = 24 hours ago)
                try:
                    hours = int(start_param[:-1])
                    start_time = now - timedelta(hours=hours)
                except ValueError:
                    return jsonify({"error": "Invalid start time format"}), 400
            else:
                # ISO format
                try:
                    start_time = datetime.fromisoformat(start_param.replace('Z', '+00:00'))
                except ValueError:
                    return jsonify({"error": "Invalid start time format"}), 400
        else:
            # Default: last 7 days
            start_time = now - timedelta(days=7)
        
        # Query logs
        logs = log_collector.query_logs(
            start_time=start_time,
            end_time=end_time,
            job_id=job_id,
            level=level,
            error_type=error_type,
            limit=limit,
        )
        
        return jsonify({
            "success": True,
            "count": len(logs),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "filters": {
                "job_id": job_id,
                "level": level,
                "error_type": error_type,
            },
            "logs": logs,
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to fetch logs: {str(e)}"}), 500


@app.route("/api/logs/errors/summary", methods=["GET"])
def get_error_summary():
    """
    Get summary of errors by type
    
    Query parameters:
        start: Start date (same format as /api/logs)
        end: End date
        job_id: Filter by job ID
    """
    from src.log_collector import get_log_collector
    from datetime import datetime, timedelta, timezone
    
    try:
        log_collector = get_log_collector()
        
        # Parse parameters (same logic as get_logs)
        start_param = request.args.get("start")
        end_param = request.args.get("end")
        job_id = request.args.get("job_id")
        
        now = datetime.now(timezone.utc)
        end_time = now
        
        if end_param:
            end_time = datetime.fromisoformat(end_param.replace('Z', '+00:00'))
        
        if start_param:
            if start_param == "today":
                start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif start_param == "yesterday":
                start_time = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            elif start_param.endswith("d"):
                days = int(start_param[:-1])
                start_time = now - timedelta(days=days)
            elif start_param.endswith("h"):
                hours = int(start_param[:-1])
                start_time = now - timedelta(hours=hours)
            else:
                start_time = datetime.fromisoformat(start_param.replace('Z', '+00:00'))
        else:
            start_time = now - timedelta(days=7)
        
        # Get error summary
        error_summary = log_collector.get_error_summary(
            start_time=start_time,
            end_time=end_time,
            job_id=job_id,
        )
        
        return jsonify({
            "success": True,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "job_id": job_id,
            "error_counts": error_summary,
            "total_errors": sum(error_summary.values()),
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to fetch error summary: {str(e)}"}), 500


@app.route("/diagnostics", methods=["GET"])
def diagnostics_ui():
    """Beautiful UI for diagnostics with auto-refresh"""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CSV Merger Diagnostics</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            color: #333;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .header {
            background: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .header h1 {
            font-size: 32px;
            color: #667eea;
        }
        
        .refresh-info {
            text-align: right;
        }
        
        .refresh-countdown {
            font-size: 14px;
            color: #666;
        }
        
        .refresh-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            background: #4ade80;
            border-radius: 50%;
            margin-right: 8px;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .card {
            background: white;
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        .card h2 {
            font-size: 18px;
            margin-bottom: 20px;
            color: #667eea;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
        }
        
        .status-badge.connected {
            background: #dcfce7;
            color: #15803d;
        }
        
        .status-badge.busy {
            background: #fef3c7;
            color: #92400e;
        }
        
        .status-badge.idle {
            background: #dbeafe;
            color: #1e40af;
        }
        
        .status-badge.error {
            background: #fee2e2;
            color: #991b1b;
        }
        
        .info-row {
            display: flex;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid #f3f4f6;
        }
        
        .info-row:last-child {
            border-bottom: none;
        }
        
        .info-label {
            font-weight: 600;
            color: #6b7280;
        }
        
        .info-value {
            color: #111827;
            font-family: 'Courier New', monospace;
        }
        
        .progress-bar {
            width: 100%;
            height: 8px;
            background: #e5e7eb;
            border-radius: 4px;
            overflow: hidden;
            margin-top: 8px;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            transition: width 0.3s ease;
        }
        
        .worker-card {
            background: #f9fafb;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 10px;
        }
        
        .worker-card:last-child {
            margin-bottom: 0;
        }
        
        .job-table {
            width: 100%;
            margin-top: 15px;
        }
        
        .job-table th {
            text-align: left;
            padding: 10px;
            background: #f9fafb;
            font-weight: 600;
            color: #6b7280;
            border-bottom: 2px solid #e5e7eb;
        }
        
        .job-table td {
            padding: 10px;
            border-bottom: 1px solid #f3f4f6;
        }
        
        .empty-state {
            text-align: center;
            padding: 40px;
            color: #9ca3af;
        }
        
        .metric {
            text-align: center;
            padding: 15px;
        }
        
        .metric-value {
            font-size: 36px;
            font-weight: bold;
            color: #667eea;
        }
        
        .metric-label {
            font-size: 12px;
            color: #6b7280;
            text-transform: uppercase;
            margin-top: 5px;
        }
        
        code {
            background: #f3f4f6;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 13px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>🔍 System Diagnostics</h1>
                <p style="color: #666; margin-top: 5px;">Real-time monitoring dashboard</p>
            </div>
            <div class="refresh-info">
                <div class="refresh-countdown">
                    <span class="refresh-indicator"></span>
                    Auto-refresh in <strong id="countdown">5</strong>s
                </div>
                <div style="margin-top: 8px; font-size: 12px; color: #999;">
                    Last updated: <span id="timestamp">--</span>
                </div>
            </div>
        </div>
        
        <div id="content">
            <div style="text-align: center; padding: 60px; color: white;">
                <div style="font-size: 48px; margin-bottom: 20px;">⏳</div>
                <div style="font-size: 18px;">Loading diagnostics...</div>
            </div>
        </div>
    </div>
    
    <script>
        let countdownValue = 5;
        let countdownInterval;
        
        function updateCountdown() {
            countdownValue--;
            document.getElementById('countdown').textContent = countdownValue;
            if (countdownValue <= 0) {
                fetchDiagnostics();
                countdownValue = 5;
            }
        }
        
        function formatTimestamp(ts) {
            const date = new Date(ts);
            return date.toLocaleTimeString('en-US', { hour12: false });
        }
        
        function formatBytes(gb) {
            return gb.toFixed(1) + ' GB';
        }
        
        function formatUptime(seconds) {
            const days = Math.floor(seconds / 86400);
            const hours = Math.floor((seconds % 86400) / 3600);
            return `${days}d ${hours}h`;
        }
        
        async function fetchDiagnostics() {
            try {
                const response = await fetch('/api/diagnostics');
                const data = await response.json();
                renderDiagnostics(data.diagnostics);
                document.getElementById('timestamp').textContent = formatTimestamp(data.diagnostics.timestamp);
            } catch (error) {
                console.error('Failed to fetch diagnostics:', error);
            }
        }
        
        function renderDiagnostics(diag) {
            const content = document.getElementById('content');
            
            content.innerHTML = `
                <div class="grid">
                    <!-- Service Info -->
                    <div class="card">
                        <h2>🚀 Service Information</h2>
                        <div class="info-row">
                            <span class="info-label">Service Type</span>
                            <span class="info-value"><code>${diag.service_info.service_type}</code></span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Service Name</span>
                            <span class="info-value">${diag.service_info.railway_service_name}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Environment</span>
                            <span class="info-value">${diag.service_info.railway_environment}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Port</span>
                            <span class="info-value">${diag.service_info.port}</span>
                        </div>
                    </div>
                    
                    <!-- Redis Status -->
                    <div class="card">
                        <h2>💾 Redis Status <span class="status-badge ${diag.redis.status === 'connected' ? 'connected' : 'error'}">${diag.redis.status}</span></h2>
                        <div class="info-row">
                            <span class="info-label">Host</span>
                            <span class="info-value">${diag.redis.connection_info.host}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Port</span>
                            <span class="info-value">${diag.redis.connection_info.port}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Jobs Stored</span>
                            <span class="info-value">${diag.redis.job_count}</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Ops/sec</span>
                            <span class="info-value">${diag.redis.stats.instantaneous_ops_per_sec}</span>
                        </div>
                    </div>
                    
                    <!-- System Resources -->
                    <div class="card">
                        <h2>💻 System Resources</h2>
                        <div class="info-row">
                            <span class="info-label">CPU Usage</span>
                            <span class="info-value">${diag.system.cpu_percent}%</span>
                        </div>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${diag.system.cpu_percent}%"></div>
                        </div>
                        <div class="info-row" style="margin-top: 15px;">
                            <span class="info-label">Memory Usage</span>
                            <span class="info-value">${diag.system.memory.percent_used}%</span>
                        </div>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${diag.system.memory.percent_used}%"></div>
                        </div>
                        <div class="info-row" style="margin-top: 15px;">
                            <span class="info-label">Uptime</span>
                            <span class="info-value">${formatUptime(diag.system.uptime_seconds)}</span>
                        </div>
                    </div>
                </div>
                
                <!-- RQ Workers -->
                <div class="card" style="margin-bottom: 20px;">
                    <h2>⚙️ RQ Workers (${diag.rq_workers.workers_count} active)</h2>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px;">
                        <div class="metric">
                            <div class="metric-value">${diag.rq_workers.workers_count}</div>
                            <div class="metric-label">Workers</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">${diag.rq_workers.jobs_queued}</div>
                            <div class="metric-label">Jobs Queued</div>
                        </div>
                    </div>
                    
                    ${diag.rq_workers.workers.length > 0 ? diag.rq_workers.workers.map(worker => `
                        <div class="worker-card">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                                <strong style="color: #667eea;">Worker ${worker.name.substring(0, 8)}</strong>
                                <span class="status-badge ${worker.state === 'busy' ? 'busy' : 'idle'}">${worker.state}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">Successful</span>
                                <span class="info-value">${worker.successful_jobs}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">Failed</span>
                                <span class="info-value">${worker.failed_jobs}</span>
                            </div>
                            ${worker.current_job ? `
                                <div class="info-row">
                                    <span class="info-label">Current Job</span>
                                    <span class="info-value" style="font-size: 11px;">${worker.current_job.substring(0, 100)}...</span>
                                </div>
                            ` : ''}
                        </div>
                    `).join('') : '<div class="empty-state">No workers running</div>'}
                </div>
                
                <!-- Recent Jobs -->
                <div class="card" style="margin-bottom: 20px;">
                    <h2>📋 Recent Jobs (${diag.recent_jobs.count})</h2>
                    ${diag.recent_jobs.jobs.length > 0 ? `
                        <table class="job-table">
                            <thead>
                                <tr>
                                    <th>Job ID</th>
                                    <th>Status</th>
                                    <th>Progress</th>
                                    <th>Webhook Status</th>
                                    <th>Message</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${diag.recent_jobs.jobs.map(job => `
                                    <tr>
                                        <td><code style="font-size: 11px;">${job.job_id.substring(0, 13)}</code></td>
                                        <td><span class="status-badge ${job.status === 'completed' ? 'connected' : job.status === 'processing' ? 'busy' : 'idle'}">${job.status}</span></td>
                                        <td>${job.progress}%</td>
                                        <td><code>${job.webhook_status}</code></td>
                                        <td style="font-size: 12px; max-width: 300px; overflow: hidden; text-overflow: ellipsis;">${job.message}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    ` : '<div class="empty-state">No recent jobs in Redis</div>'}
                </div>
                
                <!-- File System -->
                <div class="card">
                    <h2>📁 File System</h2>
                    <div class="info-row">
                        <span class="info-label">Upload Folder</span>
                        <span class="info-value"><code>${diag.filesystem.upload_folder}</code></span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Writable</span>
                        <span class="info-value">${diag.filesystem.upload_folder_writable ? '✅ Yes' : '❌ No'}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Recent Jobs</span>
                        <span class="info-value">${diag.filesystem.recent_jobs.length} folders</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Disk Usage</span>
                        <span class="info-value">${formatBytes(diag.filesystem.disk_usage.used_gb)} / ${formatBytes(diag.filesystem.disk_usage.total_gb)}</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${diag.filesystem.disk_usage.percent_used}%"></div>
                    </div>
                </div>
            `;
        }
        
        // Start countdown
        countdownInterval = setInterval(updateCountdown, 1000);
        
        // Initial load
        fetchDiagnostics();
    </script>
</body>
</html>
    """


@app.route("/api/diagnostics", methods=["GET"])
def diagnostics():
    """Comprehensive diagnostic endpoint for troubleshooting (JSON API)"""
    import platform
    import psutil
    from datetime import datetime
    
    diagnostic_data = {
        "timestamp": datetime.now().isoformat(),
        "service_info": {},
        "filesystem": {},
        "redis": {},
        "rq_workers": {},
        "recent_jobs": {},
        "system": {},
    }
    
    # Service Information
    try:
        diagnostic_data["service_info"] = {
            "service_type": os.getenv("SERVICE_TYPE", "unknown"),
            "railway_environment": os.getenv("RAILWAY_ENVIRONMENT", "unknown"),
            "railway_service_name": os.getenv("RAILWAY_SERVICE_NAME", "unknown"),
            "railway_replica_id": os.getenv("RAILWAY_REPLICA_ID", "unknown"),
            "port": os.getenv("PORT", "unknown"),
            "redis_url": os.getenv("REDIS_URL", "not set")[:50] + "..." if os.getenv("REDIS_URL") else "not set",
        }
    except Exception as e:
        diagnostic_data["service_info"]["error"] = str(e)
    
    # File System Status
    try:
        upload_folder = app.config["UPLOAD_FOLDER"]
        diagnostic_data["filesystem"] = {
            "upload_folder": upload_folder,
            "upload_folder_exists": os.path.exists(upload_folder),
            "upload_folder_writable": os.access(upload_folder, os.W_OK) if os.path.exists(upload_folder) else False,
            "recent_jobs": [],
        }
        
        # Check recent jobs in upload folder
        if os.path.exists(upload_folder):
            job_folders = []
            for item in os.listdir(upload_folder):
                item_path = os.path.join(upload_folder, item)
                if os.path.isdir(item_path):
                    job_folders.append(item)
            
            # Get last 5 jobs
            job_folders.sort(key=lambda x: os.path.getmtime(os.path.join(upload_folder, x)), reverse=True)
            for job_id in job_folders[:5]:
                job_path = os.path.join(upload_folder, job_id)
                files_in_job = os.listdir(job_path)
                
                # Check for processed file
                processed_files = [f for f in files_in_job if f.startswith("processed_")]
                
                diagnostic_data["filesystem"]["recent_jobs"].append({
                    "job_id": job_id,
                    "path": job_path,
                    "file_count": len(files_in_job),
                    "has_processed_file": len(processed_files) > 0,
                    "processed_files": processed_files,
                    "modified": datetime.fromtimestamp(os.path.getmtime(job_path)).isoformat(),
                })
        
        # Disk usage
        disk = psutil.disk_usage(upload_folder if os.path.exists(upload_folder) else '/')
        diagnostic_data["filesystem"]["disk_usage"] = {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent_used": disk.percent,
        }
        
    except Exception as e:
        diagnostic_data["filesystem"]["error"] = str(e)
    
    # Redis Connectivity
    try:
        # Test Redis connection
        redis_client.ping()
        diagnostic_data["redis"]["status"] = "connected"
        diagnostic_data["redis"]["connection_info"] = {
            "host": redis_client.connection_pool.connection_kwargs.get("host", "unknown"),
            "port": redis_client.connection_pool.connection_kwargs.get("port", "unknown"),
            "db": redis_client.connection_pool.connection_kwargs.get("db", "unknown"),
        }
        
        # Get Redis info
        info = redis_client.info("stats")
        diagnostic_data["redis"]["stats"] = {
            "total_connections_received": info.get("total_connections_received", 0),
            "total_commands_processed": info.get("total_commands_processed", 0),
            "instantaneous_ops_per_sec": info.get("instantaneous_ops_per_sec", 0),
        }
        
        # Count job status keys
        job_keys = redis_client.keys("job_status:*")
        diagnostic_data["redis"]["job_count"] = len(job_keys)
        
    except Exception as e:
        diagnostic_data["redis"]["status"] = "error"
        diagnostic_data["redis"]["error"] = str(e)
    
    # RQ Workers Status
    try:
        from rq import Queue, Worker
        
        queue = Queue("csv_processing", connection=redis_client)
        workers = Worker.all(queue=queue)
        
        diagnostic_data["rq_workers"] = {
            "queue_name": "csv_processing",
            "jobs_queued": queue.count,
            "workers_count": len(workers),
            "workers": [],
        }
        
        for worker in workers:
            diagnostic_data["rq_workers"]["workers"].append({
                "name": worker.name,
                "state": worker.get_state(),
                "current_job": str(worker.get_current_job()) if worker.get_current_job() else None,
                "successful_jobs": worker.successful_job_count,
                "failed_jobs": worker.failed_job_count,
            })
        
    except Exception as e:
        diagnostic_data["rq_workers"]["error"] = str(e)
    
    # Recent Jobs Status (from Redis)
    try:
        job_keys = redis_client.keys("job_status:*")
        recent_jobs = []
        
        for key in job_keys[:10]:  # Last 10 jobs
            try:
                job_data = redis_client.hget(key, "data")
                if job_data:
                    job_info = json.loads(job_data)
                    recent_jobs.append({
                        "job_id": job_info.get("job_id", "unknown"),
                        "status": job_info.get("status", "unknown"),
                        "progress": job_info.get("progress", 0),
                        "message": job_info.get("message", ""),
                        "webhook_status": job_info.get("webhook_status", "none"),
                        "result_path": job_info.get("result_path", "none"),
                        "created_at": job_info.get("created_at", "unknown"),
                    })
            except Exception:
                pass
        
        diagnostic_data["recent_jobs"] = {
            "count": len(recent_jobs),
            "jobs": recent_jobs,
        }
        
    except Exception as e:
        diagnostic_data["recent_jobs"]["error"] = str(e)
    
    # System Information
    try:
        diagnostic_data["system"] = {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cpu_count": psutil.cpu_count(),
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory": {
                "total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
                "available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
                "percent_used": psutil.virtual_memory().percent,
            },
            "uptime_seconds": round(time.time() - psutil.boot_time(), 2),
        }
    except Exception as e:
        diagnostic_data["system"]["error"] = str(e)
    
    return jsonify({
        "success": True,
        "diagnostics": diagnostic_data,
    })


@app.route("/api/test-webhook", methods=["POST"])
def test_webhook():
    """Test webhook endpoint with sample data"""
    try:
        data = request.get_json()
        webhook_url = data.get("webhook_url")

        if not webhook_url:
            return jsonify({"error": "Webhook URL is required"}), 400

        # Create sample test data
        sample_data = {
            "test": True,
            "message": "This is a test webhook from CSV Merger",
            "timestamp": time.time(),
            "sample_records": [
                {
                    "First Name": "John",
                    "Last Name": "Doe",
                    "Work Email": "john.doe@example.com",
                    "Company Name": "Example Corp",
                    "Company Domain": "example.com",
                    "Job Title": "CEO",
                },
                {
                    "First Name": "Jane",
                    "Last Name": "Smith",
                    "Work Email": "jane.smith@testcompany.com",
                    "Company Name": "Test Company",
                    "Company Domain": "testcompany.com",
                    "Job Title": "CTO",
                },
            ],
            "total_sample_records": 2,
        }

        # Send test data to webhook
        import requests

        response = requests.post(
            webhook_url,
            json=sample_data,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

        if response.status_code == 200:
            return jsonify(
                {
                    "success": True,
                    "status": f"HTTP {response.status_code}",
                    "response_preview": (
                        response.text[:200] + "..."
                        if len(response.text) > 200
                        else response.text
                    ),
                }
            )
        else:
            return (
                jsonify(
                    {
                        "error": f"Webhook returned HTTP {response.status_code}: {response.text[:200]}"
                    }
                ),
                400,
            )

    except requests.exceptions.Timeout:
        return jsonify({"error": "Webhook request timed out"}), 408
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Could not connect to webhook URL"}), 502
    except Exception as e:
        print(f"❌ Webhook test error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/cancel/<job_id>", methods=["POST"])
def cancel_job(job_id):
    """Cancel a running job"""
    import json

    try:
        print(f"🛑 Cancel request for job {job_id}")

        # Set cancellation flag in Redis
        redis_client.hset(f"job_cancel:{job_id}", "cancelled", "true")

        # Update job status if it exists
        if job_id in job_status:
            job_status[job_id].update(
                {
                    "status": "cancelled",
                    "message": "Job cancelled by user",
                    "cancelled_at": datetime.now().isoformat(),
                    "can_cancel": False,
                }
            )

            try:
                redis_client.hset(
                    f"job_status:{job_id}",
                    mapping={"data": json.dumps(job_status[job_id], default=str)},
                )
            except Exception as e:
                print(f"⚠️ Redis update failed: {e}")

        return jsonify(
            {"success": True, "message": "Job cancellation requested", "job_id": job_id}
        )

    except Exception as e:
        print(f"❌ Cancel failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/download/<job_id>")
def download_result(job_id):
    """Download processed file"""
    import json

    # Try to get from Redis first (like status endpoint)
    job_info = None
    redis_data = redis_client.hget(f"job_status:{job_id}", "data")
    if redis_data:
        try:
            job_info = json.loads(redis_data)
        except json.JSONDecodeError:
            pass

    # Fallback to local storage
    if not job_info:
        if job_id not in job_status:
            return jsonify({"error": "Job not found"}), 404
        job_info = job_status[job_id]

    # Allow download if processing is complete (download_ready), even if webhooks are still sending
    if not job_info.get("download_ready", False):
        return jsonify({"error": "File not ready for download"}), 400

    if "result_path" not in job_info or not os.path.exists(job_info["result_path"]):
        return jsonify({"error": "Result file not found"}), 404

    return send_file(
        job_info["result_path"],
        as_attachment=True,
        download_name=f"processed_{job_id}.csv",
    )


@app.route("/health")
def health():
    """Health check"""
    redis_status = "unknown"
    redis_error = None

    try:
        # Test Redis connection
        redis_client.ping()
        redis_status = "connected"
    except Exception as e:
        redis_status = "disconnected"
        redis_error = str(e)

    # Always return 200 OK - app can function without Redis for basic operations
    return jsonify(
        {
            "status": "healthy",
            "redis": redis_status,
            "redis_error": redis_error,
            "timestamp": datetime.now().isoformat(),
            "app": "CSV Merger",
            "version": "1.0",
        }
    )


@app.route("/api/cleanup", methods=["POST"])
def manual_cleanup():
    """Manual cleanup endpoint"""
    try:
        max_age = request.json.get("max_age_hours", 24) if request.is_json else 24
        dry_run = request.json.get("dry_run", False) if request.is_json else False

        print(f"🧹 Manual cleanup triggered (max_age: {max_age}h, dry_run: {dry_run})")

        cleanup = UploadCleanup(uploads_dir="uploads", max_age_hours=max_age)
        stats = cleanup.clean_uploads(dry_run=dry_run)

        if "error" in stats:
            return jsonify({"success": False, "error": stats["error"]}), 500

        return jsonify(
            {
                "success": True,
                "message": f"Cleanup {'simulation' if dry_run else 'completed'}",
                "stats": stats,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def run_automatic_cleanup():
    """Run automatic cleanup of old upload files"""
    try:
        print("🧹 Running automatic upload cleanup...")
        cleanup = UploadCleanup(uploads_dir="uploads", max_age_hours=24)
        stats = cleanup.clean_uploads(dry_run=False)

        if "error" not in stats:
            deleted_count = stats["folders_deleted"] + stats["files_deleted"]
            if deleted_count > 0:
                print(
                    f"✅ Cleanup completed: {deleted_count} items deleted, {cleanup.format_size(stats['total_size_freed'])} freed"
                )
            else:
                print("✅ Cleanup completed: No old files to remove")
        else:
            print(f"❌ Cleanup failed: {stats['error']}")
    except Exception as e:
        print(f"❌ Cleanup error: {e}")


def start_background_cleanup():
    """Start background cleanup that runs periodically"""

    def cleanup_worker():
        while True:
            time.sleep(3600)  # Run every hour
            run_automatic_cleanup()

    # Run cleanup on startup
    run_automatic_cleanup()

    # Start background cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
    cleanup_thread.start()
    print("🕒 Background cleanup scheduled (runs every hour)")


if __name__ == "__main__":
    # Get port from environment (Railway sets this) - use 5002 as default per memory
    port = int(os.getenv("PORT", 5002))
    debug = os.getenv("FLASK_ENV") != "production"

    print("🚀 Starting CSV Merger (Simplified)")
    print("📁 Upload folder:", app.config["UPLOAD_FOLDER"])
    print(
        f"🔗 Redis connection: {redis_client.connection_pool.connection_kwargs.get('host', 'configured')}"
    )
    print(f"🌐 Server will start on: http://0.0.0.0:{port}")

    # Start automatic cleanup
    start_background_cleanup()
    app.run(host="0.0.0.0", port=port, debug=debug)
