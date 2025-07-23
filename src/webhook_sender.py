import time
import json
import logging
import asyncio
import aiohttp
import requests
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
import math
import random

from src.logging_config import setup_module_logger
logger = setup_module_logger(__name__)

@dataclass
class WebhookConfig:
    """Configuration for webhook sending"""
    url: str
    rate_limit: int = 10  # requests per second
    retry_attempts: int = 3
    retry_backoff: List[int] = None  # [1, 3, 9] seconds
    timeout: int = 30
    verify_ssl: bool = True
    
    def __post_init__(self):
        if self.retry_backoff is None:
            self.retry_backoff = [1, 3, 9]
        # Ensure rate_limit is an integer
        self.rate_limit = int(self.rate_limit) if self.rate_limit is not None else 10

class TokenBucket:
    """Token bucket for rate limiting"""
    
    def __init__(self, rate_limit: int, bucket_size: Optional[int] = None):
        """
        Initialize token bucket
        
        Args:
            rate_limit: Tokens per second (0 means unlimited)
            bucket_size: Maximum tokens in bucket (defaults to rate_limit)
        """
        # Ensure rate_limit is an integer
        self.rate_limit = int(rate_limit) if rate_limit is not None else 10
        self.bucket_size = bucket_size or max(self.rate_limit, 1)
        self.tokens = float(self.bucket_size)  # Ensure tokens is a float for calculations
        self.last_update = time.time()
        self.unlimited = self.rate_limit == 0
    
    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens from bucket
        
        Args:
            tokens: Number of tokens to consume
            
        Returns:
            True if tokens were consumed, False if not available
        """
        if self.unlimited:
            return True
        
        # Ensure tokens parameter is a number
        tokens = float(tokens)
        
        now = time.time()
        # Add tokens based on elapsed time
        elapsed = now - self.last_update
        self.tokens = min(float(self.bucket_size), self.tokens + elapsed * self.rate_limit)
        self.last_update = now
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
    
    def wait_time(self, tokens: int = 1) -> float:
        """
        Calculate wait time for tokens to be available
        
        Args:
            tokens: Number of tokens needed
            
        Returns:
            Seconds to wait
        """
        if self.unlimited:
            return 0
        
        # Ensure tokens parameter is a number
        tokens = float(tokens)
        
        if self.tokens >= tokens:
            return 0
        
        needed_tokens = tokens - self.tokens
        return needed_tokens / self.rate_limit
    
    def update_rate(self, new_rate: int):
        """Update rate limit dynamically"""
        # Ensure new_rate is an integer
        self.rate_limit = int(new_rate) if new_rate is not None else 10
        self.unlimited = self.rate_limit == 0
        if not self.unlimited:
            self.bucket_size = max(self.rate_limit, 1)
            self.tokens = min(self.tokens, float(self.bucket_size))

class WebhookSender:
    """Handles webhook delivery with intelligent retry and rate limiting"""
    
    def _format_record(self, record: Dict[str, Any], table_type: str = 'people') -> Dict[str, Any]:
        """
        Format record according to standardized schema with flat structure
        
        Args:
            record: Raw record data
            table_type: 'people' or 'company'
            
        Returns:
            Formatted record data (flat structure for better webhook compatibility)
        """
        def clean_value(value: Any) -> str:
            """Clean and normalize a value"""
            if value is None:
                return ""
            str_value = str(value).strip()
            # Remove common empty indicators
            if str_value.lower() in ['', 'nan', 'null', 'none', 'n/a', '#n/a']:
                return ""
            return str_value
        
        if table_type == 'people':
            formatted_record = {
                # Person fields
                "first_name": clean_value(record.get("First Name", "")),
                "last_name": clean_value(record.get("Last Name", "")),
                "full_name": clean_value(record.get("Full Name", "")),
                "job_title": clean_value(record.get("Job Title", "")),
                "linkedin_profile": clean_value(record.get("LinkedIn Profile", "")),
                "person_location": clean_value(record.get("Person Location", "")),
                "work_email": clean_value(record.get("Work Email", "")),
                "personal_email": clean_value(record.get("Personal Email", "")),
                "phone_number": clean_value(record.get("Phone Number", "")),
                
                # Company fields (flat structure)
                "company_name": clean_value(record.get("Company Name", "")),
                "company_domain": clean_value(record.get("Company Domain", "")),
                "company_description": clean_value(record.get("Company Description", "")),
                "company_website": clean_value(record.get("Company Website", "")),
                "company_linkedin_url": clean_value(record.get("Company LinkedIn URL", "")),
                "company_linkedin": clean_value(record.get("Company LinkedIn", "")),
                "company_employee_count": clean_value(record.get("Company Employee Count", "")),
                "company_location": clean_value(record.get("Company Location", "")),
                "company_industry": clean_value(record.get("Company Industry", "")),
                "year_founded": clean_value(record.get("Year Founded", "")),
                
                # Metadata
                "source": clean_value(record.get("Source", "")),
                "table_type": "people"
            }
        else:  # company type
            formatted_record = {
                "company_name": clean_value(record.get("Company Name", "")),
                "company_domain": clean_value(record.get("Company Domain", "")),
                "company_description": clean_value(record.get("Company Description", "")),
                "company_industry": clean_value(record.get("Company Industry", "")),
                "company_employee_count": clean_value(record.get("Company Employee Count", "")),
                "company_linkedin": clean_value(record.get("Company LinkedIn", "")),
                "company_linkedin_handle": clean_value(record.get("Company LinkedIn Handle", "")),
                "year_founded": clean_value(record.get("Year Founded", "")),
                "company_location": clean_value(record.get("Company Location", "")),
                "source": clean_value(record.get("Source", "")),
                "table_type": "company"
            }
        
        # Filter out completely empty values to reduce payload size and improve data quality
        filtered_record = {k: v for k, v in formatted_record.items() if v != ""}
        
        logger.debug(f"Formatted record: {len(filtered_record)} non-empty fields out of {len(formatted_record)} total fields")
        return filtered_record

    def __init__(self, config: WebhookConfig, progress_callback: Optional[Callable] = None, table_type: str = 'people'):
        """
        Initialize webhook sender
        
        Args:
            config: Webhook configuration
            progress_callback: Optional callback for progress updates
            table_type: 'people' or 'company'
        """
        self.config = config
        self.progress_callback = progress_callback
        self.table_type = table_type
        logger.info(f"WEBHOOK DEBUG: Creating TokenBucket with rate_limit={config.rate_limit} (type: {type(config.rate_limit)})")
        self.token_bucket = TokenBucket(config.rate_limit)
        
        # Enhanced statistics
        self.stats = {
            'total_records': 0,
            'sent_successfully': 0,
            'failed_records': 0,
            'retry_attempts': 0,
            'total_requests': 0,
            'start_time': None,
            'end_time': None,
            'current_rate': 0,
            'avg_response_time': 0,
            'stage': 'initialized',  # New: Track webhook stage
            'status': 'pending',     # New: Track webhook status
            'last_error': None,      # New: Track last error
            'consecutive_failures': 0 # New: Track consecutive failures
        }
        
        # Failed records for retry with enhanced error tracking
        self.failed_records = []
        
        logger.info(f"Webhook sender initialized for {config.url} (table_type: {table_type})")

    def _update_avg_response_time(self, response_time: float):
        """Update average response time with exponential moving average"""
        if self.stats['avg_response_time'] == 0:
            self.stats['avg_response_time'] = response_time
        else:
            # Exponential moving average with alpha = 0.1
            alpha = 0.1
            self.stats['avg_response_time'] = (alpha * response_time + 
                                             (1 - alpha) * self.stats['avg_response_time'])
    
    def _calculate_current_rate(self) -> float:
        """Calculate current sending rate"""
        if self.stats['start_time'] and self.stats['total_requests'] > 0:
            elapsed = time.time() - self.stats['start_time']
            if elapsed > 0:
                return self.stats['total_requests'] / elapsed
        return 0

    def update_rate_limit(self, new_rate: int):
        """
        Update rate limit dynamically during sending
        
        Args:
            new_rate: New rate limit (requests per second, 0 for unlimited)
        """
        old_rate = self.config.rate_limit
        self.config.rate_limit = new_rate
        self.token_bucket.update_rate(new_rate)
        
        logger.info(f"Rate limit updated: {old_rate} -> {new_rate} requests/second")
        self._update_progress(f"Rate limit updated to {new_rate} req/sec")
    
    def _update_progress(self, message: str, percentage: float = None, stats: Dict = None):
        """Update progress via callback if available"""
        if self.progress_callback:
            progress_data = {
                'message': message,
                'percentage': percentage,
                'stats': stats or self.stats,
                'webhook_stats': {
                    'current_rate': self.stats['current_rate'],
                    'rate_limit': self.config.rate_limit,
                    'sent': self.stats['sent_successfully'],
                    'failed': self.stats['failed_records'],
                    'total': self.stats['total_records'],
                    'stage': self.stats['stage'],        # New: Include stage
                    'status': self.stats['status'],      # New: Include status
                    'last_error': self.stats['last_error'] # New: Include last error
                }
            }
            self.progress_callback(**progress_data)
        
        logger.info(f"Webhook progress: {message} ({percentage}%)" if percentage else f"Webhook progress: {message}")
    
    async def prepare_records(self, records: List[Dict[str, Any]], webhook_limit: int = 0) -> bool:
        """
        First step of two-step process - prepare records for sending
        
        Args:
            records: List of records to prepare
            webhook_limit: Optional limit on records to send (0 = no limit)
            
        Returns:
            True if preparation successful
        """
        try:
            self.stats['stage'] = 'preparing'
            self.stats['status'] = 'processing'
            self.stats['total_records'] = len(records)
            self.stats['is_test'] = webhook_limit > 0  # Mark as test if limit is set
            
            # Validate webhook URL before proceeding
            if not await self._validate_webhook_url_async():
                self.stats['stage'] = 'failed'
                self.stats['status'] = 'failed'
                self.stats['last_error'] = 'Webhook URL validation failed'
                self._update_progress(
                    'Webhook URL validation failed',
                    0,
                    {'error': 'Failed to validate webhook URL'}
                )
                return False
            
            self._update_progress(
                f'Prepared {len(records)} records for webhook delivery',
                100,
                {'stage': 'prepared', 'records': len(records)}
            )
            
            self.stats['stage'] = 'prepared'
            self.stats['status'] = 'ready'
            return True
            
        except Exception as e:
            self.stats['stage'] = 'failed'
            self.stats['status'] = 'failed'
            self.stats['last_error'] = str(e)
            self._update_progress(
                f'Failed to prepare records: {str(e)}',
                0,
                {'error': str(e)}
            )
            return False

    async def _validate_webhook_url_async(self) -> bool:
        """
        Validate webhook URL with a small POST request
        
        Returns:
            True if webhook is reachable and responds correctly
        """
        try:
            # Send a minimal validation payload
            validation_payload = {
                'test': True,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'validation': True,  # Indicate this is a validation request
                'message': 'Validating webhook URL before sending records'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.config.url,
                    json=validation_payload,
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout),
                    ssl=self.config.verify_ssl
                ) as response:
                    if 200 <= response.status < 300:
                        logger.info(f"Webhook validation successful: {response.status}")
                        return True
                    else:
                        logger.warning(f"Webhook validation failed: {response.status}")
                        return False
                    
        except Exception as e:
            logger.error(f"Webhook validation error: {e}")
            return False

    async def send_record_async(self, session: aiohttp.ClientSession, record: Dict[str, Any], record_index: int) -> bool:
        """
        Send single record via webhook asynchronously with enhanced error handling
        
        Args:
            session: aiohttp session
            record: Record data to send
            record_index: Index of record for progress tracking
            
        Returns:
            True if sent successfully, False otherwise
        """
        # Wait for rate limiting
        while not self.token_bucket.consume():
            wait_time = self.token_bucket.wait_time()
            if wait_time > 0:
                await asyncio.sleep(wait_time)
        
        # Prepare webhook payload with metadata
        payload = {
            'record_index': record_index,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'test': self.stats['is_test'],  # Will be true if webhook_limit > 0
            'data': self._format_record(record, self.table_type)
        }
        
        # Track request timing
        start_time = time.time()
        
        for attempt in range(self.config.retry_attempts):
            try:
                self.stats['total_requests'] += 1
                payload['attempt'] = attempt + 1
                
                async with session.post(
                    self.config.url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout),
                    ssl=self.config.verify_ssl
                ) as response:
                    response_time = time.time() - start_time
                    self._update_avg_response_time(response_time)
                    
                    if response.status >= 200 and response.status < 300:
                        self.stats['sent_successfully'] += 1
                        self.stats['consecutive_failures'] = 0  # Reset failure counter
                        return True
                    else:
                        error_body = await response.text()
                        logger.warning(f"Webhook returned status {response.status} for record {record_index}: {error_body}")
                        
                        self.stats['last_error'] = f"HTTP {response.status}: {error_body[:100]}"
                        
                        # Don't retry on client errors (4xx)
                        if 400 <= response.status < 500:
                            self.stats['failed_records'] += 1
                            self.stats['consecutive_failures'] += 1
                            return False
                
            except asyncio.TimeoutError:
                error_msg = f"Webhook timeout for record {record_index}, attempt {attempt + 1}"
                logger.warning(error_msg)
                self.stats['last_error'] = error_msg
                self.stats['consecutive_failures'] += 1
                
            except Exception as e:
                error_msg = f"Webhook error for record {record_index}, attempt {attempt + 1}: {e}"
                logger.warning(error_msg)
                self.stats['last_error'] = str(e)
                self.stats['consecutive_failures'] += 1
            
            # Check for too many consecutive failures
            if self.stats['consecutive_failures'] >= 5:
                logger.error("Too many consecutive failures, pausing webhook sending")
                self.stats['status'] = 'paused'
                self._update_progress(
                    'Paused due to multiple consecutive failures',
                    None,
                    {'error': 'Too many consecutive failures'}
                )
                return False
            
            # Exponential backoff for retries
            if attempt < self.config.retry_attempts - 1:
                self.stats['retry_attempts'] += 1
                backoff_time = self.config.retry_backoff[min(attempt, len(self.config.retry_backoff) - 1)]
                # Add jitter to prevent thundering herd
                jitter = random.uniform(0, 0.1) * backoff_time
                await asyncio.sleep(backoff_time + jitter)
        
        # All retries failed
        self.stats['failed_records'] += 1
        self.failed_records.append({
            'index': record_index,
            'data': record,
            'last_error': self.stats['last_error'],
            'attempts': self.config.retry_attempts
        })
        return False
    
    async def send_records_batch(self, records: List[Dict[str, Any]], batch_size: int = 10) -> Dict[str, Any]:
        """
        Send records in batches asynchronously with enhanced monitoring
        
        Args:
            records: List of records to send
            batch_size: Number of concurrent requests
            
        Returns:
            Dictionary with sending results
        """
        # First step: Prepare records
        if not await self.prepare_records(records):
            return {
                'status': 'failed',
                'stage': 'preparation',
                'error': self.stats['last_error']
            }
        
        self.stats['start_time'] = time.time()
        self.stats['stage'] = 'sending'
        self.stats['status'] = 'processing'
        
        self._update_progress("Starting webhook delivery", 0)
        
        connector = aiohttp.TCPConnector(limit=batch_size)
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Process records in batches
            for i in range(0, len(records), batch_size):
                if self.stats['status'] == 'paused':
                    logger.warning("Webhook sending is paused due to errors")
                    break
                
                batch = records[i:i + batch_size]
                
                # Create tasks for batch
                tasks = []
                for j, record in enumerate(batch):
                    record_index = i + j
                    task = self.send_record_async(session, record, record_index)
                    tasks.append(task)
                
                # Execute batch
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Update progress
                completed = min(i + batch_size, len(records))
                percentage = (completed / len(records)) * 100
                
                self.stats['current_rate'] = self._calculate_current_rate()
                
                self._update_progress(
                    f"Sent {completed}/{len(records)} records", 
                    percentage,
                    {
                        'batch_success': sum(1 for r in batch_results if r is True),
                        'batch_failure': sum(1 for r in batch_results if r is False)
                    }
                )
                
                # Brief pause between batches to prevent overwhelming
                await asyncio.sleep(0.1)
        
        self.stats['end_time'] = time.time()
        processing_time = self.stats['end_time'] - self.stats['start_time']
        
        # Final statistics
        results = {
            'total_records': self.stats['total_records'],
            'sent_successfully': self.stats['sent_successfully'],
            'failed_records': self.stats['failed_records'],
            'retry_attempts': self.stats['retry_attempts'],
            'processing_time': processing_time,
            'average_rate': self.stats['total_records'] / processing_time if processing_time > 0 else 0,
            'success_rate': (self.stats['sent_successfully'] / self.stats['total_records'] * 100) if self.stats['total_records'] > 0 else 0,
            'avg_response_time': self.stats['avg_response_time'],
            'failed_record_details': self.failed_records if len(self.failed_records) <= 10 else self.failed_records[:10],
            'stage': 'completed' if self.stats['status'] != 'paused' else 'paused',
            'status': 'completed' if self.stats['failed_records'] == 0 else 'completed_with_errors',
            'last_error': self.stats['last_error']
        }
        
        self.stats['stage'] = results['stage']
        self.stats['status'] = results['status']
        
        self._update_progress(
            f"Webhook delivery completed: {results['success_rate']:.1f}% success rate",
            100,
            results
        )
        
        logger.info(f"Webhook delivery completed: {self.stats['sent_successfully']}/{self.stats['total_records']} sent successfully")
        return results
    
    def send_records_sync(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Synchronous wrapper for sending records
        
        Args:
            records: List of records to send
            
        Returns:
            Dictionary with sending results
        """
        try:
            # Create event loop if none exists
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        try:
            return loop.run_until_complete(self.send_records_batch(records))
        finally:
            # Don't close the loop if it was already running
            pass
    
    def validate_webhook_url(self) -> bool:
        """
        Validate webhook URL by sending a test request - used by test button
        
        Returns:
            True if webhook is reachable and responds correctly
        """
        test_payload = {
            'test': True,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'message': 'CSV Merger webhook validation'
        }
        
        try:
            response = requests.post(
                self.config.url,
                json=test_payload,
                timeout=self.config.timeout,
                verify=self.config.verify_ssl
            )
            
            if 200 <= response.status_code < 300:
                logger.info(f"Webhook validation successful: {response.status_code}")
                return True
            else:
                logger.warning(f"Webhook validation failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Webhook validation error: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current sending statistics"""
        return self.stats.copy()
    
    def retry_failed_records(self) -> Dict[str, Any]:
        """
        Retry sending failed records
        
        Returns:
            Results of retry attempt
        """
        if not self.failed_records:
            return {'message': 'No failed records to retry'}
        
        failed_data = [record['data'] for record in self.failed_records]
        self.failed_records.clear()  # Clear failed records before retry
        
        logger.info(f"Retrying {len(failed_data)} failed records")
        return self.send_records_sync(failed_data) 