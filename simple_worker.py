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
from src.log_collector import get_log_collector


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
    records=None,
    webhook_url=None,
    rate_limit=10,
    record_limit=None,
    table_type=None,
):
    """
    Send webhooks synchronously using records data passed through Redis.
    
    This worker function receives the actual data (not a file path), making it
    truly stateless and eliminating the need for shared storage between services.
    """

    # Validate required parameters
    if not app_job_id:
        raise ValueError("app_job_id is required")
    if not records:
        raise ValueError("records data is required")
    if not webhook_url:
        raise ValueError("webhook_url is required")
    if not table_type:
        raise ValueError("table_type is required")

    print(f"🚀 Worker processing webhook job {app_job_id}")
    print(
        f"📦 Parameters: webhook_url={webhook_url}, rate_limit={rate_limit}, record_limit={record_limit}, table_type={table_type}"
    )

    try:
        # Records are already in memory (passed through Redis)
        print(
            f"📊 Received {len(records)} processed records from Redis, sending webhooks..."
        )

        # Send via webhook with retry logic
        webhook_sender = WebhookSender(webhook_url, rate_limit, job_id=app_job_id)
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
            webhook_sender = WebhookSender(webhook_url, rate_limit, job_id=job_id)

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
    """Handles webhook delivery with retry logic and adaptive rate limiting"""

    def __init__(self, webhook_url: str, rate_limit: int = 10, job_id: Optional[str] = None):
        self.webhook_url = webhook_url
        self.config = Config()
        self.rate_limit = rate_limit  # requests per second
        self.delay_between_requests = 1.0 / rate_limit  # seconds between requests
        self.job_id = job_id  # Track job ID for logging
        
        # Adaptive rate limiting - detect and respond to throttling
        self.throttle_count = 0  # Count consecutive 429 errors
        self.original_rate_limit = rate_limit  # Store original rate
        self.is_throttled = False  # Track if we've reduced rate

    def _split_emails_to_columns(
        self, records: List[Dict], table_type: str
    ) -> List[Dict]:
        """
        Split multiple emails in a single field into numbered columns (Company Email 1, Company Email 2, etc.).
        Only applies to company table_type.
        
        Args:
            records: List of record dictionaries
            table_type: 'company' or 'people'
            
        Returns:
            List of records with emails split into numbered columns
        """
        if table_type != "company":
            return records  # Only process company records
        
        processed_records = []
        email_delimiters = [':', ',', ';', '|']  # Common delimiters for multiple emails
        
        for record in records:
            record_copy = record.copy()
            
            # Look for email fields (any field with 'email' in name)
            email_fields = [k for k in record.keys() if 'email' in k.lower()]
            
            # Collect all unique emails found across all email fields
            all_emails = []
            
            for email_field in email_fields:
                email_value = record.get(email_field)
                
                if email_value and isinstance(email_value, str) and email_value.strip():
                    # Check if this field contains multiple emails
                    contains_delimiter = any(delim in email_value for delim in email_delimiters)
                    
                    if contains_delimiter:
                        # Split by any of the delimiters
                        import re
                        split_emails = re.split(r'[;:,|\s]+', email_value)
                        # Clean and validate each email
                        for email in split_emails:
                            email = email.strip()
                            if email and '@' in email and email not in all_emails:  # Basic validation + dedup
                                all_emails.append(email)
                    elif '@' in email_value:  # Single email
                        clean_email = email_value.strip()
                        if clean_email not in all_emails:
                            all_emails.append(clean_email)
            
            # Add numbered email columns
            if all_emails:
                for idx, email in enumerate(all_emails, start=1):
                    record_copy[f"Company Email {idx}"] = email
                
                if len(all_emails) > 1:
                    print(f"📧 Split {len(all_emails)} emails into separate columns for record")
            
            processed_records.append(record_copy)
        
        return processed_records

    def send_records_batch(
        self,
        records: List[Dict],
        job_id: str,
        table_type: str,
        batch_size: int = 100,
        max_retries: int = 3,
    ) -> tuple:
        """Send each record as an individual webhook (not batched)"""
        
        # Split multiple emails into numbered columns (only for company type)
        records = self._split_emails_to_columns(records, table_type)
        
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
                record, record_num, max_retries, table_type, job_id
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
                progress = 80 + int((record_num / total_records) * 20)  # 80-100%
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
        self, record: Dict, record_num: int, max_retries: int, table_type: str, job_id: Optional[str] = None
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
                
                # Dynamically detect numbered company email fields (Company Email 1, Company Email 2, etc.)
                company_email_fields = {k for k in clean_record.keys() if k.startswith("Company Email ")}

                # Get all standard fields (union of person, company, metadata, and dynamic email fields)
                all_standard_fields = person_fields | company_fields | metadata_fields | company_email_fields

                # Extract additional fields (all fields NOT in the standard categories)
                additional_fields = {
                    k: v
                    for k, v in clean_record.items()
                    if k not in all_standard_fields and v is not None and v != ""
                }

                # Create payload based on table_type
                if table_type == "company":
                    # Company webhooks: Include company fields + numbered email fields + metadata + ALL additional fields
                    payload = {
                        **{
                            k: v
                            for k, v in clean_record.items()
                            if k in company_fields or k in metadata_fields or k in company_email_fields
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
                    # Success! Reset throttle counter
                    self.throttle_count = 0
                    return True
                    
                elif response.status_code == 429:
                    # Rate limited - implement adaptive rate limiting
                    self.throttle_count += 1
                    
                    # After 3 consecutive 429s, reduce rate limit
                    if self.throttle_count >= 3 and not self.is_throttled:
                        self.is_throttled = True
                        self.rate_limit = 5  # Drop to 5 req/sec
                        self.delay_between_requests = 1.0 / self.rate_limit
                        print(f"🚨 THROTTLING DETECTED! Reducing rate to {self.rate_limit} req/sec to avoid further 429s")
                    
                    print(f"⚠️ Record {record_num} attempt {attempt + 1}: HTTP 429 (Rate Limited)")
                    
                    # For 429, use SHORT fixed delay (no exponential backoff)
                    if attempt < max_retries - 1:
                        time.sleep(0.5)  # Just 500ms wait
                        continue  # Retry immediately after short wait
                    
                else:
                    # Other non-200 responses
                    error_type = f"HTTP_{response.status_code}"
                    print(
                        f"⚠️ Record {record_num} attempt {attempt + 1}: HTTP {response.status_code}"
                    )
                    
                    # Log to structured logger (on final attempt)
                    if attempt == max_retries - 1:
                        try:
                            log_collector = get_log_collector()
                            log_collector.log(
                                level="ERROR",
                                message=f"Webhook failed for record {record_num} after {max_retries} attempts: HTTP {response.status_code}",
                                job_id=job_id or self.job_id,
                                error_type=error_type,
                                record_number=record_num,
                                metadata={
                                    "status_code": response.status_code,
                                    "response_text": response.text[:500] if response.text else None,
                                    "webhook_url": self.webhook_url,
                                },
                            )
                        except Exception as log_err:
                            print(f"⚠️ Failed to log error: {log_err}")

            except Exception as e:
                error_msg = str(e)
                print(f"⚠️ Record {record_num} attempt {attempt + 1} failed: {e}")
                
                # Log exception (on final attempt)
                if attempt == max_retries - 1:
                    try:
                            log_collector = get_log_collector()
                            log_collector.log(
                                level="ERROR",
                                message=f"Webhook exception for record {record_num} after {max_retries} attempts: {error_msg}",
                                job_id=job_id or self.job_id,
                                error_type="EXCEPTION",
                                record_number=record_num,
                                metadata={
                                    "exception_type": type(e).__name__,
                                    "exception_message": error_msg,
                                    "webhook_url": self.webhook_url,
                                },
                            )
                    except Exception as log_err:
                        print(f"⚠️ Failed to log error: {log_err}")

            # Exponential backoff with jitter (for non-429 errors)
            # Note: 429 errors use short fixed delay (handled above with 'continue')
            if attempt < max_retries - 1:
                # Base delay: 1s, 2s, 4s (for server errors, exceptions, etc.)
                base_delay = (2**attempt) * 1
                # Add small random jitter (±20%) to prevent thundering herd
                import random
                jitter = random.uniform(0.8, 1.2)
                wait_time = base_delay * jitter
                print(f"⏳ Retrying record {record_num} in {wait_time:.1f}s...")
                time.sleep(wait_time)

        # All retries exhausted - this webhook failed
        return False


if __name__ == "__main__":
    print("🔧 Simple Worker ready for webhook processing")
    print("Use: rq worker csv_processing")
