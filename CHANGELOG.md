# CSV Merger - Change Log

This file tracks all code changes made to the project. Every modification must be logged here.

---

## [Date: 2025-11-03 - Initial Setup]

### Created: CHANGELOG.md
**Type:** Documentation
**Description:** Created changelog system to track all code modifications
**Reason:** Implement proper change management to prevent accidental breaking changes
**Impact:** Project-wide documentation practice
**Risk Level:** Low

### Updated: .cursor/rules/my-custom-rules.mdc
**Type:** Documentation
**Description:** Added mandatory changelog requirement to cursor rules
**Reason:** Enforce change tracking discipline for all future modifications
**Impact:** All future code changes must be logged
**Risk Level:** Low

---

## [Date: 2025-11-05 - Bug #10] Multi-Email Detection and Record Duplication for Company Records

### Changed: simple_worker.py (lines 299-373, 523-532)
**Type:** Feature Enhancement / Bug Fix
**Description:** Detect multiple emails in single cells for company records and duplicate the entire record for each email
**Reason:** Lead platforms (Store Leads, etc.) often export company data with multiple contact emails in one field (e.g., "info@example.com:support@example.com"). Each email should be sent as a separate webhook to Clay.
**Solution:** 
- Added "Company Email" to company_fields set (line 532) - proper naming for company contact emails
- Created `_expand_multi_email_records()` method to detect and split multi-email records
- Method detects delimiters (`:`, `,`, `;`, `|`) in email fields
- Duplicates entire company record for each email found
- Each duplicate gets the email in BOTH "Company Email" (standardized) AND the original field name (preserved in additional_fields)
- Only applies to company table_type, not people (person records have clean separate email columns)

**Impact:**
  - Affects: Company webhook sending logic
  - Company records with multiple emails will now generate multiple webhooks (one per email)
  - People records are NOT affected (no changes to person processing)
  - All other company data remains identical across duplicates
  - Email fields now included in company_fields for proper webhook structure
**Risk Level:** Low-Medium (changes record count sent to webhooks, but improves data quality)
**Status:** ✅ APPLIED

**Logic Details:**
```python
# Example input CSV row:
{
  "Company Name": "Steeped Coffee",
  "Company Domain": "steepedcoffee.com",
  "emails": "info@steepedcoffee.com:support@steepedcoffee.com",
  "Company Industry": "Food & Drink"
}

# Output: 2 separate webhooks sent to Clay
# Webhook 1:
{
  "Company Name": "Steeped Coffee",
  "Company Domain": "steepedcoffee.com",
  "Company Email": "info@steepedcoffee.com",  // Standardized field
  "Company Industry": "Food & Drink",
  "additional_fields": {
    "emails": "info@steepedcoffee.com"  // Original field preserved with single email
  }
}

# Webhook 2:
{
  "Company Name": "Steeped Coffee",
  "Company Domain": "steepedcoffee.com",
  "Company Email": "support@steepedcoffee.com",  // Standardized field
  "Company Industry": "Food & Drink",
  "additional_fields": {
    "emails": "support@steepedcoffee.com"  // Original field preserved with single email
  }
}
```

**Supported Delimiters:** `:` (colon), `,` (comma), `;` (semicolon), `|` (pipe), whitespace
**Email Validation:** Basic check for `@` symbol presence

---

## [Date: 2025-11-03 - Bug Fix #1] Job Title Date Conversion Issue

### Changed: src/phase1_merger.py (line 69)
**File:** src/phase1_merger.py (line 69)
**Type:** Bug Fix
**Description:** Prevent pandas from auto-converting text fields (like Job Title) to date format
**Solution:** Add `parse_dates=False` parameter to pd.read_csv()
**Reason:** User reported that "Job Title" field is being sent as date format to Clay, causing issues
**Impact:** 
  - Affects: CSV reading in Phase 1 merge
  - All text fields will stay as text (Job Title, names, descriptions)
  - Numeric fields will stay as numbers (employee_count, prices)
  - Date strings will stay as strings (can be parsed later if needed)
**Risk Level:** Low (improves data integrity)
**Status:** ✅ APPLIED

---

## [Date: 2025-11-03 - Bug Fix #2] Missing Fields in Clay Webhooks

### Changed: simple_worker.py (lines 362-414)
**File:** simple_worker.py (lines 362-414)
**Type:** Bug Fix
**Description:** Include ALL fields from source CSV in webhook payload, not just predefined standard fields
**Solution:** Add "additional_fields" object containing all unmapped fields from original CSV
**Reason:** Store Leads CSV has 80+ fields but only ~10 are being sent to Clay. Fields like average_product_price, technologies, social media URLs are being dropped.
**Impact:**
  - Affects: Webhook payload structure sent to Clay
  - Payload will include both standardized fields AND all original fields
  - Does NOT affect n8n webhooks (only Clay webhooks)
**Risk Level:** Low-Medium (changes webhook payload structure, but additive only)
**Status:** ✅ APPLIED

**Changes Made:**
- Added "additional_fields" object to webhook payload
- Contains ALL fields from source CSV that aren't in the standard field mappings
- Includes total count in _metadata for debugging
- Empty/null values are excluded from additional_fields
- Only affects Clay webhooks (not n8n webhooks)

**Example Payload Structure (Previous - Bug #2-3):**
```json
{
  "person": { ... standard person fields ... },
  "company": { ... standard company fields ... },
  "additional_fields": {
    "average_product_price": "USD $37.28",
    "technologies": "Shopify:Klaviyo:...",
    "instagram_url": "https://instagram.com/...",
    "tiktok_followers": "1600000",
    ... all other unmapped fields ...
  },
  "_metadata": {
    "record_number": 1,
    "timestamp": 1234567890,
    "source": "CSV Merger",
    "total_additional_fields": 60
  }
}
```

---

## [Date: 2025-11-03 - Bug Fix #3] Unmapped Columns Being Dropped in Phase 2

### Changed: src/phase2_standardizer.py (lines 164-218)
**Type:** Bug Fix
**Description:** Preserve ALL unmapped columns from source CSV during Phase 2 standardization
**Reason:** Phase 2 was creating a new DataFrame with ONLY standard headers, dropping all columns that don't map (like average_product_price, technologies, social URLs). This is why additional_fields was empty - those columns were gone before reaching the webhook sender.
**Solution:** After mapping standard headers, add all unmapped columns from the original merged_df to the standardized_df
**Impact:**
  - Affects: Phase 2 standardization output
  - All unmapped columns now preserved in final CSV
  - Webhook sender can now access all original fields in additional_fields
  - Does NOT affect standard field mapping logic
**Risk Level:** Low (additive only, doesn't change existing mapping behavior)
**Status:** ✅ APPLIED

**Implementation Details:**
- After standard header mapping, collect all original columns that were used in mappings
- Find columns that weren't mapped to any standard header
- Preserve these unmapped columns in the standardized DataFrame
- Log count of preserved columns for debugging
- Now Store Leads fields like average_product_price, technologies, social URLs will flow through to webhooks

**Before:** standardized_df had ONLY standard headers (9-17 columns)
**After:** standardized_df has standard headers + ALL unmapped columns (80+ columns for Store Leads)

---

## [Date: 2025-11-03 - Bug Fix #4] LinkedIn URL Not Mapping to Company LinkedIn

### Changed: config/field_mappings.json (lines 8, 27)
**Type:** Bug Fix
**Description:** Add underscore variations for LinkedIn field mappings
**Reason:** Store Leads CSV uses `linkedin_url` and `linkedin_account` (with underscores), but field mappings only had "linkedin url" (with space). This caused LinkedIn URLs to not map to the "Company LinkedIn" standard field and they were ending up empty/null.
**Solution:** Added variations with underscores to both company_mappings and people_mappings
**Impact:**
  - Affects: Field mapping for LinkedIn columns
  - Now recognizes: "linkedin_url", "linkedin url", "linkedin_account", "linkedin account"
  - Store Leads LinkedIn URLs will now map to "Company LinkedIn" standard field
  - Applies to both company and people table types
**Risk Level:** Low (additive mapping rules only)
**Status:** ✅ APPLIED

**Added Mappings:**
- Company LinkedIn: `linkedin_url`, `linkedin_account`, `linkedin account`
- LinkedIn Profile: `linkedin_profile`, `linkedin_url`, `li_url`, `li_profile`
- Work Email: `work_email`, `business_email`, `company_email`, `corporate_email`
- Personal Email: `personal_email`, `private_email`, `home_email`, `email_personal`
- Phone Number: `contact_number`, `phone_number`
- Company Employee Count: `employee_count`, `staff_size`, `team_size`, `company_size`

**Why This Matters:**
CSV providers often use underscores instead of spaces in column names (e.g., `linkedin_url` vs "linkedin url"). Adding both variations ensures robust field mapping regardless of the CSV format.

---

## [Date: 2025-11-03 - Bug Fix #5] Unhashable Type Error in Phase 2

### Changed: src/phase2_standardizer.py (lines 209-238)
**Type:** Bug Fix - Critical
**Description:** Fix "unhashable type: 'list'" error when collecting mapped columns
**Reason:** The code was trying to add lists to a set, which isn't allowed in Python. The mapping_data structure can contain lists or strings in secondary/tertiary fields, and we need to handle both cases.
**Solution:** Add type checking to safely handle both strings and lists when collecting mapped columns
**Impact:**
  - Affects: Phase 2 unmapped column preservation logic
  - Fixes crash during CSV processing
  - Now properly handles mapping data regardless of whether values are strings or lists
**Risk Level:** Low (defensive type checking)
**Status:** ✅ APPLIED

---

## [Date: 2025-11-03 - Bug Fix #6] LinkedIn Fields Filtered Out Before AI Mapping

### Changed: src/header_mapper.py (lines 139-145)
**Type:** Bug Fix - Critical
**Description:** Prevent LinkedIn and social media fields from being filtered out when empty
**Reason:** The header mapper filters out columns with empty values UNLESS they're in the "important_fields" list. LinkedIn, Twitter, Instagram, etc. weren't in this list, so if the first sample row had empty social media fields, they'd be completely filtered out before n8n AI mapping, making it impossible to map them even when we added them to field_mappings.json
**Solution:** Add social media field terms ('linkedin', 'twitter', 'facebook', 'instagram', 'youtube', 'tiktok') to the important_fields whitelist
**Impact:**
  - Affects: Sample data sent to n8n for AI mapping
  - Social media fields now preserved even if empty in sample row
  - n8n AI can now see and map linkedin_url → Company LinkedIn
  - Ensures ALL important fields are visible to AI mapper
**Risk Level:** Low (additive whitelist entry)
**Status:** ✅ APPLIED

**Root Cause Chain:**
1. Store Leads CSV row 1 has empty `linkedin_url`
2. Header mapper filters it out (not in important_fields)
3. n8n never sees the field, can't create mapping
4. Field ends up in additional_fields instead of Company LinkedIn

**Now:** LinkedIn fields preserved → n8n sees them → maps to Company LinkedIn ✅

---

## [Date: 2025-11-03 - Bug Fix #7] LinkedIn Data Scattered Across Multiple Fields

### Changed: src/phase2_standardizer.py (lines 261-473)
**Type:** Bug Fix - CRITICAL
**Description:** Add field consolidation to merge variant field names created by inconsistent AI mapping
**Reason:** n8n AI was creating different field names for the same data (e.g., "LinkedIn Profile", "Linkedin Url", "Company LinkedIn Url", "LinkedIn Username") causing LinkedIn data to scatter across multiple columns in Clay instead of being in ONE consistent field
**Solution:** Added `_consolidate_variant_fields()` method that runs after AI mapping to merge all variant names into the correct standard field
**Impact:**
  - Affects: Final standardized DataFrame before webhook sending
  - Merges all LinkedIn variants → "Company LinkedIn" (for companies)
  - Merges all LinkedIn variants → "LinkedIn Profile" (for people)
  - Also consolidates: Company Name, Company Domain, Employee Count variants
  - Removes duplicate variant columns after merging data
**Risk Level:** Medium (changes field structure, but only consolidates, doesn't lose data)
**Status:** ✅ APPLIED

**Consolidation Rules:**
- **Company LinkedIn**: Merges "LinkedIn Profile", "Linkedin Url", "Company LinkedIn Url", "LinkedIn Username", "linkedin_url", "linkedin_account", etc.
- **Company Domain**: Merges "Domain", "Website", "domain_url", "Final Domain"
- **Company Name**: Merges "merchant_name", "Merchant Name", "Name"
- **Company Employee Count**: Merges "employee_count", "Employees", "Staff Size"

**Before:** LinkedIn data scattered across 5+ different fields in Clay
**After:** ALL LinkedIn data in ONE consistent "Company LinkedIn" field ✅

---

## [Date: 2025-11-04 - Bug Fix #8] Case-Sensitive Field Consolidation Failing

### Changed: src/phase2_standardizer.py (lines 579-593, 520-576)
**Type:** Bug Fix - CRITICAL
**Description:** Make field consolidation case-insensitive to catch AI-created variants with different casing
**Reason:** n8n AI was creating fields like "Linkedin profile" (lowercase 'p') instead of "LinkedIn Profile" (uppercase 'P'). The consolidation was case-sensitive, so it didn't match → data stayed in separate column → ended up in additional_fields instead of main person/company object → LinkedIn Profile field stayed NULL
**Solution:** 
- Made variant matching case-insensitive
- Added more lowercase variants to catch: "linkedin profile", "company linkedin url", "Linkedin profile"
- Added "company Linked In Handle" (which AI incorrectly maps to Company Name!)
**Impact:**
  - Affects: Field consolidation logic
  - Now catches ALL casing variations: "LinkedIn", "Linkedin", "linkedin", "LINKEDIN"
  - Fixes empty main fields with data stuck in additional_fields
  - Fixes "Linked In" (two words with space)
**Risk Level:** Low (more robust matching)
**Status:** ✅ APPLIED

**Example of what was broken:**
```json
{
  "person": {
    "LinkedIn Profile": null  ❌ Empty!
  },
  "additional_fields": {
    "Linkedin profile": "https://linkedin.com/in/..."  ❌ Data here!
  }
}
```

**Now fixed:**
```json
{
  "person": {
    "LinkedIn Profile": "https://linkedin.com/in/..."  ✅
  },
  "additional_fields": {}  ✅
}
```

**HOTFIX:** Added duplicate prevention - variant list had ["LinkedIn Profile", "Linkedin profile", "linkedin profile"] which all matched same column, causing KeyError when trying to drop it 3 times. Now checks for duplicates and verifies column exists before dropping.

---

## [Date: 2025-11-04 - Bug #9] Standard Fields NULL, Data in additional_fields - TYPE MISMATCH

### Changed: src/phase2_standardizer.py (lines 264-280)
**Type:** Bug Fix - CATASTROPHIC
**Description:** Fix type mismatch causing ALL mapped source columns to be incorrectly preserved as unmapped
**Reason:** 
- `_extract_all_mappings` creates: `{"primary": ["first_name"]}` (LIST)
- Unmapped detection checked: `isinstance(primary, str)` ❌ ALWAYS FALSE!
- Result: Source columns NEVER added to `mapped_original_columns`
- ALL mapped columns preserved as "unmapped"
- Standard fields exist but NULL
- Data stuck in additional_fields

**Solution:** Loop through priority lists correctly to extract source column names

**Impact:**
- Affects: Unmapped column preservation
- FIXES: First Name, Last Name, Full Name, Job Title all showing NULL
- FIXES: Data appearing in additional_fields instead of main objects
- FIXES: Duplicate columns (standard + source both present)
**Risk Level:** HIGH (was breaking ALL field mappings)
**Status:** ✅ APPLIED

**The Disaster:**
```json
{
  "person": {
    "First Name": null,  ❌
    "Last Name": null,   ❌
    "Job Title": null    ❌
  },
  "additional_fields": {
    "first_name": "Abigail",      ❌ Should be in First Name!
    "last_name": "Swanson",       ❌ Should be in Last Name!
    "current_title": "Marketing Director"  ❌ Should be in Job Title!
  }
}
```

**Now Fixed:**
```json
{
  "person": {
    "First Name": "Abigail",  ✅
    "Last Name": "Swanson",   ✅
    "Job Title": "Marketing Director"  ✅
  },
  "additional_fields": {}  ✅ Only truly unmapped stuff
}
```

---

## Instructions for Future Changes

Every time you modify code:
1. Add entry to this changelog BEFORE making changes
2. Include all required fields (see format above)
3. Be specific about what files and lines are affected
4. Note any potential impacts or risks
5. Mark as complete once change is applied and tested

