import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Tuple, Optional, Any
import re
from datetime import datetime
import os

from src.logging_config import setup_module_logger

logger = setup_module_logger(__name__)

class Phase3Enricher:
    """
    Phase 3: Email enrichment and deduplication
    
    Handles email consolidation with ranking (Gmail > Yahoo > Outlook > Hotmail)
    and smart deduplication with data merging.
    """
    
    def __init__(self, config_manager, progress_callback=None):
        self.config_manager = config_manager
        self.progress_callback = progress_callback
        self.stats = {
            'emails_enriched': 0,
            'personal_emails_ranked': 0,
            'work_emails_identified': 0,
            'duplicates_removed': 0,
            'records_merged': 0,
            'domains_enriched': 0,
            'processing_time': 0
        }
        
        # Email domain rankings (higher number = higher priority)
        self.personal_email_rankings = {
            'gmail.com': 4,
            'yahoo.com': 3,
            'outlook.com': 2,
            'hotmail.com': 1
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
    
    def enrich_and_deduplicate(self, standardized_df: pd.DataFrame, table_type: str) -> pd.DataFrame:
        """
        Main enrichment and deduplication process
        
        Args:
            standardized_df: Standardized DataFrame from Phase 2
            table_type: 'people' or 'company'
            
        Returns:
            Final processed DataFrame
        """
        logger.info("=== PHASE 3: Email enrichment and deduplication ===")
        start_time = datetime.now()
        
        # Step 1: Email enrichment and ranking
        self._update_progress("Step 1: Email enrichment and ranking", 20, "enrich")
        enriched_df = self._enrich_emails(standardized_df)
        
        # Step 2: Domain cleaning
        self._update_progress("Step 2: Domain cleaning", 40, "clean")
        cleaned_df = self._clean_domains(enriched_df)
        
        # Step 3: Data normalization
        self._update_progress("Step 3: Data normalization", 60, "normalize")
        normalized_df = self._normalize_data(cleaned_df)
        
        # Step 4: Smart deduplication
        self._update_progress("Step 4: Smart deduplication", 80, "dedupe")
        deduplicated_df = self._smart_deduplicate(normalized_df, table_type)
        
        # Step 5: Enrich Company Domain from Work Email where missing
        self._update_progress("Step 5: Enriching Company Domain", 85, "enrich_domain")
        enriched_domain_df = self._enrich_company_domain(deduplicated_df)
        
        # Step 6: Clean domains (protocols, www, etc.)
        cleaned_df = self._clean_domains(enriched_domain_df)
        
        # Final result
        final_df = cleaned_df
        
        # Update stats
        self.stats['processing_time'] = (datetime.now() - start_time).total_seconds()
        
        logger.info(f"✅ PHASE 3 COMPLETE:")
        logger.info(f"   • Emails enriched: {self.stats['emails_enriched']}")
        logger.info(f"   • Personal emails ranked: {self.stats['personal_emails_ranked']}")
        logger.info(f"   • Work emails identified: {self.stats['work_emails_identified']}")
        logger.info(f"   • Duplicates removed: {self.stats['duplicates_removed']}")
        logger.info(f"   • Records merged: {self.stats['records_merged']}")
        logger.info(f"   • Processing time: {self.stats['processing_time']:.2f}s")
        
        return final_df
    
    def _enrich_emails(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Enrich email data with ranking and consolidation
        
        Args:
            df: DataFrame to process
            
        Returns:
            DataFrame with enriched email data
        """
        logger.info("Enriching email data...")
        df = df.copy()
        
        # Find all email columns (not just Work Email and Personal Email)
        email_columns = [col for col in df.columns if 'email' in col.lower()]
        logger.info(f"Found email columns: {email_columns}")
        
        # Process each row for email enrichment
        for idx in df.index:
            personal_emails = []
            work_emails = []
            
            # Collect all emails from all email columns
            for col in email_columns:
                email = df.at[idx, col]
                if pd.notna(email) and email and str(email).strip() and str(email).lower() != 'nan':
                    clean_email = str(email).strip().lower()
                    
                    if self._is_personal_email(clean_email):
                        personal_emails.append(clean_email)
                    else:
                        work_emails.append(clean_email)
            
            # Rank and select best personal email
            if personal_emails:
                best_personal = self._rank_personal_emails(personal_emails)
                df.at[idx, 'Personal Email'] = best_personal
                self.stats['personal_emails_ranked'] += 1
            else:
                df.at[idx, 'Personal Email'] = ''
            
            # Select best work email (first valid one)
            if work_emails:
                df.at[idx, 'Work Email'] = work_emails[0]  # Take first work email
                self.stats['work_emails_identified'] += 1
            else:
                df.at[idx, 'Work Email'] = ''
            
            if personal_emails or work_emails:
                self.stats['emails_enriched'] += 1
        
        # Clear out other email columns to avoid confusion
        for col in email_columns:
            if col not in ['Personal Email', 'Work Email']:
                df[col] = ''
        
        return df
    
    def _is_personal_email(self, email: str) -> bool:
        """Check if email domain is personal"""
        if not email or '@' not in email:
            return False
        
        domain = email.split('@')[-1].lower()
        return domain in self.personal_email_rankings
    
    def _rank_personal_emails(self, emails: List[str]) -> str:
        """
        Rank personal emails by domain priority
        
        Args:
            emails: List of personal email addresses
            
        Returns:
            Best ranked email address
        """
        if not emails:
            return ''
        
        # Score emails by domain ranking
        scored_emails = []
        for email in emails:
            domain = email.split('@')[-1].lower()
            score = self.personal_email_rankings.get(domain, 0)
            scored_emails.append((score, email))
        
        # Sort by score (highest first)
        scored_emails.sort(key=lambda x: x[0], reverse=True)
        
        return scored_emails[0][1]  # Return highest scored email
    
    def _enrich_company_domain(self, df: pd.DataFrame) -> pd.DataFrame:
        """Enrich Company Domain from Work Email where missing"""
        logger.info("Enriching Company Domain from Work Email where missing...")
        df = df.copy()
        
        # Check if required columns exist
        if 'Company Domain' not in df.columns or 'Work Email' not in df.columns:
            logger.warning("Company Domain or Work Email column not found, skipping domain enrichment")
            return df
        
        enriched_count = 0
        
        for idx in df.index:
            company_domain = df.at[idx, 'Company Domain']
            work_email = df.at[idx, 'Work Email']
            
            # If Company Domain is empty but Work Email is present
            if (pd.isna(company_domain) or not str(company_domain).strip() or 
                str(company_domain).lower() in ['nan', 'none', 'null', '']) and \
               (not pd.isna(work_email) and str(work_email).strip() and 
                '@' in str(work_email) and str(work_email).lower() not in ['nan', 'none', 'null', '']):
                
                try:
                    # Extract domain from work email
                    email_domain = str(work_email).strip().split('@')[1].lower()
                    
                    # Skip common free email providers
                    free_providers = {
                        'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 
                        'icloud.com', 'aol.com', 'live.com', 'msn.com', 'mail.com',
                        'ymail.com', 'rocketmail.com', 'protonmail.com', 'zoho.com'
                    }
                    
                    if email_domain not in free_providers:
                        df.at[idx, 'Company Domain'] = email_domain
                        enriched_count += 1
                        logger.debug(f"Enriched Company Domain from Work Email: {work_email} -> {email_domain}")
                        
                except (IndexError, AttributeError) as e:
                    # Invalid email format, skip
                    logger.debug(f"Invalid email format for domain extraction: {work_email}")
                    continue
        
        logger.info(f"Enriched {enriched_count} Company Domain fields from Work Email")
        self.stats['domains_enriched'] = enriched_count
        
        return df
    
    def _clean_domains(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean domain data by removing protocols and www"""
        logger.info("Cleaning domain data...")
        df = df.copy()
        
        domain_columns = [col for col in df.columns if 'domain' in col.lower() or 'website' in col.lower()]
        
        for col in domain_columns:
            if col in df.columns:
                df[col] = df[col].apply(self._clean_domain_value)
        
        return df
    
    def _clean_domain_value(self, value) -> str:
        """Clean a single domain value"""
        if pd.isna(value) or not value or str(value).lower() in ['nan', 'none', 'null']:
            return ''
        
        domain = str(value).strip().lower()
        
        # Remove protocols
        domain = re.sub(r'^https?://', '', domain)
        domain = re.sub(r'^www\.', '', domain)
        
        # Remove trailing slashes and paths
        domain = domain.split('/')[0]
        
        # Remove query parameters
        domain = domain.split('?')[0]
        
        return domain
    
    def _normalize_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize data fields"""
        logger.info("Normalizing data...")
        df = df.copy()
        
        # Normalize whitespace
        for column in df.select_dtypes(include=['object']).columns:
            if column != 'Source':  # Don't normalize Source column
                df[column] = df[column].astype(str).apply(
                    lambda x: re.sub(r'\s+', ' ', str(x).strip()) if pd.notna(x) and x != 'nan' else ''
                )
        
        # Title case for name columns
        name_columns = [col for col in df.columns if any(word in col.lower() for word in ['name', 'title'])]
        for col in name_columns:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: str(x).title() if x and str(x).lower() != 'nan' else '')
        
        return df
    
    def _smart_deduplicate(self, df: pd.DataFrame, table_type: str) -> pd.DataFrame:
        """
        Smart deduplication with record merging
        
        Args:
            df: DataFrame to deduplicate
            table_type: 'people' or 'company'
            
        Returns:
            Deduplicated DataFrame with merged records
        """
        logger.info("Starting smart deduplication...")
        original_count = len(df)
        
        # Define deduplication keys based on table type
        if table_type == 'people':
            # For people: use email, LinkedIn profile, or full name + company combination
            dedup_keys = ['Work Email', 'Personal Email', 'LinkedIn Profile', 'Full Name', 'Company Name']
        else:  # company
            dedup_keys = ['Company Name', 'Company Domain', 'Company LinkedIn']
        
        # Filter to available keys
        available_keys = [key for key in dedup_keys if key in df.columns]
        
        if not available_keys:
            logger.warning("No deduplication keys available")
            return df
        
        logger.info(f"Using deduplication keys: {available_keys}")
        
        # Create deduplication groups
        df = df.copy()
        df['_dedup_key'] = ''
        
        # Build deduplication key for each row
        for idx in df.index:
            key_parts = []
            for key_col in available_keys:
                value = df.at[idx, key_col]
                if value and str(value).strip() and str(value).lower() not in ['nan', 'none', '']:
                    key_parts.append(str(value).strip().lower())
            
            if key_parts:
                df.at[idx, '_dedup_key'] = '|'.join(key_parts)
            else:
                df.at[idx, '_dedup_key'] = f'unique_{idx}'  # Ensure unique key for empty records
        
        # Group by deduplication key and merge
        grouped = df.groupby('_dedup_key')
        merged_records = []
        
        for dedup_key, group in grouped:
            if len(group) > 1:
                # Multiple records - merge them
                merged_record = self._merge_duplicate_records(group)
                merged_records.append(merged_record)
                self.stats['records_merged'] += len(group) - 1
                self.stats['duplicates_removed'] += len(group) - 1
            else:
                # Single record - keep as is
                merged_records.append(group.iloc[0].to_dict())
        
        # Create final DataFrame
        final_df = pd.DataFrame(merged_records)
        
        # Remove the temporary dedup key column
        if '_dedup_key' in final_df.columns:
            final_df = final_df.drop(columns=['_dedup_key'])
        
        logger.info(f"Deduplication complete: {original_count} → {len(final_df)} records")
        
        return final_df
    
    def _merge_duplicate_records(self, group: pd.DataFrame) -> Dict[str, Any]:
        """
        Merge multiple duplicate records into one complete record
        
        Args:
            group: Group of duplicate records
            
        Returns:
            Dictionary representing merged record
        """
        merged = {}
        
        for column in group.columns:
            if column == '_dedup_key':
                continue
                
            # Get all non-empty values for this column
            values = []
            for _, row in group.iterrows():
                val = row[column]
                if pd.notna(val) and str(val).strip() and str(val).lower() not in ['nan', 'none', '']:
                    clean_val = str(val).strip()
                    if clean_val not in values:  # Avoid duplicates
                        values.append(clean_val)
            
            if values:
                if column == 'Source':
                    # For Source, combine all sources
                    merged[column] = '; '.join(values)
                else:
                    # For other columns, use the longest/most complete value
                    merged[column] = max(values, key=len)
            else:
                merged[column] = ''
        
        return merged
    
    def export_results(self, df: pd.DataFrame, table_type: str, session_id: str) -> str:
        """
        Export final results to CSV
        
        Args:
            df: Final processed DataFrame
            table_type: 'people' or 'company'
            session_id: Session ID for file organization
            
        Returns:
            Path to exported CSV file
        """
        # Create session directory if it doesn't exist
        session_dir = f"uploads/{session_id}"
        os.makedirs(session_dir, exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
        filename = f"{table_type}_leads_processed_{timestamp}.csv"
        file_path = os.path.join(session_dir, filename)
        
        # Export to CSV
        df.to_csv(file_path, index=False, encoding='utf-8')
        
        logger.info(f"Exported {len(df)} processed records to {file_path}")
        return file_path
    
    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics"""
        return self.stats.copy() 