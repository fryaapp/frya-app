-- Migration 0013: UNIQUE constraint on case_references
-- Ensures (case_id, reference_type, reference_value) is unique per case.
-- Duplicate references created before this migration are deduplicated by
-- keeping the earliest (lowest created_at) entry.

-- Step 1: Remove true duplicates, keeping the oldest entry per group
DELETE FROM case_references cr
WHERE id NOT IN (
    SELECT DISTINCT ON (case_id, reference_type, reference_value) id
    FROM case_references
    ORDER BY case_id, reference_type, reference_value, created_at ASC
);

-- Step 2: Add the unique constraint
ALTER TABLE case_references
    ADD CONSTRAINT case_references_unique
    UNIQUE (case_id, reference_type, reference_value);
