-- =====================================================================
-- P-A1.1  Schema Foundation — CHECKS  (read-only; run by section)
-- Sections: PRE-FLIGHT (before forward) | POST-FORWARD | POST-ROLLBACK.
-- These statements are SELECT/SHOW only — they change nothing.
-- =====================================================================

-- ---------------------------------------------------------------------
-- SECTION A — PRE-FLIGHT  (run BEFORE applying .up.sql)
-- ---------------------------------------------------------------------

-- A1. Server version — FLAG: need >= 8.0.12 for ALGORITHM=INSTANT column adds.
SELECT VERSION() AS mysql_version;

-- A2. Confirm we are on the intended database.
SELECT DATABASE() AS current_db;

-- A3. Snapshot the table definition — must match schema/qa_theory_and_rows.sql.
SHOW CREATE TABLE qa_content_row;

-- A4. Baseline row count (record this number; POST checks compare against it).
SELECT COUNT(*) AS qa_content_row_baseline FROM qa_content_row;

-- A5. Confirm NONE of the P-A1.1 objects already exist (expect 0 rows each).
SELECT column_name FROM information_schema.columns
 WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
   AND column_name IN ('question_uid','revision','content_hash');
SELECT index_name FROM information_schema.statistics
 WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
   AND index_name = 'idx_question_uid';
SELECT table_name FROM information_schema.tables
 WHERE table_schema = DATABASE() AND table_name = 'question_identity';

-- A6. Confirm existing structures we must NOT disturb are present.
--     Expect: PRIMARY, idx_chapter, idx_book  (idx_question_type may or may not exist).
SELECT index_name, column_name, seq_in_index
  FROM information_schema.statistics
 WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
 ORDER BY index_name, seq_in_index;
--     Expect the CASCADE foreign key fk_content_chapter.
SELECT constraint_name, delete_rule, update_rule
  FROM information_schema.referential_constraints
 WHERE constraint_schema = DATABASE() AND table_name = 'qa_content_row';


-- ---------------------------------------------------------------------
-- SECTION B — POST-FORWARD VALIDATION  (run AFTER .up.sql)
-- ---------------------------------------------------------------------

-- B1. New columns exist with correct nullability / default.
--     Expect: question_uid CHAR(26) NULLABLE null-default;
--             revision INT NOT NULL default '1';
--             content_hash CHAR(64) NULLABLE null-default.
SELECT column_name, column_type, is_nullable, column_default
  FROM information_schema.columns
 WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
   AND column_name IN ('question_uid','revision','content_hash')
 ORDER BY column_name;

-- B2. Lookup index exists and is NON-UNIQUE (NON_UNIQUE = 1).
SELECT index_name, non_unique, column_name
  FROM information_schema.statistics
 WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
   AND index_name = 'idx_question_uid';

-- B3. Registry table exists, empty, correct shape.
SELECT COUNT(*) AS question_identity_rowcount FROM question_identity;   -- expect 0
SELECT column_name, column_type, is_nullable, column_default
  FROM information_schema.columns
 WHERE table_schema = DATABASE() AND table_name = 'question_identity'
 ORDER BY ordinal_position;
SELECT index_name, non_unique, column_name, seq_in_index
  FROM information_schema.statistics
 WHERE table_schema = DATABASE() AND table_name = 'question_identity'
 ORDER BY index_name, seq_in_index;

-- B4. Data is untouched: row count unchanged; new columns hold only NULL / default 1.
SELECT COUNT(*) AS qa_content_row_after FROM qa_content_row;             -- == A4 baseline
SELECT
  SUM(question_uid IS NULL)  AS uid_nulls,                               -- == total
  SUM(content_hash IS NULL)  AS hash_nulls,                              -- == total
  SUM(revision = 1)          AS revision_is_default,                     -- == total
  COUNT(*)                   AS total
FROM qa_content_row;

-- B5. Existing structures intact (diff against A3 snapshot — additive only).
SHOW CREATE TABLE qa_content_row;


-- ---------------------------------------------------------------------
-- SECTION C — POST-ROLLBACK VALIDATION  (run AFTER .down.sql)
-- ---------------------------------------------------------------------

-- C1. New columns are gone (expect 0 rows).
SELECT column_name FROM information_schema.columns
 WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
   AND column_name IN ('question_uid','revision','content_hash');

-- C2. Lookup index is gone (expect 0 rows).
SELECT index_name FROM information_schema.statistics
 WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
   AND index_name = 'idx_question_uid';

-- C3. Registry table is gone (expect 0 rows).
SELECT table_name FROM information_schema.tables
 WHERE table_schema = DATABASE() AND table_name = 'question_identity';

-- C4. Row count unchanged; definition matches the pre-migration snapshot (A3).
SELECT COUNT(*) AS qa_content_row_after_rollback FROM qa_content_row;    -- == A4 baseline
SHOW CREATE TABLE qa_content_row;

-- End of CHECKS.
