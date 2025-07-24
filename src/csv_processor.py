import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Tuple, Optional, Any
import asyncio
import time
from datetime import datetime
import json

from src.logging_config import setup_module_logger
from src.config_manager import ConfigManager
from src.header_mapper import N8NHeaderMapper
from src.phase1_merger import Phase1Merger
from src.phase2_standardizer import Phase2Standardizer
from src.phase3_enricher import Phase3Enricher

logger = setup_module_logger(__name__)

class CSVProcessor:
    """
    New CSV Processor V2 with three-phase architecture:
    
    Phase 1: Raw file merging with source tracking
    Phase 2: AI-based header standardization using n8n mappings
    Phase 3: Email enrichment and smart deduplication
    """
    
    def __init__(self, config_manager: ConfigManager, progress_callback=None, redis_client=None, session_manager=None):
        self.config_manager = config_manager
        self.progress_callback = progress_callback
        self.redis_client = redis_client
        self.session_manager = session_manager
        
        # Initialize phase processors
        self.header_mapper = N8NHeaderMapper(config_manager.get_n8n_webhook_url())
        self.phase1_merger = Phase1Merger(progress_callback)
        self.phase2_standardizer = Phase2Standardizer(config_manager, progress_callback)
        self.phase3_enricher = Phase3Enricher(config_manager, progress_callback)
        
        # Combined stats
        self.stats = {
            'total_processing_time': 0,
            'phase1_stats': {},
            'phase2_stats': {},
            'phase3_stats': {},
            'n8n_mapping_time': 0
        }
        
        logger.info("Initialized CSV Processor with three-phase architecture")
    
    def _update_progress(self, message: str, percentage: int = None, stage: str = None, 
                        stats: Dict = None, webhook_stats: Dict = None):
        """Update progress via callback"""
        if self.progress_callback:
            self.progress_callback(
                message=message,
                stage=stage or 'processing',
                percentage=percentage,
                stats=stats,
                webhook_stats=webhook_stats
            )
    
    async def process_files(self, file_paths: List[str], table_type: str, session_id: str) -> Tuple[pd.DataFrame, str, Dict]:
        """
        Main processing pipeline orchestrating all three phases
        
        Args:
            file_paths: List of CSV file paths to process
            table_type: 'people' or 'company'
            session_id: Session ID for tracking
            
        Returns:
            Tuple of (final DataFrame, export file path, n8n_response)
        """
        if not file_paths:
            raise ValueError("No files provided for processing")
        
        logger.info(f"=== CSV PROCESSOR: Starting three-phase processing ===")
        logger.info(f"Files: {[f.split('/')[-1] for f in file_paths]}")
        logger.info(f"Table type: {table_type}")
        logger.info(f"Session: {session_id}")
        
        start_time = time.time()
        
        try:
            # Phase 0: n8n Header Mapping
            n8n_response = {}
            if self.progress_callback:
                self.progress_callback(percentage=5, message="[1/5] Sending data to n8n for AI mapping...", stage="n8n_mapping")
            
            logger.info("🔍 === CSV PROCESSOR N8N DEBUG START ===")
            logger.info("Requesting header mapping from n8n...")
            n8n_start_time = time.time()
            n8n_response = await self.header_mapper.map_headers(
                file_paths=file_paths,
                table_type=table_type,
                session_id=session_id
            )
            self.stats['n8n_mapping_time'] = time.time() - n8n_start_time
            logger.info(f"🔍 N8N Response received in {self.stats['n8n_mapping_time']:.2f}s")
            logger.info(f"🔍 N8N Response type: {type(n8n_response)}")
            logger.info(f"🔍 N8N Response content: {json.dumps(n8n_response, indent=2) if n8n_response else 'EMPTY'}")
            
            if self.progress_callback:
                self.progress_callback(percentage=15, message="[2/5] Received AI mapping from n8n.", stage="n8n_mapping", n8n_response=n8n_response)
            
            # PHASE 1: Merge raw files
            self._update_progress("Phase 1: Merging raw CSV files", 20, "phase1")
            logger.info("=== PHASE 1: Raw file merging ===")
            merged_df = self.phase1_merger.merge_raw_files(file_paths)
            self.stats['phase1_stats'] = self.phase1_merger.get_stats()
            
            logger.info(f"Phase 1 complete: {len(merged_df)} records merged")
            
            # MEMORY FIX: Force garbage collection after Phase 1
            import gc
            gc.collect()
            
            # PHASE 2: Apply AI mappings
            self._update_progress("Phase 2: Applying AI mappings", 40, "phase2")
            logger.info("=== PHASE 2: AI-based standardization ===")
            standardized_df = self.phase2_standardizer.apply_n8n_mappings(merged_df, n8n_response, table_type)
            self.stats['phase2_stats'] = self.phase2_standardizer.get_stats()
            
            logger.info(f"Phase 2 complete: {len(standardized_df.columns)} standard columns")
            
            # MEMORY FIX: Delete Phase 1 DataFrame and force garbage collection
            del merged_df
            gc.collect()
            
            # PHASE 3: Email enrichment and deduplication
            self._update_progress("Phase 3: Email enrichment and deduplication", 70, "phase3")
            logger.info("=== PHASE 3: Email enrichment and deduplication ===")
            final_df = self.phase3_enricher.enrich_and_deduplicate(standardized_df, table_type)
            self.stats['phase3_stats'] = self.phase3_enricher.get_stats()
            
            logger.info(f"Phase 3 complete: {len(final_df)} final records")
            
            # MEMORY FIX: Delete Phase 2 DataFrame and force garbage collection
            del standardized_df
            gc.collect()
            
            # Export final results
            self._update_progress("Exporting final results", 95, "export")
            export_path = self.phase3_enricher.export_results(final_df, table_type, session_id)
            
            # Calculate total processing time
            self.stats['total_processing_time'] = time.time() - start_time
            
            # Final progress update
            self._update_progress("Processing completed successfully", 100, "completed", 
                                stats=self.get_processing_stats())
            
            # Log final summary
            logger.info(f"✅ ALL PHASES COMPLETED SUCCESSFULLY:")
            logger.info(f"   • Total processing time: {self.stats['total_processing_time']:.2f}s")
            logger.info(f"   • n8n mapping time: {self.stats['n8n_mapping_time']:.2f}s")
            logger.info(f"   • Phase 1 time: {self.stats['phase1_stats'].get('processing_time', 0):.2f}s")
            logger.info(f"   • Phase 2 time: {self.stats['phase2_stats'].get('processing_time', 0):.2f}s")
            logger.info(f"   • Phase 3 time: {self.stats['phase3_stats'].get('processing_time', 0):.2f}s")
            logger.info(f"   • Final records: {len(final_df)}")
            logger.info(f"   • Export path: {export_path}")
            
            return final_df, export_path, n8n_response
            
        except Exception as e:
            logger.error(f"Error during CSV processing pipeline: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """Get comprehensive processing statistics"""
        # Combine stats from all phases
        combined_stats = {
            'total_processing_time': self.stats['total_processing_time'],
            'n8n_mapping_time': self.stats['n8n_mapping_time'],
            
            # Phase 1 stats
            'files_processed': self.stats['phase1_stats'].get('files_processed', 0),
            'total_records': self.stats['phase1_stats'].get('total_records', 0),
            'total_columns': self.stats['phase1_stats'].get('total_columns', 0),
            
            # Phase 2 stats  
            'headers_mapped': self.stats['phase2_stats'].get('headers_mapped', 0),
            'primary_mappings': self.stats['phase2_stats'].get('primary_mappings', 0),
            'secondary_mappings': self.stats['phase2_stats'].get('secondary_mappings', 0),
            'tertiary_mappings': self.stats['phase2_stats'].get('tertiary_mappings', 0),
            
            # Phase 3 stats
            'emails_enriched': self.stats['phase3_stats'].get('emails_enriched', 0),
            'personal_emails_ranked': self.stats['phase3_stats'].get('personal_emails_ranked', 0),
            'work_emails_identified': self.stats['phase3_stats'].get('work_emails_identified', 0),
            'duplicates_removed': self.stats['phase3_stats'].get('duplicates_removed', 0),
            'records_merged': self.stats['phase3_stats'].get('records_merged', 0),
            'domains_enriched': self.stats['phase3_stats'].get('domains_enriched', 0),
            
            # Final counts
            'merged_records': self.stats['phase1_stats'].get('total_records', 0) - self.stats['phase3_stats'].get('duplicates_removed', 0),
            'fields_merged': self.stats['phase3_stats'].get('records_merged', 0),
            'domains_cleaned': 0  # This would need to be tracked if we want it
        }
        
        # Convert all numpy types to Python native types for JSON serialization
        def convert_numpy_types(obj):
            """Recursively convert numpy types to Python native types"""
            if hasattr(obj, 'item'):  # numpy scalar
                return obj.item()
            elif isinstance(obj, dict):
                return {k: convert_numpy_types(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_numpy_types(v) for v in obj]
            else:
                return obj
        
        return convert_numpy_types(combined_stats)
    
    # Legacy methods for compatibility with existing webhook sender
    def clean_domains(self, df: pd.DataFrame, domain_columns: List[str]) -> pd.DataFrame:
        """Legacy method for compatibility - domain cleaning is now in Phase 3"""
        return self.phase3_enricher._clean_domains(df)
    
    def normalize_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Legacy method for compatibility - normalization is now in Phase 3"""
        return self.phase3_enricher._normalize_data(df)
    
    def deduplicate_records(self, df: pd.DataFrame, table_type: str) -> pd.DataFrame:
        """Legacy method for compatibility - deduplication is now in Phase 3"""
        return self.phase3_enricher._smart_deduplicate(df, table_type)
    
    def export_to_csv(self, df: pd.DataFrame, table_type: str, session_id: str) -> str:
        """Legacy method for compatibility - export is now in Phase 3"""
        return self.phase3_enricher.export_results(df, table_type, session_id) 