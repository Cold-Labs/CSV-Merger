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

## Instructions for Future Changes

Every time you modify code:
1. Add entry to this changelog BEFORE making changes
2. Include all required fields (see format above)
3. Be specific about what files and lines are affected
4. Note any potential impacts or risks
5. Mark as complete once change is applied and tested

