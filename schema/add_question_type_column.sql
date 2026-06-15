-- Add question_type to existing qa_content_row (safe to re-run).
--   mysql -u root -p foundation < schema/add_question_type_column.sql

ALTER TABLE qa_content_row
  ADD COLUMN question_type VARCHAR(64) NOT NULL DEFAULT 'Exercise Question'
  AFTER answer;

CREATE INDEX idx_question_type ON qa_content_row (question_type);
