"""
Simple Worker - Webhook Processing Only
Handles background webhook sending with retry logic for high volume
"""

import json
import os
import time
from typing import Dict, List, Optional

import pandas as pd
import requests
# Redis-based job status storage (shared with main app)
from redis import Redis

from simple_config import Config
from simple_csv_processor import CSVProcessor


def get_redis_config():
    """Get Redis configuration from environment variables (same as main app)"""
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        # Railway Redis addon provides REDIS_URL
        return Redis.from_url(redis_url)
    else:
        # Fallback to localhost for development
        return Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=int(os.getenv("REDIS_DB", 0)),
        )


redis_client = get_redis_config()
job_status = {}


def send_processed_data_webhook_sync(
    app_job_id=None,
    result_path=None,
    webhook_url=None,
    rate_limit=5,
    record_limit=None,
    table_type=None,
):
    """Send webhooks synchronously in main process (no forking issues)"""

    # Validate required parameters
    if not app_job_id:
        raise ValueError("app_job_id is required")
    if not result_path:
        raise ValueError("result_path is required")
    if not webhook_url:
        raise ValueError("webhook_url is required")
    if not table_type:
        raise ValueError("table_type is required")

    print(f"🚀 Sending webhooks directly for job {app_job_id}")
    print(
        f"📦 Parameters: result_path={result_path}, webhook_url={webhook_url}, rate_limit={rate_limit}, record_limit={record_limit}, table_type={table_type}"
    )

    try:
        # Read the already-processed CSV file
        import os

        import pandas as pd

        if not os.path.exists(result_path):
            raise FileNotFoundError(f"Processed file not found: {result_path}")

        final_df = pd.read_csv(result_path)
        records = final_df.to_dict("records")

        print(
            f"📊 Loaded {len(records)} processed records, sending individual webhooks..."
        )

        # Send via webhook with retry logic
        webhook_sender = WebhookSender(webhook_url, rate_limit)
        success_count, failed_count = webhook_sender.send_records_batch(
            records=records,
            job_id=app_job_id,
            table_type=table_type,
            batch_size=1,  # Not used anymore
            max_retries=3,
        )

        print(
            f"✅ Job {app_job_id} completed: {success_count} sent, {failed_count} failed"
        )
        return success_count, failed_count

    except Exception as e:
        print(f"❌ Job {app_job_id} failed: {e}")
        return 0, 1


def process_job(
    job_id, file_paths, webhook_url, table_type, rate_limit=5, record_limit=None
):
    """Process CSV files using EXACT SAME pipeline as download mode, then send webhook"""
    print(f"🚀 Worker started for job {job_id}")

    try:
        # Update job status
        update_job_status(job_id, "processing", 5, "Starting processing...")

        # Use the EXACT SAME processor and method as download mode
        processor = CSVProcessor()

        # Create temporary output directory (won't be used but required by method)
        import os
        import tempfile

        temp_dir = tempfile.mkdtemp()

        try:
            # Call the EXACT SAME method that download mode uses
            print("🔄 Using same processing pipeline as download mode...")
            update_job_status(
                job_id, "processing", 10, "Processing files (same as download)..."
            )

            result_path = processor.process_files_sync(
                file_paths=file_paths,
                job_id=job_id,
                table_type=table_type,
                output_dir=temp_dir,
                record_limit=record_limit,  # Apply record limit during processing
            )

            # Read the processed file to get records for webhook
            update_job_status(job_id, "processing", 70, "Preparing webhook data...")
            import pandas as pd

            final_df = pd.read_csv(result_path)
            records = final_df.to_dict("records")

            print(
                f"📊 Processed {len(records)} records using same pipeline as download, preparing webhook delivery..."
            )

        finally:
            # Clean up temp directory
            import shutil

            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

        # Send via webhook with retry logic and better error handling
        update_job_status(job_id, "processing", 80, "Sending webhook...")

        try:
            webhook_sender = WebhookSender(webhook_url, rate_limit)

            success_count, failed_count = webhook_sender.send_records_batch(
                records=records,
                job_id=job_id,
                table_type=table_type,
                batch_size=100,  # Send in batches of 100
                max_retries=3,
            )

            # Update final status - SUCCESS
            update_job_status(
                job_id,
                "completed",
                100,
                f"Completed! Sent {success_count} records, {failed_count} failed",
            )

        except Exception as webhook_error:
            # Even if webhook fails, mark job as completed with warning
            print(f"⚠️ Webhook sending failed: {webhook_error}")
            update_job_status(
                job_id,
                "completed",
                100,
                f"Processing completed but webhook failed: {str(webhook_error)}",
            )

        print(f"✅ Job {job_id} completed: {success_count} sent, {failed_count} failed")

    except Exception as e:
        error_msg = f"Job failed: {str(e)}"
        print(f"❌ Job {job_id} failed: {e}")
        update_job_status(job_id, "failed", 0, error_msg)
        raise


def update_job_status(job_id: str, status: str, progress: int, message: str):
    """Update job status in Redis storage (shared with main app) - preserve existing fields"""
    import json

    # Get existing data to preserve fields like can_cancel, download_ready, etc.
    existing_data = {}
    try:
        existing_redis_data = redis_client.hget(f"job_status:{job_id}", "data")
        if existing_redis_data:
            existing_data = json.loads(existing_redis_data)
    except Exception as e:
        print(f"⚠️ Could not load existing status: {e}")

    # Update only the changing fields, preserve everything else
    status_update = {
        "status": status,
        "progress": progress,
        "message": message,
        "updated_at": time.time(),
    }

    # Merge with existing data to preserve can_cancel, download_ready, etc.
    merged_data = {**existing_data, **status_update}

    # Store in Redis for sharing with main app
    try:
        redis_client.hset(
            f"job_status:{job_id}",
            mapping={"data": json.dumps(merged_data, default=str)},
        )
    except Exception as e:
        print(f"⚠️ Redis update failed: {e}")

    # Also store locally for quick access
    job_status[job_id] = merged_data

    print(f"📊 Job {job_id}: {status} ({progress}%) - {message}")


def update_job_status_with_time(
    job_id: str,
    status: str,
    progress: int,
    message: str,
    estimated_seconds_remaining=None,
    webhooks_sent=None,
    webhooks_total=None,
):
    """Update job status with estimated time information"""
    import json

    # Get existing data to preserve fields like can_cancel, download_ready, etc.
    existing_data = {}
    try:
        existing_redis_data = redis_client.hget(f"job_status:{job_id}", "data")
        if existing_redis_data:
            existing_data = json.loads(existing_redis_data)
    except Exception as e:
        print(f"⚠️ Could not load existing status: {e}")

    # Update with timing information
    status_update = {
        "status": status,
        "progress": progress,
        "message": message,
        "updated_at": time.time(),
    }

    # Add timing data if provided
    if estimated_seconds_remaining is not None:
        status_update["estimated_seconds_remaining"] = estimated_seconds_remaining
        status_update["estimated_completion_time"] = (
            time.time() + estimated_seconds_remaining
        )

    if webhooks_sent is not None:
        status_update["webhooks_sent"] = webhooks_sent
        status_update["webhooks_total"] = webhooks_total

    # Merge with existing data
    merged_data = {**existing_data, **status_update}

    # Store in Redis
    try:
        redis_client.hset(
            f"job_status:{job_id}",
            mapping={"data": json.dumps(merged_data, default=str)},
        )
    except Exception as e:
        print(f"⚠️ Redis update failed: {e}")

    # Also store locally
    job_status[job_id] = merged_data

    print(f"📊 Job {job_id}: {status} ({progress}%) - {message}")


class WebhookSender:
    """Handles webhook delivery with retry logic and rate limiting"""

    def __init__(self, webhook_url: str, rate_limit: int = 5):
        self.webhook_url = webhook_url
        self.config = Config()
        self.rate_limit = rate_limit  # requests per second
        self.delay_between_requests = 1.0 / rate_limit  # seconds between requests

    def send_records_batch(
        self,
        records: List[Dict],
        job_id: str,
        table_type: str,
        batch_size: int = 100,
        max_retries: int = 3,
    ) -> tuple:
        """Send each record as an individual webhook (not batched)"""
        success_count = 0
        failed_count = 0
        total_records = len(records)

        # Start timing for estimated completion calculation
        start_time = time.time()
        webhook_times = []  # Track individual webhook times for better estimation

        print(f"📡 Sending {total_records} individual webhooks (one per record)")

        for i, record in enumerate(records):
            record_num = i + 1
            webhook_start = time.time()  # Track this webhook's start time

            # Check for cancellation
            if self._is_job_cancelled(job_id):
                print(
                    f"🛑 Job {job_id} cancelled at webhook {record_num}/{total_records}"
                )
                update_job_status(
                    job_id,
                    "cancelled",
                    100,
                    f"Cancelled after sending {success_count} webhooks",
                )
                return success_count, failed_count

            print(f"📤 Sending webhook {record_num}/{total_records}")

            # Send individual record with retry
            webhook_success = self._send_individual_record_with_retry(
                record, record_num, max_retries, table_type
            )
            webhook_end = time.time()

            # Track webhook timing
            webhook_duration = webhook_end - webhook_start
            webhook_times.append(webhook_duration)

            if webhook_success:
                success_count += 1
                print(f"✅ Webhook {record_num} sent successfully")
            else:
                failed_count += 1
                print(f"❌ Webhook {record_num} failed after {max_retries} retries")

            # Calculate estimated time remaining
            if len(webhook_times) >= 3:  # Need at least 3 samples for good estimate
                avg_time_per_webhook = sum(webhook_times[-10:]) / len(
                    webhook_times[-10:]
                )  # Use last 10 for better accuracy
                records_remaining = total_records - record_num
                estimated_seconds_remaining = records_remaining * avg_time_per_webhook
            else:
                # Not enough data yet, estimate based on rate limit
                estimated_seconds_remaining = (
                    total_records - record_num
                ) / self.rate_limit

            # Update progress with estimated time
            try:
                progress = 80 + int((record_num / total_records) * 15)  # 80-95%
                message = (
                    f"Sending webhooks"  # Simple message, let frontend add details
                )

                # Add estimated time to status update
                update_job_status_with_time(
                    job_id,
                    "processing",
                    progress,
                    message,
                    estimated_seconds_remaining=estimated_seconds_remaining,
                    webhooks_sent=record_num,
                    webhooks_total=total_records,
                )
            except Exception as e:
                print(f"⚠️ Could not update status: {e}")

            # Rate limiting (configurable delay between individual webhooks)
            if record_num < total_records:
                time.sleep(self.delay_between_requests)

        return success_count, failed_count

    def _is_job_cancelled(self, job_id: str) -> bool:
        """Check if job has been cancelled"""
        try:
            cancelled = redis_client.hget(f"job_cancel:{job_id}", "cancelled")
            return (
                cancelled == b"true"
                if isinstance(cancelled, bytes)
                else cancelled == "true"
            )
        except Exception as e:
            print(f"⚠️ Cancel check failed: {e}")
            return False

    def _send_individual_record_with_retry(
        self, record: Dict, record_num: int, max_retries: int, table_type: str
    ) -> bool:
        """Send a single record as individual webhook with retry logic"""
        for attempt in range(max_retries):
            try:
                # Clean the record to ensure JSON serialization works
                clean_record = {}
                for key, value in record.items():
                    # Fix LinkedIn header issue: "Linked In" -> "LinkedIn"
                    normalized_key = key
                    if "Linked In" in key:
                        normalized_key = key.replace("Linked In", "LinkedIn")
                        if record_num == 1:  # Only log once to avoid spam
                            print(f"🔧 Fixed header: '{key}' -> '{normalized_key}'")

                    # Convert pandas/numpy types to native Python types
                    if pd.isna(value) or value is None:
                        clean_record[normalized_key] = None
                    elif isinstance(value, (int, float, str, bool)):
                        clean_record[normalized_key] = value
                    else:
                        clean_record[normalized_key] = str(
                            value
                        )  # Convert everything else to string

                # Define field categories
                person_fields = {
                    "First Name",
                    "Last Name",
                    "Full Name",
                    "Job Title",
                    "LinkedIn Profile",
                    "Person Location",
                    "Work Email",
                    "Personal Email",
                    "Phone Number",
                }

                company_fields = {
                    "Company Name",
                    "Company Domain",
                    "Company Description",
                    "Company Industry",
                    "Company Employee Count",
                    "Company LinkedIn",
                    "Year Founded",
                    "Company Location",
                }

                metadata_fields = {"Source"}

                # Get all standard fields (union of person, company, and metadata fields)
                all_standard_fields = person_fields | company_fields | metadata_fields

                # Extract additional fields (all fields NOT in the standard categories)
                additional_fields = {
                    k: v
                    for k, v in clean_record.items()
                    if k not in all_standard_fields and v is not None and v != ""
                }

                # Create payload based on table_type
                if table_type == "company":
                    # Company webhooks: Include company fields + metadata + ALL additional fields
                    payload = {
                        **{
                            k: v
                            for k, v in clean_record.items()
                            if k in company_fields or k in metadata_fields
                        },
                        "additional_fields": additional_fields,  # Include ALL unmapped fields
                        "_metadata": {
                            "record_number": record_num,
                            "timestamp": time.time(),
                            "source": "CSV Merger",
                            "total_additional_fields": len(additional_fields),
                        },
                    }

                elif table_type == "people":
                    # People webhooks: Nested structure with person and company objects + ALL additional fields
                    person_data = {
                        k: v for k, v in clean_record.items() if k in person_fields
                    }
                    company_data = {
                        k: v for k, v in clean_record.items() if k in company_fields
                    }

                    payload = {
                        "person": person_data,
                        "company": company_data,
                        **{
                            k: v
                            for k, v in clean_record.items()
                            if k in metadata_fields
                        },
                        "additional_fields": additional_fields,  # Include ALL unmapped fields
                        "_metadata": {
                            "record_number": record_num,
                            "timestamp": time.time(),
                            "source": "CSV Merger",
                            "total_additional_fields": len(additional_fields),
                        },
                    }
                else:
                    # Fallback: include all fields (for backward compatibility)
                    payload = {
                        **clean_record,  # Spread the record fields directly into payload
                        "_metadata": {
                            "record_number": record_num,
                            "timestamp": time.time(),
                            "source": "CSV Merger",
                        },
                    }

                import requests

                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=30,
                )

                if response.status_code == 200:
                    return True
                else:
                    print(
                        f"⚠️ Record {record_num} attempt {attempt + 1}: HTTP {response.status_code}"
                    )

            except Exception as e:
                print(f"⚠️ Record {record_num} attempt {attempt + 1} failed: {e}")

            # Exponential backoff
            if attempt < max_retries - 1:
                wait_time = (2**attempt) * 1  # 1s, 2s, 4s
                print(f"⏳ Retrying record {record_num} in {wait_time}s...")
                time.sleep(wait_time)

        return False


if __name__ == "__main__":
    print("🔧 Simple Worker ready for webhook processing")
    print("Use: rq worker csv_processing")
