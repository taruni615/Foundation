-- Three-table layout for *_qa_table.json exports.
--
-- qa_chapter          — chapter header (one row per topic/chapter)
-- qa_theory_chapter   — theory section (topic_name / topic_explanation)
-- qa_content_row      — Q&A items
--
-- Run: mysql -u user -p foundation < schema/qa_theory_and_rows.sql

CREATE TABLE IF NOT EXISTS qa_chapter (
  chapter_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  book_slug VARCHAR(255) NOT NULL,
  chapter_number INT NOT NULL,
  chapter_name VARCHAR(512) NOT NULL,
  page_range VARCHAR(128) DEFAULT '',
  summary LONGTEXT,
  key_points LONGTEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (chapter_id),
  UNIQUE KEY uq_book_chapter (book_slug, chapter_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS qa_theory_chapter (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  chapter_id BIGINT UNSIGNED NOT NULL,
  topic_name VARCHAR(512) NOT NULL DEFAULT '',
  topic_explanation LONGTEXT,
  section_order INT NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_chapter_section (chapter_id, section_order),
  CONSTRAINT fk_theory_chapter
    FOREIGN KEY (chapter_id) REFERENCES qa_chapter (chapter_id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS qa_content_row (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  chapter_id BIGINT UNSIGNED NOT NULL,
  book_slug VARCHAR(255) NOT NULL,
  chapter_name VARCHAR(512) NOT NULL,
  question LONGTEXT NOT NULL,
  answer LONGTEXT,
  question_type VARCHAR(64) NOT NULL DEFAULT 'Exercise Question',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_chapter (chapter_id),
  KEY idx_book (book_slug),
  CONSTRAINT fk_content_chapter
    FOREIGN KEY (chapter_id) REFERENCES qa_chapter (chapter_id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Replace all data for one book (CASCADE removes theory + content):
-- DELETE FROM qa_chapter WHERE book_slug = '10TH BIOLOGY FOUNDATION';
