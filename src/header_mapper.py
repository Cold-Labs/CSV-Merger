import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)


class N8NHeaderMapper:
    """Sends headers to n8n webhook for AI mapping"""

    def __init__(
        self, webhook_url: str = "https://n8n.coldlabs.ai/webhook/csv-header-mapping"
    ):
        """
        Initialize n8n header mapper

        Args:
            webhook_url: n8n webhook URL for header mapping
        """
        self.webhook_url = webhook_url
        self.timeout = 120  # 120 seconds timeout for n8n response

        # Load standard target headers from field mappings
        self.standard_headers = self._load_standard_headers()

        # Load manual filters for unwanted header terms
        self.unwanted_terms = self._load_unwanted_terms()

    def _load_standard_headers(self) -> Dict[str, List[str]]:
        """Load standard headers for each table type from field mappings"""
        try:
            with open("config/field_mappings.json", "r") as f:
                mappings = json.load(f)

            return {
                "company": list(mappings["company_mappings"].keys()),
                "people": list(mappings["people_mappings"].keys()),
            }
        except Exception as e:
            logger.error(f"Failed to load field mappings: {e}")
            # Fallback to hardcoded standard headers
            return {
                "company": [
                    "Company Name",
                    "Company Domain",
                    "Company Description",
                    "Company Industry",
                    "Company Employee Count",
                    "Company LinkedIn",
                    "Company LinkedIn Handle",
                    "Year Founded",
                    "Company Location",
                ],
                "people": [
                    "First Name",
                    "Last Name",
                    "Full Name",
                    "Job Title",
                    "LinkedIn Profile",
                    "Person Location",
                    "Work Email",
                    "Personal Email",
                    "Phone Number",
                    "Company Name",
                    "Company Description",
                    "Company Website",
                    "Company LinkedIn URL",
                    "Company Employee Count",
                    "Company Location",
                    "Company Industry",
                ],
            }

    def _load_unwanted_terms(self) -> List[str]:
        """Load unwanted terms from configuration file"""
        try:
            with open("config/header_filters.json", "r") as f:
                filters = json.load(f)

            terms = filters.get("unwanted_header_terms", [])
            logger.info(f"Loaded {len(terms)} unwanted header terms from config")
            return [term.lower() for term in terms]

        except Exception as e:
            logger.error(f"Failed to load header filters: {e}")
            # Fallback to basic hardcoded filters
            fallback_terms = [
                "avatar",
                "photo",
                "picture",
                "image",
                "funding",
                "revenue",
                "postal_code",
                "zip_code",
                "keywords",
                "status",
                "timestamp",
            ]
            logger.info(f"Using fallback filters: {len(fallback_terms)} terms")
            return fallback_terms

    def add_unwanted_terms(self, new_terms: List[str]) -> None:
        """
        Easily add more unwanted terms to the filter list

        Args:
            new_terms: List of terms to add to the unwanted filter

        Example:
            mapper.add_unwanted_terms(['new_term', 'another_term'])
        """
        self.unwanted_terms.extend([term.lower() for term in new_terms])
        logger.info(f"Added {len(new_terms)} new unwanted terms to filter: {new_terms}")

    def get_unwanted_terms(self) -> List[str]:
        """Get current list of unwanted terms for debugging"""
        return self.unwanted_terms.copy()

    def _is_hash_like_id(self, value: str) -> bool:
        """Check if a value looks like a hash ID"""
        if not isinstance(value, str) or len(value) < 10:
            return False

        # Common hash patterns
        hash_patterns = [
            r"^[a-f0-9]{24}$",  # MongoDB ObjectId (24 hex chars)
            r"^[a-f0-9]{32}$",  # MD5 hash
            r"^[a-f0-9]{40}$",  # SHA1 hash
            r"^[a-f0-9]{64}$",  # SHA256 hash
            r"^[A-Za-z0-9_-]{20,}$",  # Base64-like IDs
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",  # UUID
        ]

        for pattern in hash_patterns:
            if re.match(pattern, str(value).strip()):
                return True
        return False

    def _is_useless_column(self, column_name: str, sample_value: str) -> bool:
        """Determine if a column should be filtered out"""
        column_lower = column_name.lower()
        value_str = str(sample_value).strip()

        # Check manual filters first (easy to customize)
        for unwanted_term in self.unwanted_terms:
            if unwanted_term.lower() in column_lower:
                return True

        # Filter out obvious ID columns
        if any(
            id_term in column_lower for id_term in ["_id", "/id", "uid", "guid", "uuid"]
        ):
            return True

        # Filter out hash-like values
        if self._is_hash_like_id(value_str):
            return True

        # Filter out boolean-like columns with empty/false values
        if value_str.lower() in ["", "false", "true", "0", "1", "none", "null"]:
            # But keep important fields even if they're empty (for composite sample enrichment)
            important_fields = [
                "verified",
                "active",
                "current",
                "primary",
                "valid",  # booleans
                "email",
                "e-mail",
                "mail",  # email fields
                "phone",
                "telephone",
                "mobile",
                "cell",  # phone fields
                "name",
                "title",
                "position",
                "role",  # key identity fields
                "company",
                "organization",
                "domain",
                "website",  # company fields
                "linkedin",
                "twitter",
                "facebook",
                "instagram",
                "youtube",
                "tiktok",  # social media fields
            ]
            if not any(term in column_lower for term in important_fields):
                return True

        # Filter out nested array indices that are empty
        if re.match(r".+/\d+$", column_name) and value_str == "":
            return True

        # Filter out obvious tracking/metadata columns
        tracking_terms = [
            "tracking",
            "metadata",
            "internal",
            "system",
            "debug",
            "test_",
        ]
        if any(term in column_lower for term in tracking_terms):
            return True

        # Filter out very long nested paths that are likely junk
        if column_name.count("/") > 2:  # More than 2 levels deep
            return True

        return False

    def _clean_sample_record(self, sample_record: Dict[str, str]) -> Dict[str, str]:
        """Remove useless columns from sample record"""
        cleaned_record = {}
        removed_count = 0
        removed_by_manual_filter = 0

        for column, value in sample_record.items():
            if self._is_useless_column(column, value):
                removed_count += 1
                # Check if it was removed by manual filter
                column_lower = column.lower()
                for unwanted_term in self.unwanted_terms:
                    if unwanted_term.lower() in column_lower:
                        removed_by_manual_filter += 1
                        break
                logger.debug(f"Filtering out column: {column} (value: '{value}')")
            else:
                cleaned_record[column] = value

        logger.info(
            f"Filtered out {removed_count} useless columns (including {removed_by_manual_filter} by manual filters), kept {len(cleaned_record)} useful columns"
        )
        if removed_count > 0:
            logger.info(f"Kept columns: {list(cleaned_record.keys())}")
        if len(cleaned_record) == 0:
            logger.warning(
                "WARNING: All columns were filtered out! This might be too aggressive."
            )
        return cleaned_record

    def _create_enriched_sample(
        self,
        cleaned_sample_record: Dict[str, str],
        file_path: str,
        max_rows_to_scan: int = 1000,
    ) -> Dict[str, str]:
        """
        🚀 BULLETPROOF Sample Enrichment: Fill empty fields from other rows (AFTER filtering)

        Args:
            cleaned_sample_record: Already filtered sample record (from _clean_sample_record)
            file_path: Path to the CSV file (for re-reading and logging)
            max_rows_to_scan: Maximum number of rows to scan for filling empty fields (conservative: 1000)

        Returns:
            Dictionary with enriched sample record where empty fields are filled from other rows
            Falls back to original sample if ANYTHING goes wrong (bulletproof)
        """
        start_time = time.time()
        filename = file_path.split("/")[-1]

        # MODIFIED: Always create a composite sample for better AI mapping
        # Track which fields are empty, but also enrich non-empty fields if we find better data
        empty_fields = [
            col
            for col, value in cleaned_sample_record.items()
            if not value
            or value.strip() == ""
            or value.lower() in ["nan", "null", "none"]
        ]

        logger.info(
            f"🔍 COMPOSITE SAMPLE for {filename}: {len(empty_fields)} empty fields to fill: {empty_fields}"
        )
        logger.info(
            f"🔍 Will also scan for better data in non-empty fields to create best possible sample"
        )

        logger.info(
            f"🔍 SAMPLE ENRICHMENT for {filename}: Found {len(empty_fields)} empty fields to fill: {empty_fields}"
        )

        # 🛡️ BULLETPROOF: Wrap everything in try/catch
        try:
            # Re-read the file with more rows for enrichment scanning
            df_full = pd.read_csv(file_path, nrows=max_rows_to_scan, low_memory=False)

            # Apply the SAME column cleaning as before (to match the cleaned sample)
            df_full_cleaned = df_full.dropna(axis=1, how="all")
            for col in df_full_cleaned.columns:
                if df_full_cleaned[col].astype(str).str.strip().eq("").all():
                    df_full_cleaned = df_full_cleaned.drop(columns=[col])

            # Only keep columns that exist in our cleaned sample (after filtering)
            available_columns = [
                col
                for col in cleaned_sample_record.keys()
                if col in df_full_cleaned.columns
            ]
            df_enrichment = df_full_cleaned[available_columns]

            if len(df_enrichment) <= 1:
                logger.info(
                    f"⚠️ Only {len(df_enrichment)} rows available for enrichment, skipping"
                )
                return cleaned_sample_record

        except Exception as e:
            logger.warning(
                f"⚠️ Could not re-read file for enrichment: {e} - using original sample"
            )
            return cleaned_sample_record

        # Start enrichment process - create BEST POSSIBLE composite sample
        enriched_sample = cleaned_sample_record.copy()
        rows_to_scan = min(max_rows_to_scan, len(df_enrichment))
        filled_fields = []
        improved_fields = []

        # Scan ALL rows to create the best composite sample
        for row_idx in range(
            0, rows_to_scan
        ):  # Start from row 0 (include first row for potential improvements)
            try:
                current_row = df_enrichment.iloc[row_idx].fillna("").astype(str)

                # Check EVERY field to potentially improve the sample
                for field_name in enriched_sample.keys():
                    if field_name not in current_row.index:
                        continue

                    current_value = current_row[field_name]
                    existing_value = enriched_sample[field_name]

                    # Skip if current row has no value
                    if (
                        not current_value
                        or current_value.strip() == ""
                        or current_value.lower() in ["nan", "null", "none"]
                    ):
                        continue

                    current_value = current_value.strip()

                    # If field is empty, fill it
                    if (
                        not existing_value
                        or existing_value.strip() == ""
                        or existing_value.lower() in ["nan", "null", "none"]
                    ):
                        enriched_sample[field_name] = current_value
                        if field_name in empty_fields:
                            empty_fields.remove(field_name)
                        filled_fields.append(f"{field_name} (from row {row_idx + 1})")
                        logger.debug(
                            f"  ✅ Filled empty '{field_name}' with '{current_value}' from row {row_idx + 1}"
                        )

                    # If field has value, check if current value is "better" (longer, more complete)
                    elif len(current_value) > len(existing_value.strip()):
                        old_value = existing_value.strip()
                        enriched_sample[field_name] = current_value
                        improved_fields.append(
                            f"{field_name} ('{old_value[:20]}...' → '{current_value[:20]}...' from row {row_idx + 1})"
                        )
                        logger.debug(
                            f"  📈 Improved '{field_name}': '{old_value[:20]}...' → '{current_value[:20]}...' from row {row_idx + 1}"
                        )

            except Exception as e:
                logger.debug(f"Error processing row {row_idx}: {e}")
                continue

        # Performance and results logging
        elapsed_time = time.time() - start_time
        total_changes = len(filled_fields) + len(improved_fields)

        if total_changes > 0:
            logger.info(
                f"✅ COMPOSITE SAMPLE SUCCESS for {filename}: Made {total_changes} improvements in {elapsed_time:.3f}s by scanning {rows_to_scan} rows:"
            )

            if filled_fields:
                logger.info(f"   📝 Filled {len(filled_fields)} empty fields:")
                for fill_info in filled_fields[:3]:  # Show first 3 filled fields
                    logger.info(f"      • {fill_info}")
                if len(filled_fields) > 3:
                    logger.info(f"      • ... and {len(filled_fields) - 3} more")

            if improved_fields:
                logger.info(
                    f"   📈 Improved {len(improved_fields)} existing fields with better data:"
                )
                for improve_info in improved_fields[:3]:  # Show first 3 improved fields
                    logger.info(f"      • {improve_info}")
                if len(improved_fields) > 3:
                    logger.info(f"      • ... and {len(improved_fields) - 3} more")
        else:
            logger.info(
                f"⚠️ COMPOSITE SAMPLE NO-CHANGE for {filename}: No improvements found in {rows_to_scan} rows (took {elapsed_time:.3f}s)"
            )

        if empty_fields:
            logger.info(
                f"⚠️ ENRICHMENT INCOMPLETE for {filename}: {len(empty_fields)} fields remain empty: {empty_fields[:5]}"
            )
        else:
            logger.info(
                f"🎉 ENRICHMENT COMPLETE for {filename}: All fields filled successfully!"
            )

        # 🛡️ CLEANUP: Memory management
        try:
            del df_full, df_full_cleaned, df_enrichment
            import gc

            gc.collect()
        except:
            pass  # Ignore cleanup errors

        return enriched_sample

    async def extract_headers_and_samples(self, file_paths: List[str]) -> List[Dict]:
        """
        Extract headers and first data row from each CSV file, removing empty columns and junk

        Args:
            file_paths: List of CSV file paths

        Returns:
            List of dictionaries with file info and cleaned sample data
        """
        files_data = []

        # ENHANCED DEBUG: Show exactly what we're processing
        logger.info(f"🔍 === HEADER MAPPER DEBUG ===")
        logger.info(f"🔍 Received {len(file_paths)} file paths to process:")
        for i, path in enumerate(file_paths):
            logger.info(f"🔍   {i+1}. {path}")

        for file_path in file_paths:
            try:
                logger.info(f"🔍 Processing file: {file_path}")

                # ENHANCED DEBUG: Check file existence and permissions
                if not os.path.exists(file_path):
                    logger.error(f"🔍 ❌ FILE DOES NOT EXIST: {file_path}")
                    # Check if parent directory exists
                    parent_dir = os.path.dirname(file_path)
                    logger.error(f"🔍 Parent directory: {parent_dir}")
                    logger.error(f"🔍 Parent exists: {os.path.exists(parent_dir)}")
                    if os.path.exists(parent_dir):
                        logger.error(f"🔍 Parent contents: {os.listdir(parent_dir)}")
                    continue

                file_size = os.path.getsize(file_path)
                logger.info(f"🔍 ✅ File exists: {file_path} ({file_size} bytes)")

                # Check if file is readable
                try:
                    with open(file_path, "r", encoding="utf-8") as test_file:
                        first_line = test_file.readline()
                        logger.info(
                            f"🔍 ✅ File is readable, first line: {first_line[:100]}..."
                        )
                except Exception as read_error:
                    logger.error(f"🔍 ❌ File read error: {read_error}")
                    continue

                # 🆕 ENHANCEMENT: Read more rows for better column detection (increased from 3 to 100)
                df = pd.read_csv(file_path, nrows=100, low_memory=False)
                original_columns = len(df.columns)
                logger.info(f"Original CSV shape: {df.shape} (rows x columns)")
                logger.info(
                    f"Original headers: {list(df.columns)[:10]}..."
                )  # First 10 headers

                # Remove completely empty columns
                df_cleaned = df.dropna(axis=1, how="all")

                # Remove columns that are empty strings
                for col in df_cleaned.columns:
                    if df_cleaned[col].astype(str).str.strip().eq("").all():
                        df_cleaned = df_cleaned.drop(columns=[col])

                # Get cleaned headers and first row
                if len(df_cleaned) > 0:
                    headers = df_cleaned.columns.tolist()
                    first_row = df_cleaned.iloc[0].fillna("").astype(str).tolist()
                    sample_record = dict(zip(headers, first_row))

                    # Apply aggressive filtering to remove junk columns
                    cleaned_sample_record = self._clean_sample_record(sample_record)

                    # TEMPORARY: Don't skip files with no cleaned columns - use original for debugging
                    if not cleaned_sample_record:
                        logger.warning(
                            f"No useful columns found in {file_path} after filtering - using original record for debugging"
                        )
                        cleaned_sample_record = sample_record  # Use original record

                    # 🆕 NEW: ENRICH the cleaned sample by filling empty fields from other rows (AFTER filtering)
                    try:
                        cleaned_sample_record = self._create_enriched_sample(
                            cleaned_sample_record, file_path, max_rows_to_scan=1000
                        )
                        logger.info(
                            f"✅ Sample enrichment completed for {file_path.split('/')[-1]}"
                        )
                    except Exception as enrich_error:
                        logger.warning(
                            f"⚠️ Sample enrichment failed for {file_path.split('/')[-1]}: {enrich_error} - using original sample"
                        )
                        # cleaned_sample_record stays as-is (bulletproof fallback)

                else:
                    logger.warning(f"No data rows found in {file_path}")
                    # MEMORY FIX: Explicit cleanup before continuing
                    del df, df_cleaned
                    import gc

                    gc.collect()
                    continue

                file_info = {
                    "filename": file_path.split("/")[-1],
                    "file_path": file_path,
                    "original_header_count": original_columns,
                    "header_count": len(cleaned_sample_record),
                    "sample_record": cleaned_sample_record,
                }

                files_data.append(file_info)
                logger.info(
                    f"Processed {file_info['filename']}: {original_columns} → {len(cleaned_sample_record)} columns (filtered {original_columns - len(cleaned_sample_record)} junk columns)"
                )

                # MEMORY FIX: Explicit cleanup after each file
                del df, df_cleaned, sample_record, cleaned_sample_record
                import gc

                gc.collect()

            except Exception as e:
                logger.error(f"Failed to extract headers from {file_path}: {e}")
                # MEMORY FIX: Cleanup on error too
                import gc

                gc.collect()
                continue

        return files_data

    async def send_to_n8n(
        self, files_data: List[Dict], table_type: str, session_id: str
    ) -> Dict:
        """
        Send cleaned sample data to n8n webhook

        Args:
            files_data: List of file data with sample records
            table_type: 'company' or 'people'
            session_id: Session ID for tracking

        Returns:
            Dictionary with mapping results from n8n
        """
        # Collect all unique headers from all files
        all_headers = set()
        total_original_headers = 0
        for file_data in files_data:
            all_headers.update(file_data["sample_record"].keys())
            total_original_headers += file_data.get(
                "original_header_count", file_data["header_count"]
            )

        payload = {
            "session_id": session_id,
            "table_type": table_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "files": files_data,  # Only contains filename, file_path, header_count, and sample_record
            "total_files": len(files_data),
            "total_unique_headers": len(all_headers),
            "original_total_headers": total_original_headers,
            "filtering_stats": {
                "headers_before_filtering": total_original_headers,
                "headers_after_filtering": len(all_headers),
                "headers_filtered_out": total_original_headers - len(all_headers),
                "filtering_percentage": (
                    round(
                        (total_original_headers - len(all_headers))
                        / total_original_headers
                        * 100,
                        1,
                    )
                    if total_original_headers > 0
                    else 0
                ),
            },
            "standard_headers": self.standard_headers[
                table_type
            ],  # Add standard headers to payload
        }

        logger.info(f"📊 PAYLOAD OPTIMIZATION RESULTS:")
        logger.info(f"   • Files: {len(files_data)}")
        logger.info(f"   • Headers before filtering: {total_original_headers}")
        logger.info(f"   • Headers after filtering: {len(all_headers)}")
        logger.info(
            f"   • Filtered out: {total_original_headers - len(all_headers)} ({payload['filtering_stats']['filtering_percentage']}%)"
        )
        logger.info(f"   • Payload size significantly reduced!")
        logger.info(f"🎯 STANDARD HEADERS FOR '{table_type.upper()}' TABLE:")
        logger.info(
            f"   • Sending {len(self.standard_headers[table_type])} target headers to n8n AI"
        )
        logger.info(f"   • Headers: {', '.join(self.standard_headers[table_type])}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    headers={"Content-Type": "application/json"},
                ) as response:

                    response_text = await response.text()
                    logger.debug(
                        f"Received raw response from n8n (Status: {response.status}):\n{response_text}"
                    )

                    if response.status == 200:
                        try:
                            result = json.loads(response_text)
                            logger.info(
                                "✅ Successfully received and parsed mapping from n8n"
                            )
                            return result
                        except json.JSONDecodeError:
                            logger.error(
                                f"❌ Failed to decode JSON from n8n response. Response text: {response_text}"
                            )
                            raise Exception("n8n returned invalid JSON")
                    else:
                        logger.error(
                            f"❌ n8n webhook error: {response.status} - {response_text}"
                        )
                        raise Exception(
                            f"n8n webhook failed: {response.status} - {response_text}"
                        )

        except asyncio.TimeoutError:
            logger.error(f"⏰ n8n webhook timeout after {self.timeout} seconds")
            raise Exception("n8n webhook timeout - try again later")
        except Exception as e:
            logger.error(f"💥 Failed to send data to n8n: {e}")
            raise

    async def map_headers(
        self, file_paths: List[str], table_type: str, session_id: str
    ) -> Dict[str, str]:
        """
        Complete header mapping process using n8n

        Args:
            file_paths: List of CSV file paths
            table_type: 'company' or 'people'
            session_id: Session ID for tracking

        Returns:
            Dictionary mapping original headers to standard headers
        """
        logger.info("🔍 === N8N HEADER MAPPING DEBUG START ===")
        logger.info(f"🔍 Input file_paths: {file_paths}")
        logger.info(f"🔍 Input table_type: {table_type}")
        logger.info(f"🔍 Input session_id: {session_id}")

        try:
            # Step 1: Extract headers and samples from all files
            logger.info("Step 1: Extracting headers and sample data from files")
            files_data = await self.extract_headers_and_samples(file_paths)
            logger.info(f"🔍 files_data extracted: {len(files_data)} files")

            if not files_data:
                logger.error("🔍 ERROR: No files_data extracted!")
                raise Exception(
                    "No valid CSV files found or all files failed to process"
                )

            # Step 2: Send to n8n for AI mapping
            logger.info("Step 2: Sending data to n8n for AI mapping")
            n8n_result = await self.send_to_n8n(files_data, table_type, session_id)
            logger.info(f"🔍 n8n_result received: {type(n8n_result)}")
            logger.info(
                f"🔍 n8n_result content: {json.dumps(n8n_result, indent=2) if n8n_result else 'EMPTY'}"
            )

            # Step 3: Extract mapping from n8n response
            logger.info("Step 3: Processing n8n mapping response")
            header_mappings = n8n_result.get("mappings", {})
            logger.info(f"🔍 header_mappings extracted: {header_mappings}")

            if not header_mappings:
                logger.warning("🔍 WARNING: No mappings returned from n8n")
                logger.info(
                    f"🔍 Available keys in n8n_result: {list(n8n_result.keys()) if isinstance(n8n_result, dict) else 'Not a dict'}"
                )
                # Return the full n8n_result instead of empty dict
                logger.info("🔍 Returning full n8n_result instead of empty mappings")
                return n8n_result

            logger.info(f"🔍 Received {len(header_mappings)} header mappings from n8n")
            for original, mapped in header_mappings.items():
                logger.info(f"🔍   {original} → {mapped}")

            logger.info("🔍 === N8N HEADER MAPPING DEBUG END (SUCCESS) ===")
            return header_mappings

        except Exception as e:
            logger.error(f"🔍 === N8N HEADER MAPPING DEBUG END (ERROR) ===")
            logger.error(f"🔍 Header mapping failed: {e}")
            import traceback

            logger.error(f"🔍 Full traceback: {traceback.format_exc()}")
            raise

    def validate_webhook_url(self) -> bool:
        """
        Validate that the n8n webhook URL is accessible

        Returns:
            True if webhook is accessible, False otherwise
        """
        try:
            import requests

            # Send a simple test payload
            test_payload = {
                "test": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": "Testing n8n webhook connectivity",
            }

            response = requests.post(
                self.webhook_url,
                json=test_payload,
                timeout=10,
                headers={"Content-Type": "application/json"},
            )

            return response.status_code == 200

        except Exception as e:
            logger.error(f"Webhook validation failed: {e}")
            return False
