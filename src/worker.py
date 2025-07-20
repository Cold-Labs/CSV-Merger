import os
import sys
import signal
import logging
import time
import threading
from typing import Dict, Any, Optional
import redis
from rq import Worker, Queue
from rq.job import Job
import pandas as pd
import json

# Add src to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Config
from src.csv_processor import CSVProcessor
from src.config_manager import ConfigManager
from src.webhook_sender import WebhookSender, WebhookConfig
from src.queue_manager import JobManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [Worker] %(message)s'
)
logger = logging.getLogger(__name__)

class CSVWorker:
    """Background worker for processing CSV jobs"""
    
    def __init__(self, redis_connection: redis.Redis, worker_name: Optional[str] = None):
        """
        Initialize CSV worker
        
        Args:
            redis_connection: Redis connection
            worker_name: Optional worker name for identification
        """
        self.redis = redis_connection
        self.config = Config() if isinstance(Config, type) else Config
        self.worker_name = worker_name or f"csv-worker-{os.getpid()}"
        
        # Initialize components
        self.config_manager = ConfigManager(self.config.FIELD_MAPPINGS_FILE)
        self.job_manager = JobManager(redis_connection, self.config)
        
        # Create RQ worker
        self.worker = Worker(
            ['csv_processing'], 
            connection=redis_connection,
            name=self.worker_name
        )
        
        # Shutdown flag
        self.shutdown_requested = False
        
        logger.info(f"CSV Worker '{self.worker_name}' initialized")
    
    def process_csv_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process CSV job with real-time progress updates
        
        Args:
            job_data: Job configuration and parameters
            
        Returns:
            Processing results
        """
        job_id = job_data.get('job_id')
        session_id = job_data.get('session_id')
        
        logger.info(f"Starting CSV processing job {job_id} by worker {self.worker_name}")
        
        # Create progress callback for real-time updates
        progress_callback = self.job_manager.create_progress_callback(job_id, session_id)
        
        try:
            # Initial progress update
            progress_callback({
                'message': 'Initializing CSV processing...',
                'percentage': 0,
                'status': 'initializing',
                'stage': 'setup'
            })
            
            # Extract job parameters
            table_type = job_data.get('table_type', 'company')
            processing_mode = job_data.get('processing_mode', 'webhook')
            webhook_url = job_data.get('webhook_url')
            webhook_rate_limit = job_data.get('webhook_rate_limit', 10)
            
            # Get session files
            session_files = self.session_manager.get_session_files(session_id)
            if not session_files:
                raise ValueError("No files found for processing")
            
            progress_callback({
                'message': f'Found {len(session_files)} files to process',
                'percentage': 5,
                'status': 'loading',
                'stage': 'file_discovery',
                'file_count': len(session_files)
            })
            
            # Load and process CSV files
            progress_callback({
                'message': 'Loading CSV files...',
                'percentage': 10,
                'status': 'loading',
                'stage': 'csv_loading'
            })
            
            # Process CSVs
            csv_processor = CSVProcessor(self.config_manager.get_field_mappings())
            
            progress_callback({
                'message': 'Processing and merging CSV data...',
                'percentage': 20,
                'status': 'processing',
                'stage': 'csv_processing'
            })
            
            # Load all CSVs into the processor
            for i, file_info in enumerate(session_files):
                file_path = file_info['path']
                logger.info(f"Loading CSV file: {file_path}")
                
                csv_processor.load_csv(file_path, table_type)
                
                file_progress = 20 + (30 * (i + 1) / len(session_files))
                progress_callback({
                    'message': f'Loaded {i + 1}/{len(session_files)} files',
                    'percentage': int(file_progress),
                    'status': 'processing',
                    'stage': 'csv_loading',
                    'files_processed': i + 1,
                    'total_files': len(session_files)
                })
            
            # Merge data
            progress_callback({
                'message': 'Merging CSV data...',
                'percentage': 50,
                'status': 'processing',
                'stage': 'merging'
            })
            
            df = csv_processor.merge_dataframes()
            if df.empty:
                raise ValueError("No data to process after merging")
            
            progress_callback({
                'message': 'Performing deduplication...',
                'percentage': 60,
                'status': 'processing',
                'stage': 'deduplication'
            })
            
            # Deduplicate
            df, duplicates_info = csv_processor.smart_deduplicate(df)
            
            progress_callback({
                'message': 'Cleaning and normalizing data...',
                'percentage': 70,
                'status': 'processing',
                'stage': 'cleaning'
            })
            
            # Clean and normalize
            df = csv_processor.clean_domains(df)
            df = csv_processor.normalize_data(df)
            
            # Prepare results
            results = {
                'total_records': len(df),
                'duplicates_removed': duplicates_info.get('removed_count', 0),
                'sources_merged': len(session_files),
                'processing_time': time.time() - job_data.get('start_time', time.time())
            }
            
            progress_callback({
                'message': f'Processed {results["total_records"]} records',
                'percentage': 80,
                'status': 'processing',
                'stage': 'finalizing',
                'stats': results
            })
            
            # Handle processing mode
            if processing_mode == 'download':
                # Export CSV for download
                progress_callback({
                    'message': 'Preparing CSV for download...',
                    'percentage': 85,
                    'status': 'exporting',
                    'stage': 'csv_export'
                })
                
                export_path = csv_processor.export_csv(df, session_id, table_type)
                results['export_path'] = export_path
                
                progress_callback({
                    'message': 'CSV ready for download',
                    'percentage': 100,
                    'status': 'completed',
                    'stage': 'completed'
                })
                
            elif processing_mode == 'webhook':
                # Send via webhook
                progress_callback({
                    'message': 'Preparing webhook delivery...',
                    'percentage': 85,
                    'status': 'webhook_delivery',
                    'stage': 'webhook_setup'
                })
                
                # Initialize webhook sender
                webhook_sender = WebhookSender(webhook_url, webhook_rate_limit)
                
                # Start rate monitoring thread
                rate_check_thread = threading.Thread(
                    target=self._monitor_rate_changes,
                    args=(job_id, session_id, webhook_sender),
                    daemon=True
                )
                rate_check_thread.start()
                
                # Convert DataFrame to records and send
                records = df.to_dict('records')
                
                progress_callback({
                    'message': f'Sending {len(records)} records via webhook...',
                    'percentage': 90,
                    'status': 'webhook_delivery',
                    'stage': 'webhook_sending',
                    'total_records': len(records)
                })
                
                webhook_results = webhook_sender.send_records_sync(records)
                
                # Update results with webhook information
                results.update({
                    'webhook_status': 'completed',
                    'webhook_results': webhook_results,
                    'webhook_success_rate': webhook_results.get('success_rate', 0),
                    'webhook_failed_records': webhook_results.get('failed_records', 0)
                })
                
                progress_callback({
                    'message': f'Webhook delivery completed ({webhook_results.get("success_rate", 0):.1f}% success)',
                    'percentage': 100,
                    'status': 'completed',
                    'stage': 'completed',
                    'webhook_stats': webhook_results
                })
                
                logger.info(f"Webhook delivery completed for job {job_id}: {webhook_results.get('success_rate', 0):.1f}% success rate")
            
            # Mark job as completed
            self.job_manager.mark_job_completed(job_id, session_id, results)
            
            # Final progress update
            progress_callback({
                'message': 'Job completed successfully',
                'percentage': 100,
                'status': 'completed',
                'stage': 'completed',
                'stats': results
            })
            
            logger.info(f"Job {job_id} completed successfully by worker {self.worker_name}")
            return results
            
        except Exception as e:
            error_msg = f"Job {job_id} failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            # Mark job as failed
            self.job_manager.mark_job_failed(job_id, session_id, str(e))
            
            # Update progress with error
            try:
                progress_callback({
                    'message': f'Job failed: {str(e)}',
                    'percentage': 0,
                    'status': 'failed',
                    'stage': 'error',
                    'error': str(e)
                })
            except:
                pass
            
            raise
    
    def _monitor_rate_changes(self, job_id: str, session_id: str, webhook_sender: WebhookSender):
        """
        Monitor for rate limit changes during webhook sending
        
        Args:
            job_id: Job ID
            session_id: Session ID
            webhook_sender: WebhookSender instance to update
        """
        rate_signal_key = f"rate_change:{session_id}:{job_id}"
        
        while True:
            try:
                # Check for rate change signal
                rate_data = self.redis.get(rate_signal_key)
                if rate_data:
                    rate_info = json.loads(rate_data)
                    new_rate = rate_info.get('new_rate')
                    
                    if new_rate is not None:
                        webhook_sender.update_rate_limit(new_rate)
                        logger.info(f"Updated rate limit for job {job_id} to {new_rate} req/sec")
                        
                        # Remove the signal
                        self.redis.delete(rate_signal_key)
                
                # Check every 5 seconds
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"Error monitoring rate changes for job {job_id}: {e}")
                break
    
    def start(self):
        """Start the worker"""
        logger.info(f"Starting CSV worker '{self.worker_name}'")
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        try:
            # Start the worker
            self.worker.work(with_scheduler=True)
        except KeyboardInterrupt:
            logger.info("Worker interrupted by user")
        finally:
            self._cleanup()
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Worker {self.worker_name} received signal {signum}, shutting down gracefully...")
        self.shutdown_requested = True
        self.worker.request_stop()
    
    def _cleanup(self):
        """Cleanup worker resources"""
        logger.info(f"Worker {self.worker_name} cleaning up...")
        
        # Stop config manager file watcher
        try:
            self.config_manager.stop_file_watcher()
        except:
            pass
        
        logger.info(f"Worker {self.worker_name} shutdown complete")

class WorkerManager:
    """Manages multiple worker processes"""
    
    def __init__(self, num_workers: int = 1, redis_url: Optional[str] = None):
        """
        Initialize worker manager
        
        Args:
            num_workers: Number of worker processes to run
            redis_url: Redis connection URL
        """
        self.num_workers = num_workers
        self.redis_url = redis_url or Config.REDIS_URL
        self.workers = []
        
        logger.info(f"Worker Manager initialized for {num_workers} workers")
    
    def start_workers(self):
        """Start all worker processes"""
        logger.info(f"Starting {self.num_workers} CSV processing workers")
        
        try:
            # Create Redis connection
            redis_connection = redis.from_url(self.redis_url)
            redis_connection.ping()
            
            # Create and start workers
            for i in range(self.num_workers):
                worker_name = f"csv-worker-{i+1}"
                worker = CSVWorker(redis_connection, worker_name)
                
                # Start worker in separate thread for multi-worker support
                if self.num_workers > 1:
                    worker_thread = threading.Thread(
                        target=worker.start,
                        name=worker_name,
                        daemon=False
                    )
                    worker_thread.start()
                    self.workers.append((worker, worker_thread))
                else:
                    # Single worker - run directly
                    worker.start()
                    self.workers.append((worker, None))
            
            # Wait for all workers if multi-threaded
            if self.num_workers > 1:
                for worker, thread in self.workers:
                    if thread:
                        thread.join()
            
        except redis.ConnectionError:
            logger.error("Failed to connect to Redis. Please ensure Redis is running.")
            raise
        except Exception as e:
            logger.error(f"Failed to start workers: {e}")
            raise
    
    def stop_workers(self):
        """Stop all workers gracefully"""
        logger.info("Stopping all workers...")
        
        for worker, thread in self.workers:
            try:
                worker._signal_handler(signal.SIGTERM, None)
                if thread and thread.is_alive():
                    thread.join(timeout=10)
            except Exception as e:
                logger.error(f"Error stopping worker: {e}")
        
        logger.info("All workers stopped")

def main():
    """Main entry point for worker process"""
    import argparse
    
    parser = argparse.ArgumentParser(description='CSV Merger Background Worker')
    parser.add_argument('--workers', type=int, default=1, help='Number of worker processes')
    parser.add_argument('--redis-url', help='Redis connection URL')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info(f"Starting CSV Merger Worker - PID: {os.getpid()}")
    logger.info(f"Workers: {args.workers}")
    logger.info(f"Redis URL: {args.redis_url or 'default'}")
    
    try:
        manager = WorkerManager(
            num_workers=args.workers,
            redis_url=args.redis_url
        )
        manager.start_workers()
    except KeyboardInterrupt:
        logger.info("Worker manager interrupted")
    except Exception as e:
        logger.error(f"Worker manager failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main() 