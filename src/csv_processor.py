import pandas as pd
import numpy as np
import re
import logging
from typing import Dict, List, Tuple, Optional, Callable, Any
from fuzzywuzzy import fuzz, process
from datetime import datetime
import os

logger = logging.getLogger(__name__)

class CSVProcessor:
    """Handles CSV processing with intelligent header mapping, deduplication, and data cleaning"""
    
    def __init__(self, config_manager, progress_callback: Optional[Callable] = None):
        """
        Initialize CSV processor
        
        Args:
            config_manager: Configuration manager instance
            progress_callback: Optional callback function for progress updates
        """
        self.config_manager = config_manager
        self.progress_callback = progress_callback
        self.stats = {
            'total_records': 0,
            'merged_records': 0,
            'duplicates_removed': 0,
            'fields_merged': 0,
            'domains_cleaned': 0,
            'processing_time': 0
        }
    
    def _update_progress(self, message: str, percentage: float = None, stats: Dict = None):
        """Update progress via callback if available"""
        if self.progress_callback:
            self.progress_callback({
                'message': message,
                'percentage': percentage,
                'stats': stats or self.stats
            })
        logger.info(f"Progress: {message} ({percentage}%)" if percentage else f"Progress: {message}")
    
    def map_headers(self, csv_headers: List[str], table_type: str) -> Dict[str, str]:
        """
        Use fuzzy matching to map CSV headers to standard names
        
        Args:
            csv_headers: List of CSV column headers
            table_type: 'company' or 'people'
            
        Returns:
            Dictionary mapping original headers to standard headers
        """
        self._update_progress(f"Mapping headers for {table_type} table")
        
        # Get field mappings from config
        if table_type == 'company':
            standard_mappings = self.config_manager.get_company_mappings()
        elif table_type == 'people':
            standard_mappings = self.config_manager.get_people_mappings()
        else:
            raise ValueError(f"Invalid table type: {table_type}")
        
        header_mapping = {}
        matched_standards = set()
        
        for original_header in csv_headers:
            best_match = None
            best_score = 0
            best_standard = None
            
            # Try to match against all standard headers and their alternatives
            for standard_header, alternatives in standard_mappings.items():
                # Check direct match with standard header
                score = fuzz.ratio(original_header.lower(), standard_header.lower())
                if score > best_score:
                    best_score = score
                    best_match = standard_header
                    best_standard = standard_header
                
                # Check against alternatives
                for alternative in alternatives:
                    score = fuzz.ratio(original_header.lower(), alternative.lower())
                    if score > best_score:
                        best_score = score
                        best_match = standard_header
                        best_standard = standard_header
            
            # Use match if score is above threshold and standard header not already matched
            threshold = 85  # Can be made configurable
            if best_score >= threshold and best_standard not in matched_standards:
                header_mapping[original_header] = best_match
                matched_standards.add(best_standard)
                logger.debug(f"Mapped '{original_header}' to '{best_match}' (score: {best_score})")
            else:
                # Keep original header if no good match found
                header_mapping[original_header] = original_header
                logger.debug(f"No mapping found for '{original_header}' (best score: {best_score})")
        
        logger.info(f"Header mapping complete: {len(header_mapping)} headers processed")
        return header_mapping
    
    def clean_domains(self, df: pd.DataFrame, domain_columns: List[str]) -> pd.DataFrame:
        """
        Clean and normalize domain/website fields
        
        Args:
            df: DataFrame to clean
            domain_columns: List of column names containing domains
            
        Returns:
            DataFrame with cleaned domains
        """
        if not domain_columns:
            return df
        
        self._update_progress("Cleaning and normalizing domains")
        
        # Get cleaning rules from config
        cleaning_rules = self.config_manager.get_cleaning_rules()
        prefixes_to_remove = cleaning_rules.get('domain_prefixes_to_remove', [])
        suffixes_to_remove = cleaning_rules.get('domain_suffixes_to_remove', [])
        
        domains_cleaned = 0
        
        for column in domain_columns:
            if column in df.columns:
                original_values = df[column].copy()
                
                # Clean domains
                df[column] = df[column].astype(str).apply(lambda x: self._clean_single_domain(
                    x, prefixes_to_remove, suffixes_to_remove
                ))
                
                # Count how many were actually cleaned
                domains_cleaned += (original_values != df[column]).sum()
        
        self.stats['domains_cleaned'] = domains_cleaned
        logger.info(f"Cleaned {domains_cleaned} domain entries")
        return df
    
    def _clean_single_domain(self, domain: str, prefixes: List[str], suffixes: List[str]) -> str:
        """Clean a single domain value"""
        if pd.isna(domain) or domain in ['nan', 'None', '']:
            return ''
        
        domain = str(domain).strip()
        
        # Remove prefixes
        for prefix in prefixes:
            if domain.lower().startswith(prefix.lower()):
                domain = domain[len(prefix):]
                break
        
        # Remove suffixes
        for suffix in suffixes:
            if domain.lower().endswith(suffix.lower()):
                domain = domain[:-len(suffix)]
                break
        
        # Convert to lowercase and strip
        domain = domain.lower().strip()
        
        return domain if domain and domain != 'nan' else ''
    
    def normalize_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize and clean data fields
        
        Args:
            df: DataFrame to normalize
            
        Returns:
            DataFrame with normalized data
        """
        self._update_progress("Normalizing data fields")
        
        # Get cleaning rules
        cleaning_rules = self.config_manager.get_cleaning_rules()
        
        # Normalize whitespace and remove extra spaces
        if cleaning_rules.get('normalize_whitespace', True):
            for column in df.select_dtypes(include=['object']).columns:
                df[column] = df[column].astype(str).apply(lambda x: re.sub(r'\s+', ' ', str(x).strip()) if pd.notna(x) and x != 'nan' else '')
        
        # Standardize case for specific field types
        case_rules = cleaning_rules.get('standardize_case', {})
        
        # Title case for names
        if case_rules.get('names') == 'title_case':
            name_columns = [col for col in df.columns if any(name_word in col.lower() for name_word in ['name', 'title'])]
            for column in name_columns:
                if column in df.columns:
                    df[column] = df[column].apply(lambda x: str(x).title() if pd.notna(x) and x and x != 'nan' else '')
        
        return df
    
    def deduplicate_records(self, df: pd.DataFrame, table_type: str) -> pd.DataFrame:
        """
        Remove duplicates with smart data merging
        
        Args:
            df: DataFrame to deduplicate
            table_type: 'company' or 'people'
            
        Returns:
            DataFrame with duplicates removed and data merged
        """
        self._update_progress(f"Deduplicating {table_type} records with smart merging")
        
        if table_type == 'company':
            # Company deduplication: Company Name + Company Domain
            key_columns = ['Company Name', 'Company Domain']
        elif table_type == 'people':
            # People deduplication: Full Name + Company Name
            key_columns = ['Full Name', 'Company Name']
        else:
            raise ValueError(f"Invalid table type: {table_type}")
        
        # Check if required columns exist
        available_keys = [col for col in key_columns if col in df.columns]
        if not available_keys:
            logger.warning(f"No deduplication key columns found for {table_type}")
            return df
        
        original_count = len(df)
        logger.info(f"Starting deduplication with {original_count} records using keys: {available_keys}")
        
        # Create a composite key for grouping, handling missing values
        df['_dedup_key'] = df[available_keys].apply(
            lambda row: '|'.join([str(val).lower().strip() for val in row if pd.notna(val) and str(val).strip()]), 
            axis=1
        )
        
        # Group by deduplication key and merge data
        merged_records = []
        fields_merged = 0
        
        for key, group in df.groupby('_dedup_key'):
            if key == '':  # Skip empty keys
                merged_records.extend(group.drop('_dedup_key', axis=1).to_dict('records'))
                continue
                
            if len(group) > 1:
                # Multiple records with same key - merge them
                merged_record = self._merge_duplicate_records(group.drop('_dedup_key', axis=1))
                fields_merged += len(group) - 1  # Count merged records
                merged_records.append(merged_record)
            else:
                # Single record - keep as is
                merged_records.append(group.drop('_dedup_key', axis=1).iloc[0].to_dict())
        
        # Create new DataFrame from merged records
        result_df = pd.DataFrame(merged_records)
        
        duplicates_removed = original_count - len(result_df)
        self.stats['duplicates_removed'] = duplicates_removed
        self.stats['fields_merged'] = fields_merged
        self.stats['merged_records'] = len(result_df)
        
        logger.info(f"Deduplication complete: {duplicates_removed} duplicates removed, {fields_merged} records merged")
        return result_df
    
    def _merge_duplicate_records(self, records_group: pd.DataFrame) -> Dict:
        """
        Merge multiple duplicate records into one complete record
        
        Args:
            records_group: Group of duplicate records
            
        Returns:
            Dictionary representing merged record
        """
        merged = {}
        
        for column in records_group.columns:
            # Get all non-empty values for this column
            values = []
            for _, row in records_group.iterrows():
                val = row[column]
                if pd.notna(val) and str(val).strip() and str(val).lower() not in ['nan', 'none', '']:
                    values.append(str(val).strip())
            
            if values:
                # Use the longest/most complete value
                merged[column] = max(values, key=len)
            else:
                merged[column] = ''
        
        return merged
    
    def merge_csv_files(self, file_paths: List[str], table_type: str) -> pd.DataFrame:
        """
        Combine multiple CSV files into single DataFrame
        
        Args:
            file_paths: List of CSV file paths
            table_type: 'company' or 'people'
            
        Returns:
            Combined DataFrame with standardized headers
        """
        self._update_progress(f"Merging {len(file_paths)} CSV files")
        
        combined_data = []
        
        for i, file_path in enumerate(file_paths):
            try:
                # Read CSV file
                df = pd.read_csv(file_path)
                logger.info(f"Read file {file_path}: {len(df)} records, {len(df.columns)} columns")
                
                # Map headers to standard names
                header_mapping = self.map_headers(df.columns.tolist(), table_type)
                df = df.rename(columns=header_mapping)
                
                # Add to combined data
                combined_data.append(df)
                
                self._update_progress(
                    f"Processed file {i+1}/{len(file_paths)}: {file_path}",
                    percentage=(i+1) / len(file_paths) * 30  # 30% for file reading
                )
                
            except Exception as e:
                logger.error(f"Error processing file {file_path}: {e}")
                continue
        
        if not combined_data:
            raise ValueError("No valid CSV files to process")
        
        # Combine all DataFrames
        combined_df = pd.concat(combined_data, ignore_index=True, sort=False)
        self.stats['total_records'] = len(combined_df)
        
        logger.info(f"Combined {len(file_paths)} files into {len(combined_df)} total records")
        return combined_df
    
    def export_to_csv(self, df: pd.DataFrame, table_type: str, session_id: str) -> str:
        """
        Export processed DataFrame to CSV file
        
        Args:
            df: DataFrame to export
            table_type: 'company' or 'people' 
            session_id: Session ID for file organization
            
        Returns:
            Path to exported CSV file
        """
        self._update_progress("Exporting processed data to CSV")
        
        # Create session directory if it doesn't exist
        session_dir = f"uploads/{session_id}"
        os.makedirs(session_dir, exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
        filename = f"{table_type}_leads_{timestamp}.csv"
        file_path = os.path.join(session_dir, filename)
        
        # Export to CSV
        df.to_csv(file_path, index=False)
        
        logger.info(f"Exported {len(df)} records to {file_path}")
        return file_path
    
    def process_files(self, file_paths: List[str], table_type: str, session_id: str) -> Tuple[pd.DataFrame, str]:
        """
        Main processing pipeline
        
        Args:
            file_paths: List of CSV file paths to process
            table_type: 'company' or 'people'
            session_id: Session ID for file organization
            
        Returns:
            Tuple of (processed_dataframe, exported_csv_path)
        """
        start_time = datetime.now()
        
        try:
            self._update_progress("Starting CSV processing pipeline", 0)
            
            # Step 1: Merge CSV files (0-30%)
            df = self.merge_csv_files(file_paths, table_type)
            self._update_progress("Files merged successfully", 30)
            
            # Step 2: Clean domains (30-50%)
            domain_columns = self._get_domain_columns(df.columns, table_type)
            df = self.clean_domains(df, domain_columns)
            self._update_progress("Domain cleaning completed", 50)
            
            # Step 3: Normalize data (50-70%)
            df = self.normalize_data(df)
            self._update_progress("Data normalization completed", 70)
            
            # Step 4: Deduplicate with smart merging (70-90%)
            df = self.deduplicate_records(df, table_type)
            self._update_progress("Deduplication completed", 90)
            
            # Step 5: Export to CSV (90-100%)
            export_path = self.export_to_csv(df, table_type, session_id)
            
            # Calculate processing time
            processing_time = (datetime.now() - start_time).total_seconds()
            self.stats['processing_time'] = processing_time
            
            self._update_progress("Processing completed successfully", 100, self.stats)
            
            logger.info(f"Processing completed in {processing_time:.2f} seconds")
            return df, export_path
            
        except Exception as e:
            logger.error(f"Processing failed: {e}")
            self._update_progress(f"Processing failed: {str(e)}", None)
            raise
    
    def _get_domain_columns(self, columns: List[str], table_type: str) -> List[str]:
        """Get list of columns that contain domain/website data"""
        domain_keywords = ['domain', 'website', 'url', 'site']
        return [col for col in columns if any(keyword in col.lower() for keyword in domain_keywords)]
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """Get current processing statistics"""
        return self.stats.copy()
    
    def validate_data(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Perform data quality checks
        
        Args:
            df: DataFrame to validate
            
        Returns:
            Dictionary with validation results
        """
        validation_results = {
            'total_records': len(df),
            'total_columns': len(df.columns),
            'empty_records': df.isnull().all(axis=1).sum(),
            'duplicate_records': df.duplicated().sum(),
            'column_completeness': {}
        }
        
        # Check completeness of each column
        for column in df.columns:
            non_empty = df[column].notna().sum()
            completeness = (non_empty / len(df)) * 100 if len(df) > 0 else 0
            validation_results['column_completeness'][column] = {
                'non_empty_count': int(non_empty),
                'completeness_percentage': round(completeness, 2)
            }
        
        return validation_results 