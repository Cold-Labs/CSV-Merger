import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Tuple, Optional, Any
import re
from datetime import datetime
import json
import os

from src.logging_config import setup_module_logger

logger = setup_module_logger(__name__)

class Phase2Standardizer:
    """
    Phase 2: AI-based header standardization
    
    Applies n8n mappings with priority handling (primary, secondary, tertiary)
    to transform the merged raw data into standardized columns.
    """
    
    def __init__(self, config_manager, progress_callback=None):
        self.config_manager = config_manager
        self.progress_callback = progress_callback
        self.n8n_mapping_time = 0
        self.stats = {
            'headers_mapped': 0,
            'primary_mappings': 0,
            'secondary_mappings': 0,
            'tertiary_mappings': 0,
            'unmapped_headers': 0,
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
    
    async def map_and_standardize(self, merged_df: pd.DataFrame, table_type: str, session_id: str, header_mapper, progress_callback=None):
        """
        PHASE 2: Send cleaned headers + sample to n8n for AI mapping, then apply mappings
        
        Args:
            merged_df: Cleaned and merged DataFrame from Phase 1
            table_type: 'people' or 'company'
            session_id: Session ID
            header_mapper: HeaderMapper instance for n8n calls
            progress_callback: Progress callback function
            
        Returns:
            Tuple of (standardized_df, n8n_response)
        """
        import time
        import json
        
        logger.info("=== PHASE 2: AI mapping and standardization ===")
        
        # Step 1: Extract headers and sample data from cleaned DataFrame
        if progress_callback:
            progress_callback(percentage=35, message="Extracting headers and sample data for AI mapping...", stage="phase2")
        
        headers = list(merged_df.columns)
        sample_data = merged_df.head(1).to_dict('records')[0] if len(merged_df) > 0 else {}
        
        logger.info(f"Extracted {len(headers)} headers from cleaned data")
        logger.info(f"Headers: {headers}")
        
        # Step 2: Send to n8n for AI mapping
        if progress_callback:
            progress_callback(percentage=40, message="Sending cleaned headers to n8n for AI mapping...", stage="n8n_mapping")
        
        logger.info("🔍 === PHASE 2 N8N DEBUG START ===")
        logger.info("Sending cleaned headers + sample to n8n...")
        n8n_start_time = time.time()
        
        # Instead of creating a single merged file, create separate temp files for each original source
        # This preserves the individual file information in the n8n payload
        os.makedirs(f"uploads/{session_id}", exist_ok=True)
        
        original_sources = merged_df['Source'].unique() if 'Source' in merged_df.columns else ['unknown']
        temp_file_paths = []
        
        logger.info(f"Creating {len(original_sources)} separate temp files for n8n (one per original file)")
        
        for source in original_sources:
            # Filter data for this specific source file
            source_df = merged_df[merged_df['Source'] == source] if 'Source' in merged_df.columns else merged_df
            
            # Create temp filename based on source
            base_name = source.replace('.csv', '')
            temp_filename = f"{base_name}_cleaned_headers.csv"
            temp_csv_path = f"uploads/{session_id}/{temp_filename}"
            
            # Save sample data for this source (first 5 rows)
            sample_df = source_df.head(5)
            sample_df.to_csv(temp_csv_path, index=False)
            
            temp_file_paths.append(temp_csv_path)
            logger.info(f"Created temp file for {source}: {temp_csv_path} ({len(source_df)} total rows)")
        
        n8n_response = await header_mapper.map_headers(
            file_paths=temp_file_paths,
            table_type=table_type,
            session_id=session_id
        )
        
        # Clean up temp files
        for temp_path in temp_file_paths:
            try:
                os.remove(temp_path)
                logger.info(f"Cleaned up temp file: {temp_path}")
            except Exception as e:
                logger.warning(f"Could not remove temp file {temp_path}: {e}")
        
        self.n8n_mapping_time = time.time() - n8n_start_time
        logger.info(f"🔍 N8N Response received in {self.n8n_mapping_time:.2f}s")
        logger.info(f"🔍 N8N Response: {json.dumps(n8n_response, indent=2) if n8n_response else 'EMPTY'}")
        
        if progress_callback:
            progress_callback(percentage=50, message="Received AI mappings from n8n, applying to data...", stage="phase2", n8n_response=n8n_response)
        
        # Step 3: Apply the n8n mappings to the cleaned DataFrame
        standardized_df = self.apply_n8n_mappings(merged_df, n8n_response, table_type)
        
        logger.info(f"Phase 2 complete: {len(standardized_df.columns)} standard columns")
        
        return standardized_df, n8n_response
    
    def get_n8n_time(self):
        """Get n8n mapping time"""
        return self.n8n_mapping_time
    
    def apply_n8n_mappings(self, merged_df: pd.DataFrame, n8n_response: Dict, table_type: str) -> pd.DataFrame:
        """
        Apply n8n mappings with priority handling to the merged DataFrame
        
        Args:
            merged_df: Raw merged DataFrame from Phase 1
            n8n_response: Response from n8n with priority-based mappings
            table_type: 'people' or 'company'
            
        Returns:
            Standardized DataFrame with mapped headers
        """
        logger.info("🔍 === PHASE 2 STANDARDIZER N8N DEBUG START ===")
        logger.info(f"🔍 Received n8n_response type: {type(n8n_response)}")
        logger.info(f"🔍 Received n8n_response content: {json.dumps(n8n_response, indent=2) if n8n_response else 'EMPTY'}")
        logger.info(f"🔍 Received table_type: {table_type}")
        logger.info(f"🔍 Merged DataFrame shape: {merged_df.shape}")
        
        logger.info("=== PHASE 2: Applying AI mappings with priorities ===")
        start_time = datetime.now()
        
        # Get standard headers for this table type
        standard_headers = self._get_standard_headers(table_type)
        
        # Initialize new DataFrame with standard headers
        standardized_df = pd.DataFrame(index=merged_df.index)
        
        # Process n8n mappings - handle array response format
        logger.info(f"Raw n8n response type: {type(n8n_response)}")
        
        # Add robust validation for n8n_response
        if not n8n_response or (isinstance(n8n_response, list) and not n8n_response):
            logger.error("🔍 ERROR: n8n_response is empty or invalid!")
            raise ValueError("n8n response is empty. Cannot proceed with standardization.")
        
        # Handle array-wrapped response from n8n
        if isinstance(n8n_response, list) and len(n8n_response) > 0:
            n8n_data = n8n_response[0]  # Extract first item from array
            logger.info("Unwrapped array response from n8n")
        else:
            n8n_data = n8n_response
        
        mapped_files = n8n_data.get('mapped_files', [])
        if not mapped_files:
            logger.warning("No mapped files found in n8n response")
            logger.info(f"Available keys in n8n response: {list(n8n_data.keys()) if isinstance(n8n_data, dict) else 'Not a dict'}")
            raise ValueError("n8n response does not contain 'mapped_files'. Cannot proceed.")
        
        # Create comprehensive mapping dict from all files
        logger.info(f"Processing {len(mapped_files)} mapped files from n8n")
        for i, file_mapping in enumerate(mapped_files):
            logger.info(f"File {i+1}: {file_mapping.get('filename', 'unknown')} with {len(file_mapping.get('mapped_headers', {}))} mapped headers")
        
        all_mappings = self._extract_all_mappings(mapped_files)
        
        # Apply mappings with priority handling for all headers including Source
        for standard_header in standard_headers:
            if standard_header == 'Source':
                # Add Source column from merged DataFrame
                standardized_df[standard_header] = merged_df['Source']
            else:
                self._update_progress(f"Mapping {standard_header}", stage="standardize")
                
                # Find the best available mapping for this standard header
                mapped_values = self._map_standard_header(merged_df, standard_header, all_mappings)
                standardized_df[standard_header] = mapped_values
            
            if mapped_values.notna().any():
                self.stats['headers_mapped'] += 1
        
        # ============================================================
        # PRESERVE UNMAPPED COLUMNS (Bug Fix #3)
        # ============================================================
        # Collect all original columns that were used in mappings
        mapped_original_columns = set()
        for standard_header, mapping_data in all_mappings.items():
            if isinstance(mapping_data, dict):
                # Extract original column names from all priority levels
                if 'primary' in mapping_data and mapping_data['primary']:
                    mapped_original_columns.add(mapping_data['primary'])
                if 'secondary' in mapping_data:
                    for col in mapping_data['secondary']:
                        if col:
                            mapped_original_columns.add(col)
                if 'tertiary' in mapping_data:
                    for col in mapping_data['tertiary']:
                        if col:
                            mapped_original_columns.add(col)
        
        # Add Source to mapped columns (we don't want to duplicate it)
        mapped_original_columns.add('Source')
        
        # Find unmapped columns from original data
        unmapped_columns = [col for col in merged_df.columns if col not in mapped_original_columns]
        
        # Add all unmapped columns to the standardized dataframe
        unmapped_count = 0
        for col in unmapped_columns:
            standardized_df[col] = merged_df[col]
            unmapped_count += 1
        
        self.stats['unmapped_headers'] = unmapped_count
        
        logger.info(f"📦 Preserved {unmapped_count} unmapped columns: {unmapped_columns[:10]}{'...' if len(unmapped_columns) > 10 else ''}")
        
        # Update stats
        self.stats['processing_time'] = (datetime.now() - start_time).total_seconds()
        
        logger.info(f"✅ PHASE 2 COMPLETE:")
        logger.info(f"   • Headers mapped: {self.stats['headers_mapped']}")
        logger.info(f"   • Primary mappings: {self.stats['primary_mappings']}")
        logger.info(f"   • Secondary mappings: {self.stats['secondary_mappings']}")
        logger.info(f"   • Tertiary mappings: {self.stats['tertiary_mappings']}")
        logger.info(f"   • Unmapped headers preserved: {self.stats['unmapped_headers']}")
        logger.info(f"   • Processing time: {self.stats['processing_time']:.2f}s")
        
        return standardized_df
    
    def _get_standard_headers(self, table_type: str) -> List[str]:
        """Get standard headers for table type"""
        try:
            field_mappings = self.config_manager.get_field_mappings()
            mappings_key = f"{table_type}_mappings"
            return list(field_mappings.get(mappings_key, {}).keys()) + ['Source']
        except Exception as e:
            logger.error(f"Failed to load standard headers: {e}")
            # Fallback standard headers
            if table_type == 'people':
                return [
                    'First Name', 'Last Name', 'Full Name', 'Job Title', 'LinkedIn Profile',
                    'Person Location', 'Work Email', 'Personal Email', 'Phone Number',
                    'Company Name', 'Company Domain', 'Company Description', 'Company Industry',
                    'Company Employee Count', 'Company LinkedIn', 'Year Founded', 'Company Location',
                    'Source'
                ]
            else:  # company
                return [
                    'Company Name', 'Company Domain', 'Company Description', 'Company Industry',
                    'Company Employee Count', 'Company LinkedIn', 'Year Founded', 'Company Location',
                    'Source'
                ]
    
    def _extract_all_mappings(self, mapped_files: List[Dict]) -> Dict[str, Dict]:
        """
        Extract all mappings from n8n response into a comprehensive mapping dict
        
        Args:
            mapped_files: List of mapped file objects from n8n
            
        Returns:
            Dict mapping standard headers to their priority mappings
        """
        all_mappings = {}
        
        for file_mapping in mapped_files:
            filename = file_mapping.get('filename', 'unknown')
            mapped_headers = file_mapping.get('mapped_headers', {})
            
            logger.info(f"Processing mappings for file: {filename}")
            
            for standard_header, priority_mappings in mapped_headers.items():
                if standard_header not in all_mappings:
                    all_mappings[standard_header] = {
                        'primary': [],
                        'secondary': [],
                        'tertiary': []
                    }
                
                # Extract priority mappings
                for priority in ['primary', 'secondary', 'tertiary']:
                    if priority in priority_mappings:
                        source_column = priority_mappings[priority]
                        if source_column not in all_mappings[standard_header][priority]:
                            all_mappings[standard_header][priority].append(source_column)
        
        return all_mappings
    
    def _map_standard_header(self, merged_df: pd.DataFrame, standard_header: str, 
                           all_mappings: Dict[str, Dict]) -> pd.Series:
        """
        Map a single standard header using priority-based selection
        
        Args:
            merged_df: Raw merged DataFrame
            standard_header: Standard header to map
            all_mappings: All available mappings with priorities
            
        Returns:
            Series with mapped values for this standard header
        """
        if standard_header not in all_mappings:
            logger.debug(f"No mapping found for {standard_header}")
            return pd.Series([''] * len(merged_df), index=merged_df.index)
        
        mapping_info = all_mappings[standard_header]
        result_series = pd.Series([''] * len(merged_df), index=merged_df.index)
        
        # Try primary mappings first
        for source_col in mapping_info.get('primary', []):
            if source_col in merged_df.columns:
                mask = result_series == ''  # Only fill empty values
                source_values = merged_df[source_col].fillna('').astype(str)
                valid_mask = (source_values != '') & (source_values.str.lower() != 'nan')
                
                result_series.loc[mask & valid_mask] = source_values.loc[mask & valid_mask]
                self.stats['primary_mappings'] += (mask & valid_mask).sum()
                logger.debug(f"Primary mapping: {source_col} -> {standard_header} ({(mask & valid_mask).sum()} values)")
        
        # Try secondary mappings for remaining empty values
        for source_col in mapping_info.get('secondary', []):
            if source_col in merged_df.columns:
                mask = result_series == ''  # Only fill empty values
                source_values = merged_df[source_col].fillna('').astype(str)
                valid_mask = (source_values != '') & (source_values.str.lower() != 'nan')
                
                result_series.loc[mask & valid_mask] = source_values.loc[mask & valid_mask]
                self.stats['secondary_mappings'] += (mask & valid_mask).sum()
                logger.debug(f"Secondary mapping: {source_col} -> {standard_header} ({(mask & valid_mask).sum()} values)")
        
        # Try tertiary mappings for remaining empty values
        for source_col in mapping_info.get('tertiary', []):
            if source_col in merged_df.columns:
                mask = result_series == ''  # Only fill empty values
                source_values = merged_df[source_col].fillna('').astype(str)
                valid_mask = (source_values != '') & (source_values.str.lower() != 'nan')
                
                result_series.loc[mask & valid_mask] = source_values.loc[mask & valid_mask]
                self.stats['tertiary_mappings'] += (mask & valid_mask).sum()
                logger.debug(f"Tertiary mapping: {source_col} -> {standard_header} ({(mask & valid_mask).sum()} values)")
        
        return result_series
    
    def _create_empty_standardized_df(self, merged_df: pd.DataFrame, standard_headers: List[str]) -> pd.DataFrame:
        """Create empty standardized DataFrame when no mappings are available"""
        logger.warning("Creating empty standardized DataFrame - no mappings available")
        
        standardized_df = pd.DataFrame(index=merged_df.index)
        
        for header in standard_headers:
            if header == 'Source':
                standardized_df[header] = merged_df['Source']
            else:
                standardized_df[header] = ''
        
        return standardized_df
    
    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics"""
        return self.stats.copy() 