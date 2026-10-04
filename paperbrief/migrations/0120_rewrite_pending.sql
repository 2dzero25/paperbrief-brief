-- 다시 작성 (#12): 1 while a rewrite is not finished. report_json keeps the previous report until it succeeds.
ALTER TABLE reports ADD COLUMN rewrite INTEGER NOT NULL DEFAULT 0;
