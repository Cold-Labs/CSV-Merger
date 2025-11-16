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
        rate_limit = data.get("rate_limit", 20)  # requests per second (default: 20 for better performance)
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

                    # Enqueue webhook job to RQ worker (non-blocking)
                    print(f"📤 Enqueuing webhook job for {job_id} to RQ worker...")
                    
                    try:
                        rq_job = job_queue.enqueue(
                            send_processed_data_webhook_sync,
                            app_job_id=job_id,
                            result_path=result_path,
                            webhook_url=webhook_url,
                            rate_limit=rate_limit,
                            record_limit=record_limit,
                            table_type=table_type,
                            job_timeout='2h',  # Allow 2 hours for large jobs
                            result_ttl=86400,  # Keep result for 24 hours
                        )
                        
                        print(f"✅ Webhook job enqueued with ID: {rq_job.id}")
                        
                        # Update job status with RQ job ID
                        job_status[job_id].update({
                            "webhook_status": "queued",
                            "rq_job_id": rq_job.id,
                            "message": "Webhook job queued - worker will process in parallel"
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
