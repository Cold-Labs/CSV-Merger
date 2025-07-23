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
import uvicorn
from fastapi import FastAPI

# Add src to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Config
from src.csv_processor import CSVProcessor
from src.config_manager import ConfigManager
from src.webhook_sender import WebhookSender, WebhookConfig
from src.queue_manager import JobManager
from src.session_manager import SessionManager

# Configure logging
from src.logging_config import setup_module_logger
logger = setup_module_logger(__name__, 'worker.log')

# FastAPI health check server
def create_health_app() -> FastAPI:
    """Create FastAPI app for health checks"""
    app = FastAPI(title="CSV Worker Health Check", version="1.0.0")
    
    @app.get("/health")
    async def health_check():
        """Health check endpoint for Railway"""
        return {"status": "healthy", "service": "csv-worker"}
    
    @app.get("/")
    async def root():
        """Root endpoint"""
        return {"message": "CSV Merger Worker is running"}
    
    return app

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
        self.session_manager = SessionManager(redis_connection, self.config)
        
        # Create RQ worker with explicit queue
        from rq import Queue
        self.queue = Queue('csv_processing', connection=redis_connection)
        self.worker = Worker(
            [self.queue], 
            connection=redis_connection,
            name=self.worker_name
        )
        
        # Shutdown flag
        self.shutdown_requested = False
        
        logger.info(f"CSV Worker '{self.worker_name}' initialized")
    
    def process_csv_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Background job function for processing CSV files with two-step webhook delivery
        
        Args:
            job_data: Job data dictionary
            
        Returns:
            Job results dictionary
        """
        import sys
        sys.path.append('.')
        
        from src.config_manager import ConfigManager
        from src.webhook_sender import WebhookSender, WebhookConfig
        
        job_id = job_data['job_id']
        session_id = job_data['session_id']
        
        logger.info(f"Starting background job {job_id} for session {session_id}")
        
        try:
            # Initialize components
            config_manager = ConfigManager('config/field_mappings.json')
            
            # Create progress callback
            def progress_callback(progress_data):
                """Callback to update job progress in Redis"""
                try:
                    import redis
                    from config.settings import Config
                    
                    redis_client = redis.from_url(Config.REDIS_URL, decode_responses=True)
                    job_manager = JobManager(redis_client, Config)
                    job_manager.update_progress(job_id, session_id, progress_data)
                except Exception as e:
                    logger.error(f"Failed to update progress: {e}")
            
            # Initialize CSV processor with progress callback
            processor = CSVProcessor(config_manager, progress_callback)
            
            # Update job status to processing
            progress_callback({
                'message': 'CSV Processing started',
                'percentage': 0,
                'status': 'processing',
                'stage': 'csv_processing'
            })
            
            # Process CSV files
            df, export_path = processor.process_files(
                job_data['file_paths'],
                job_data['table_type'],
                session_id
            )
            
            # Get processing statistics
            stats = processor.get_processing_stats()
            
            # Prepare base results
            results = {
                'status': 'completed',
                'stage': 'csv_processed',
                'export_path': export_path,
                'stats': stats,
                'total_records': len(df),
                'processing_time': stats.get('processing_time', 0)
            }
            
            # If webhook mode, handle webhook delivery as separate step
            if job_data.get('processing_mode') == 'webhook' and job_data.get('webhook_url'):
                progress_callback({
                    'message': 'CSV Processing completed, preparing webhook delivery',
                    'percentage': 50,
                    'status': 'processing',
                    'stage': 'webhook_preparation'
                })
                
                # Initialize webhook sender
                webhook_config = WebhookConfig(
                    url=job_data['webhook_url'],
                    rate_limit=job_data.get('webhook_rate_limit', 10),
                    retry_attempts=3,
                    timeout=30
                )
                webhook_sender = WebhookSender(
                    webhook_config, 
                    progress_callback,
                    table_type=job_data.get('table_type', 'people')
                )
                
                # Convert DataFrame to records
                records = df.to_dict('records')
                
                # Apply webhook limit if specified
                webhook_limit = int(job_data.get('webhook_limit', 0))
                if webhook_limit > 0 and len(records) > webhook_limit:
                    records = records[:webhook_limit]
                    logger.info(f"Webhook limit applied: sending {webhook_limit} records out of {len(df)} total")
                
                # First step: Prepare records
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    # Prepare records
                    preparation_success = loop.run_until_complete(
                        webhook_sender.prepare_records(records, webhook_limit=webhook_limit)
                    )
                    
                    if not preparation_success:
                        raise ValueError("Failed to prepare records for webhook delivery")
                    
                    # Second step: Send records
                    webhook_results = loop.run_until_complete(
                        webhook_sender.send_records_batch(records)
                    )
                    
                    # Update results with webhook information
                    results.update({
                        'webhook_status': webhook_results.get('status', 'failed'),
                        'webhook_stage': webhook_results.get('stage', 'unknown'),
                        'webhook_results': webhook_results,
                        'webhook_success_rate': webhook_results.get('success_rate', 0),
                        'webhook_failed_records': webhook_results.get('failed_records', 0),
                        'webhook_limit_applied': webhook_limit if webhook_limit > 0 else None,
                        'webhook_records_sent': len(records),
                        'webhook_total_available': len(df),
                        'webhook_error': webhook_results.get('last_error')
                    })
                    
                except Exception as e:
                    logger.error(f"Webhook delivery failed: {e}")
                    results.update({
                        'webhook_status': 'failed',
                        'webhook_stage': 'failed',
                        'webhook_error': str(e)
                    })
                    raise
                    
                finally:
                    loop.close()
            
            # Mark job as completed
            progress_callback({
                'message': 'Job completed successfully',
                'percentage': 100,
                'status': 'completed',
                'stage': 'completed',
                'stats': results
            })
            
            logger.info(f"Job {job_id} completed successfully")
            return results
            
        except Exception as e:
            error_msg = f"Job {job_id} failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
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
            redis_connection = redis.from_url(
                self.redis_url, 
                decode_responses=True,
                encoding='utf-8',
                encoding_errors='replace'
            )
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

def start_health_server(port: int = 8080):
    """Start FastAPI health check server in background thread"""
    def run_server():
        try:
            app = create_health_app()
            logger.info(f"Starting health check server on port {port}")
            uvicorn.run(
                app, 
                host="0.0.0.0", 
                port=port, 
                log_level="info",
                access_log=False
            )
        except Exception as e:
            logger.error(f"Health server failed: {e}")
    
    health_thread = threading.Thread(target=run_server, daemon=True)
    health_thread.start()
    logger.info("Health check server started in background thread")
    return health_thread

def main():
    """Main entry point for worker process"""
    import argparse
    
    parser = argparse.ArgumentParser(description='CSV Merger Background Worker')
    parser.add_argument('--workers', type=int, default=1, help='Number of worker processes')
    parser.add_argument('--redis-url', help='Redis connection URL')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('--health-port', type=int, default=8080, help='Health check server port')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info(f"Starting CSV Merger Worker - PID: {os.getpid()}")
    logger.info(f"Workers: {args.workers}")
    logger.info(f"Redis URL: {args.redis_url or 'default'}")
    logger.info(f"Health port: {args.health_port}")
    
    try:
        # Start health check server in background thread
        health_thread = start_health_server(args.health_port)
        
        # Start worker manager
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