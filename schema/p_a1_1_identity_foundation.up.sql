-- =====================================================================
-- P-A1.1  Schema Foundation — FORWARD migration   (additive, idempotent)
-- Stable Question Identity: identity registry + identity columns.
--
-- SCOPE (this file ONLY):
--   * CREATE the durable identity registry table (empty).
--   * ADD nullable / defaulted identity columns to qa_content_row.
--   * ADD a non-unique lookup index on qa_content_row.question_uid.
--
-- EXPLICITLY NOT DONE HERE (later P-A1 sub-steps):
--   * No backfill / data migration.            (P-A1.2)
--   * No UNIQUE constraint, no NOT NULL promotion of question_uid.
--   * No foreign key from qa_content_row -> question_identity.
--   * No triggers, no API change, no ingestion change.
--
-- RUN (mysql CLI — uses DELIMITER + a transient stored procedure):
--   mysql -u <user> -p <database> < schema/p_a1_1_identity_foundation.up.sql
--
-- REVIEW NOTES:
--   * Assumes the target DB matches schema/qa_theory_and_rows.sql.
--     Confirm with schema/p_a1_1_identity_foundation.checks.sql (PRE-FLIGHT) first.
--   * Online DDL: the secondary index uses ALGORITHM=INPLACE, LOCK=NONE (MySQL 5.6+).
--     Column ADDs are intentionally portable (no explicit ALGORITHM). On MySQL 8.0.12+
--     a DBA may append ", ALGORITHM=INSTANT, LOCK=NONE" to each ADD COLUMN for a
--     guaranteed instant, non-blocking add.
--   * Idempotent: safe to re-run. If CREATE ROUTINE is not granted, use the plain
--     fallback (run each ALTER once; see DBA notes in the accompanying document).
-- =====================================================================

-- 1) Durable identity registry — created EMPTY.
--    NOT a child of qa_chapter, so the qa_chapter CASCADE delete can never touch it.
CREATE TABLE IF NOT EXISTS question_identity (
  question_uid    CHAR(26)     NOT NULL,                 -- ULID (opaque, never recycled)
  book_slug       VARCHAR(255) NOT NULL DEFAULT '',
  chapter_number  INT          NOT NULL DEFAULT 0,
  ordinal         INT          NOT NULL DEFAULT 0,       -- position within chapter (future matching)
  content_hash    CHAR(64)     NULL     DEFAULT NULL,    -- SHA-256 of normalized content
  first_seen_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  retired_at      TIMESTAMP    NULL     DEFAULT NULL,    -- tombstone (never reissued)
  PRIMARY KEY (question_uid),
  KEY idx_identity_book_chapter (book_slug, chapter_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2) Additive identity columns + lookup index on qa_content_row (idempotent guards).
DELIMITER $$
DROP PROCEDURE IF EXISTS __p_a1_1_up $$
CREATE PROCEDURE __p_a1_1_up()
BEGIN
  -- question_uid : nullable -> existing INSERTs that omit it succeed (NULL)
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
      WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
        AND column_name = 'question_uid') THEN
    ALTER TABLE qa_content_row ADD COLUMN question_uid CHAR(26) NULL DEFAULT NULL;
  END IF;

  -- revision : NOT NULL DEFAULT 1 -> existing rows + omitted INSERTs get 1
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
      WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
        AND column_name = 'revision') THEN
    ALTER TABLE qa_content_row ADD COLUMN revision INT NOT NULL DEFAULT 1;
  END IF;

  -- content_hash : nullable
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
      WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
        AND column_name = 'content_hash') THEN
    ALTER TABLE qa_content_row ADD COLUMN content_hash CHAR(64) NULL DEFAULT NULL;
  END IF;

  -- non-unique lookup index (UNIQUE is deferred to P-A1.2, after backfill)
  IF NOT EXISTS (SELECT 1 FROM information_schema.statistics
      WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
        AND index_name = 'idx_question_uid') THEN
    ALTER TABLE qa_content_row
      ADD INDEX idx_question_uid (question_uid), ALGORITHM=INPLACE, LOCK=NONE;
  END IF;
END $$
DELIMITER ;

CALL __p_a1_1_up();
DROP PROCEDURE IF EXISTS __p_a1_1_up;

-- End of FORWARD migration.
