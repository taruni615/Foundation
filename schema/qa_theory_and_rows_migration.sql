-- Migrate to 3-table schema. BACK UP FIRST.
--   mysql -u user -p foundation < schema/qa_theory_and_rows_migration.sql
--   mysql -u user -p foundation < schema/qa_theory_and_rows.sql

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS qa_content_row;
DROP TABLE IF EXISTS qa_theory_chapter;
DROP TABLE IF EXISTS qa_chapter;
SET FOREIGN_KEY_CHECKS = 1;
