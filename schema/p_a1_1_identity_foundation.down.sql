-- =====================================================================
-- P-A1.1  Schema Foundation — ROLLBACK migration   (reverse of .up, idempotent)
--
-- Drops ONLY the objects P-A1.1 created.  No existing column, row, primary key,
-- foreign key, or index of the original schema is touched.  The dropped columns
-- in P-A1.1 hold only NULL / default(1) values, so there is no data loss.
--
-- ORDER (must be reverse of forward): drop index -> drop columns -> drop table.
--   (The index references question_uid, so it is dropped before the column.)
--
-- RUN (mysql CLI):
--   mysql -u <user> -p <database> < schema/p_a1_1_identity_foundation.down.sql
-- =====================================================================

DELIMITER $$
DROP PROCEDURE IF EXISTS __p_a1_1_down $$
CREATE PROCEDURE __p_a1_1_down()
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.statistics
      WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
        AND index_name = 'idx_question_uid') THEN
    ALTER TABLE qa_content_row DROP INDEX idx_question_uid;
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.columns
      WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
        AND column_name = 'content_hash') THEN
    ALTER TABLE qa_content_row DROP COLUMN content_hash;
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.columns
      WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
        AND column_name = 'revision') THEN
    ALTER TABLE qa_content_row DROP COLUMN revision;
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.columns
      WHERE table_schema = DATABASE() AND table_name = 'qa_content_row'
        AND column_name = 'question_uid') THEN
    ALTER TABLE qa_content_row DROP COLUMN question_uid;
  END IF;
END $$
DELIMITER ;

CALL __p_a1_1_down();
DROP PROCEDURE IF EXISTS __p_a1_1_down;

-- Registry is empty in P-A1.1 (no backfill yet), so dropping it loses no data.
DROP TABLE IF EXISTS question_identity;

-- End of ROLLBACK migration.
