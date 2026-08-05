-- Phase 1 MVP: question tagging required by the PRD developer note
-- ("Question banks must be tagged by class, subject, chapter, topic, subtopic,
-- difficulty, cognitive level and learning objective").
--
-- class / subject are derived from book_slug (see storage/database.derive_attributes)
-- and chapter / topic already exist, so this migration adds the four missing
-- attributes.  Safe to re-run: each ALTER is guarded by an information_schema
-- check so a second run is a no-op rather than an error.
--
--   mysql -u root -p foundation < schema/add_question_tagging_columns.sql

-- --------------------------------------------------------------------------
-- Columns
-- --------------------------------------------------------------------------
SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    "ALTER TABLE qa_content_row ADD COLUMN difficulty VARCHAR(16) NOT NULL DEFAULT 'Moderate' AFTER question_type",
    "SELECT 'difficulty already present'")
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'qa_content_row' AND COLUMN_NAME = 'difficulty'
);
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    "ALTER TABLE qa_content_row ADD COLUMN subtopic VARCHAR(255) NOT NULL DEFAULT '' AFTER difficulty",
    "SELECT 'subtopic already present'")
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'qa_content_row' AND COLUMN_NAME = 'subtopic'
);
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    "ALTER TABLE qa_content_row ADD COLUMN cognitive_level VARCHAR(32) NOT NULL DEFAULT '' AFTER subtopic",
    "SELECT 'cognitive_level already present'")
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'qa_content_row' AND COLUMN_NAME = 'cognitive_level'
);
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    "ALTER TABLE qa_content_row ADD COLUMN learning_objective VARCHAR(512) NOT NULL DEFAULT '' AFTER cognitive_level",
    "SELECT 'learning_objective already present'")
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'qa_content_row' AND COLUMN_NAME = 'learning_objective'
);
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

-- --------------------------------------------------------------------------
-- Indexes — the Practice Engine filters on (chapter_id, difficulty) and
-- reports group by cognitive_level.
-- --------------------------------------------------------------------------
SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    "CREATE INDEX idx_difficulty ON qa_content_row (difficulty)",
    "SELECT 'idx_difficulty already present'")
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'qa_content_row' AND INDEX_NAME = 'idx_difficulty'
);
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    "CREATE INDEX idx_cognitive_level ON qa_content_row (cognitive_level)",
    "SELECT 'idx_cognitive_level already present'")
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'qa_content_row' AND INDEX_NAME = 'idx_cognitive_level'
);
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;

SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    "CREATE INDEX idx_chapter_difficulty ON qa_content_row (chapter_id, difficulty)",
    "SELECT 'idx_chapter_difficulty already present'")
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'qa_content_row' AND INDEX_NAME = 'idx_chapter_difficulty'
);
PREPARE s FROM @ddl; EXECUTE s; DEALLOCATE PREPARE s;
