-- Study-notes tables for the Generated_Notes booklets.
--
-- notes_chapter  — one row per chapter (book, number, title, prerequisites)
-- notes_topic    — one row per topic, carrying the booklet's prose sections
-- notes_formula  — the 📐 formula cards attached to a topic
-- notes_derivation — the 🧮 derivation cards attached to a topic
--
-- Source: exports/notes/all_notes_flat.json, produced by
--   python tools/export/notes_to_json.py
--
-- Kept separate from the qa_* tables on purpose: notes are authored study
-- material with their own structure, while qa_theory_chapter holds extracted
-- textbook theory. Merging them would force one of the two into the other's
-- shape and lose fields.
--
-- Run: mysql -u user -p foundation < schema/notes_tables.sql

CREATE TABLE IF NOT EXISTS notes_chapter (
  chapter_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  book_slug VARCHAR(255) NOT NULL,
  book_title VARCHAR(512) NOT NULL DEFAULT '',
  class VARCHAR(8) NOT NULL DEFAULT '',
  subject VARCHAR(64) NOT NULL DEFAULT '',
  chapter_number INT NOT NULL,
  chapter_name VARCHAR(512) NOT NULL,
  -- JSON array of strings; MySQL 5.7+ validates it as JSON.
  prerequisites JSON DEFAULT NULL,
  source VARCHAR(16) NOT NULL DEFAULT 'spec',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (chapter_id),
  UNIQUE KEY uq_notes_book_chapter (book_slug, chapter_number),
  KEY idx_notes_class_subject (class, subject)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS notes_topic (
  topic_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  chapter_id BIGINT UNSIGNED NOT NULL,
  -- Stable business key from the export, e.g. "Class9_Physics-c01-t03".
  note_id VARCHAR(128) NOT NULL,
  topic_order INT NOT NULL DEFAULT 1,
  topic_number VARCHAR(16) NOT NULL DEFAULT '',
  topic VARCHAR(512) NOT NULL,
  estimated_time VARCHAR(32) NOT NULL DEFAULT '',
  difficulty VARCHAR(16) NOT NULL DEFAULT '',
  importance TINYINT UNSIGNED DEFAULT NULL,
  quick_summary LONGTEXT,
  real_life LONGTEXT,
  definition LONGTEXT,
  key_idea LONGTEXT,
  working_principle LONGTEXT,
  memory_hook LONGTEXT,
  advanced LONGTEXT,
  -- JSON arrays of strings.
  applications JSON DEFAULT NULL,
  points JSON DEFAULT NULL,
  mistakes JSON DEFAULT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (topic_id),
  UNIQUE KEY uq_notes_note_id (note_id),
  UNIQUE KEY uq_notes_chapter_order (chapter_id, topic_order),
  CONSTRAINT fk_notes_topic_chapter
    FOREIGN KEY (chapter_id) REFERENCES notes_chapter (chapter_id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS notes_formula (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  topic_id BIGINT UNSIGNED NOT NULL,
  card_order INT NOT NULL DEFAULT 1,
  name VARCHAR(512) NOT NULL DEFAULT '',
  difficulty VARCHAR(32) NOT NULL DEFAULT '',
  formula LONGTEXT,
  variables LONGTEXT,
  when_to_use LONGTEXT,
  common_mistakes LONGTEXT,
  shortcut LONGTEXT,
  PRIMARY KEY (id),
  UNIQUE KEY uq_notes_formula_order (topic_id, card_order),
  CONSTRAINT fk_notes_formula_topic
    FOREIGN KEY (topic_id) REFERENCES notes_topic (topic_id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS notes_derivation (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  topic_id BIGINT UNSIGNED NOT NULL,
  card_order INT NOT NULL DEFAULT 1,
  title VARCHAR(512) NOT NULL DEFAULT '',
  why LONGTEXT,
  -- JSON arrays of strings.
  assumptions JSON DEFAULT NULL,
  steps JSON DEFAULT NULL,
  result LONGTEXT,
  exam_perspective LONGTEXT,
  PRIMARY KEY (id),
  UNIQUE KEY uq_notes_derivation_order (topic_id, card_order),
  CONSTRAINT fk_notes_derivation_topic
    FOREIGN KEY (topic_id) REFERENCES notes_topic (topic_id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
