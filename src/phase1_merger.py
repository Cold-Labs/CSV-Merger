import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Tuple, Optional, Any
import os
from datetime import datetime

from src.logging_config import setup_module_logger

logger = setup_module_logger(__name__)

class Phase1Merger:
    """
    Phase 1: Raw CSV file merger
    
    Merges all uploaded CSV files into a single DataFrame with source tracking,
    before any header mapping or processing occurs.
    """
    
    def __init__(self, progress_callback=None):
        self.progress_callback = progress_callback
        self.stats = {
            'files_processed': 0,
            'total_records': 0,
            'total_columns': 0,
            'processing_time': 0
        }
    
    def _update_progress(self, message: str, percentage: int = None, stage: str = None):
        """Update progress via callback"""
        if self.progress_callback:
            progress_data = {'message': message}
            if percentage is not None:
                progress_data['percentage'] = percentage
            if stage:
                progress_data['stage'] = stage
            self.progress_callback(progress_data)
    
    def merge_raw_files(self, file_paths: List[str]) -> pd.DataFrame:
        """
        Merge all CSV files into a single DataFrame with source tracking
        
        Args:
            file_paths: List of CSV file paths to merge
            
        Returns:
            Merged DataFrame with Source column added
        """
        if not file_paths:
            raise ValueError("No files provided for merging")
        
        logger.info(f"=== PHASE 1: Merging {len(file_paths)} raw CSV files ===")
        start_time = datetime.now()
        
        # MEMORY FIX: Process files one by one instead of loading all at once
        merged_df = None
        
        for i, file_path in enumerate(file_paths):
            try:
                self._update_progress(
                    f"Reading file {i+1}/{len(file_paths)}: {os.path.basename(file_path)}", 
                    int((i / len(file_paths)) * 100), 
                    "merge"
                )
                
                logger.info(f"Reading file: {os.path.basename(file_path)}")
                
                # Read CSV file with error handling
                # parse_dates=False prevents pandas from auto-converting text fields like "Job Title" to dates
                # Numeric fields stay numeric, text stays text, dates stay as strings (can be parsed explicitly if needed)
                df = pd.read_csv(file_path, encoding='utf-8', low_memory=False, parse_dates=False)
                
                # Add source tracking
                source_name = os.path.basename(file_path)
                df['Source'] = source_name
                
                # Log file info
                logger.info(f"File {source_name}: {df.shape[0]} rows, {df.shape[1]-1} columns")
                
                # MEMORY FIX: Merge immediately instead of keeping in list
                if merged_df is None:
                    merged_df = df
                else:
                    merged_df = pd.concat([merged_df, df], ignore_index=True, sort=False)
                    # MEMORY FIX: Explicitly delete the individual DataFrame
                    del df
                
                self.stats['files_processed'] += 1
                
                # MEMORY FIX: Force garbage collection after each file
                import gc
                gc.collect()
                
            except Exception as e:
                logger.error(f"Failed to read file {file_path}: {e}")
                raise Exception(f"Failed to read file {os.path.basename(file_path)}: {e}")
        
        # Final validation
        if merged_df is None:
            raise Exception("No files were successfully processed")
        
        # Update stats
        self.stats['total_records'] = len(merged_df)
        self.stats['total_columns'] = len(merged_df.columns) - 1  # Exclude Source column
        self.stats['processing_time'] = (datetime.now() - start_time).total_seconds()
        
        logger.info(f"✅ PHASE 1 COMPLETE:")
        logger.info(f"   • Files merged: {self.stats['files_processed']}")
        logger.info(f"   • Total records: {self.stats['total_records']}")
        logger.info(f"   • Unique columns: {self.stats['total_columns']}")
        logger.info(f"   • Processing time: {self.stats['processing_time']:.2f}s")
        
        return merged_df
    
    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics"""
        return self.stats.copy() 