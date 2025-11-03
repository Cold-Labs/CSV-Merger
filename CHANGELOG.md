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

**Example Payload Structure:**
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

## Instructions for Future Changes

Every time you modify code:
1. Add entry to this changelog BEFORE making changes
2. Include all required fields (see format above)
3. Be specific about what files and lines are affected
4. Note any potential impacts or risks
5. Mark as complete once change is applied and tested

