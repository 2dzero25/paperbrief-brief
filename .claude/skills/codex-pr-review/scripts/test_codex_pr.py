"""Offline checks for codex_pr.py parsing. Run: python .claude/skills/codex-pr-review/scripts/test_codex_pr.py"""
import unittest

import codex_pr
from codex_pr import EPOCH, changed_ranges, classify, finding, pages

BOT = {"login": "chatgpt-codex-connector[bot]"}
P1 = ('**<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>  '
      'Keep existing rows on schema change**\n\nThe migration drops `papers`.\n\nUseful? React with 👍 / 👎.')
P2 = '**<sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>  Rename var**\n\nx'


def st(**kw):
    base = {"processed": [], "since": EPOCH, "rounds": 0, "fix": None, "retried": False}
    base.update(kw)
    return base


def review(i, at="2026-10-04T10:00:00Z", user=BOT):
    return {"id": i, "user": user, "state": "COMMENTED", "submitted_at": at, "body": "### 💡 Codex Review"}


def comment(rid, body, path="app/db.py", line=12, original_line=None):
    return {"id": rid * 10, "user": BOT, "pull_request_review_id": rid, "body": body,
            "path": path, "line": line, "original_line": original_line}


class Parse(unittest.TestCase):
    def test_paginate_pages_concatenated(self):
        self.assertEqual(pages('[{"a":1}]\n[{"a":2},{"a":3}]'), [{"a": 1}, {"a": 2}, {"a": 3}])
        self.assertEqual(pages(""), [])

    def test_badge_title_and_null_line(self):
        f = finding(comment(1, P1, line=None, original_line=40))
        self.assertEqual((f["priority"], f["title"], f["line"]), ("P1", "Keep existing rows on schema change", 40))

    def test_findings_from_newest_unprocessed_review(self):
        out = classify([review(1, "2026-10-04T09:00:00Z"), review(2)],
                       [comment(1, P1), comment(2, P2)], [], st(processed=[1]), {})
        self.assertEqual((out["signal"], out["review_id"], out["counts"]["P2"]), ("findings", 2, 1))

    def test_spoofed_login_ignored(self):
        fake = {"login": "chatgpt-codex-connector-evil[bot]"}
        out = classify([review(1, user=fake)], [], [], st(), {})
        self.assertEqual(out["signal"], "none")

    def test_review_before_since_ignored(self):
        out = classify([review(1, "2026-10-04T09:00:00Z")], [comment(1, P1)], [],
                       st(since="2026-10-04T09:30:00Z"), {})
        self.assertEqual(out["signal"], "none")

    def test_issue_comment_signals_and_precedence(self):
        def ic(body, at="2026-10-04T10:00:00Z"):
            return {"user": BOT, "body": body, "created_at": at, "updated_at": at}
        clean = ic("Codex Review: Didn't find any major issues. Swish!")
        limit = ic("You have reached your Codex usage limits for code reviews. You can see ...")
        error = ic("Codex Review: Something went wrong. Try again later by commenting “@codex review”.")
        self.assertEqual(classify([], [], [clean], st(), {})["signal"], "clean")
        self.assertEqual(classify([], [], [clean, limit], st(), {})["signal"], "limit")
        self.assertEqual(classify([], [], [error], st(), {})["signal"], "error")
        old = ic("Codex Review: Didn't find any major issues.", "2026-10-04T08:00:00Z")
        self.assertEqual(classify([], [], [old], st(since="2026-10-04T09:00:00Z"), {})["signal"], "none")

    def test_churn_when_all_gated_findings_hit_last_fix(self):
        diff = "diff --git a/app/db.py b/app/db.py\n--- a/app/db.py\n+++ b/app/db.py\n@@ -10,2 +10,4 @@\n"
        ranges = changed_ranges(diff)
        self.assertEqual(ranges, {"app/db.py": [(10, 13)]})
        hit = classify([review(1)], [comment(1, P1, line=12)], [], st(), ranges)
        miss = classify([review(1)], [comment(1, P1, line=30)], [], st(), ranges)
        self.assertEqual((hit["churn"], miss["churn"]), (True, False))


class Wait(unittest.TestCase):
    def test_polls_until_signal_then_returns(self):
        seq = iter(["none", "none", "findings"])
        base = {"draft": False, "pr_state": "OPEN", "repo": "o/r"}
        orig = codex_pr.snapshot, codex_pr.start_forward
        codex_pr.snapshot = lambda pr: dict(base, signal=next(seq))
        codex_pr.start_forward = lambda r, wake: None  # extension missing: polling path
        try:
            self.assertEqual(codex_pr.wait(1, timeout=5, interval=0)["signal"], "findings")
        finally:
            codex_pr.snapshot, codex_pr.start_forward = orig

    def test_draft_returns_at_once(self):
        orig = codex_pr.snapshot
        codex_pr.snapshot = lambda pr: {"draft": True, "pr_state": "OPEN", "signal": "none"}
        try:
            self.assertTrue(codex_pr.wait(1, timeout=5, interval=0)["draft"])
        finally:
            codex_pr.snapshot = orig


if __name__ == "__main__":
    unittest.main()
