"""
CSV Processor - Uses Existing Phase 1, 2, 3 Logic
Preserves all the hard work done on the three-phase processing system
"""

import asyncio
import os
import tempfile
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from simple_config import Config
from src.config_manager import ConfigManager
from src.header_mapper import N8NHeaderMapper
# Import the EXISTING phase classes (preserve the logic!)
from src.phase1_merger import Phase1Merger
from src.phase2_standardizer import Phase2Standardizer
from src.phase3_enricher import Phase3Enricher


class CSVProcessor:
    """Uses existing Phase 1, 2, 3 logic - preserves all the hard work!"""

    def __init__(self):
        self.config = Config()

        # Initialize existing config manager with config file path
        self.config_manager = ConfigManager("config/field_mappings.json")

        # Initialize the EXISTING phase processors
        self.phase1_merger = Phase1Merger()
        self.phase2_standardizer = Phase2Standardizer(self.config_manager)
        self.phase3_enricher = Phase3Enricher(self.config_manager)

        # Initialize n8n header mapper
        self.header_mapper = N8NHeaderMapper()

    def count_records(self, file_path: str) -> int:
        """Count records in a CSV file"""
        try:
            # Use pandas to properly count data rows (excludes empty lines)
            df = pd.read_csv(file_path)
            return len(df)
        except Exception as e:
            print(f"Error counting records in {file_path}: {e}")
            return 0

    def process_files_sync(
        self,
        file_paths: List[str],
        job_id: str,
        table_type: str,
        output_dir: str,
        record_limit: Optional[int] = None,
    ) -> str:
        """Process files synchronously using EXISTING phase logic"""
        print(f"🔄 Starting synchronous processing for job {job_id}")

        # Phase 1: Use EXISTING merger logic
        print("📁 Phase 1: Merging CSV files...")
        merged_df = self.phase1_merger.merge_raw_files(file_paths)
        print(f"✅ Phase 1 complete: {len(merged_df)} total records")

        # Phase 2: Use EXISTING standardizer logic
        print("🤖 Phase 2: AI standardization...")
        standardized_df, n8n_response = asyncio.run(
            self._run_phase2_async(merged_df, table_type, job_id)
        )
        print("✅ Phase 2 complete: Headers standardized")

        # Phase 3: Use EXISTING enricher logic
        print("📧 Phase 3: Email enrichment...")
        final_df = self.phase3_enricher.enrich_and_deduplicate(
            standardized_df, table_type
        )
        print(f"✅ Phase 3 complete: {len(final_df)} final records")

        # Apply record limit if specified (for testing)
        if record_limit and record_limit < len(final_df):
            final_df = final_df.head(record_limit)
            print(
                f"📊 Limited to {record_limit} records for testing (total available: {len(final_df)})"
            )

        # Save result
        result_path = os.path.join(output_dir, f"processed_{job_id}.csv")
        final_df.to_csv(result_path, index=False)
        print(f"💾 Result saved: {result_path}")

        return result_path

    async def _run_phase2_async(
        self, merged_df: pd.DataFrame, table_type: str, session_id: str
    ) -> Tuple[pd.DataFrame, Dict]:
        """Run Phase 2 async (required by existing logic)"""
        return await self.phase2_standardizer.map_and_standardize(
            merged_df=merged_df,
            table_type=table_type,
            session_id=session_id,
            header_mapper=self.header_mapper,
        )

    # REMOVED: Using existing Phase1Merger.merge_raw_files() instead

    # REMOVED: Using existing Phase2Standardizer.map_and_standardize() instead

    # REMOVED: Using existing N8NHeaderMapper instead

    # REMOVED: Using existing Phase2Standardizer logic instead

    # REMOVED: Using existing ConfigManager field mappings instead

    # REMOVED: Using existing Phase3Enricher.enrich_and_deduplicate_emails() instead

    # REMOVED: All individual methods - using existing Phase3Enricher class methods instead
