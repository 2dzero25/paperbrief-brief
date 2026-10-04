-- Initial schema from the spec's Data section. Later changes go in new numbered files and only add.
CREATE TABLE papers (
    arxiv_id         TEXT PRIMARY KEY,
    published_day    TEXT NOT NULL,              -- 발표일, YYYY-MM-DD
    title            TEXT NOT NULL,
    abstract         TEXT NOT NULL DEFAULT '',
    organization     TEXT NOT NULL DEFAULT '',
    upvotes          INTEGER NOT NULL DEFAULT 0,
    ai_summary       TEXT NOT NULL DEFAULT '',   -- EN 한 줄 요약 from HF
    summary_ko       TEXT NOT NULL DEFAULT '',   -- KO 한 줄 요약
    primary_category TEXT NOT NULL DEFAULT '',
    categories       TEXT NOT NULL DEFAULT '[]', -- JSON array
    code_url         TEXT NOT NULL DEFAULT ''    -- 등록 코드
);
CREATE INDEX papers_day ON papers (published_day);

CREATE TABLE reports (
    arxiv_id         TEXT PRIMARY KEY REFERENCES papers (arxiv_id),
    status           TEXT NOT NULL,              -- 대기 | 진행 중 | 완료 | 실패
    stage            TEXT NOT NULL DEFAULT '',   -- PDF | 파싱 | 작성 (current or failed)
    stage_started_at TEXT NOT NULL DEFAULT '',
    error_log        TEXT NOT NULL DEFAULT '',
    report_json      TEXT NOT NULL DEFAULT '',   -- whole Report as JSON (ADR-0001)
    created_at       TEXT NOT NULL DEFAULT '',
    updated_at       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE questions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    arxiv_id  TEXT NOT NULL REFERENCES papers (arxiv_id),
    question  TEXT NOT NULL,
    answer    TEXT NOT NULL,
    asked_at  TEXT NOT NULL
);
CREATE INDEX questions_paper ON questions (arxiv_id);
