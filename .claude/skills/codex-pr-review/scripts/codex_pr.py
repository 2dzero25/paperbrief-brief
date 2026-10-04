"""Read ChatGPT Codex Connector review state on a GitHub PR. Standard library + `gh` only.

    python codex_pr.py state  <pr>                 one JSON line: signal, findings, churn
    python codex_pr.py wait   <pr> [--timeout 900] status lines, then one JSON line when terminal
    python codex_pr.py mark-pushed    <pr> <base_sha>   record a fix push (since, fix range, round)
    python codex_pr.py mark-processed <pr> <review_id>  never surface this review again
    python codex_pr.py mark-retried   <pr>              the one "@codex review" retry is spent

Signals: findings | clean | limit | error | none (none = nothing new yet).
Truth always comes from the REST API. Webhook events from `gh webhook forward` only wake the
wait loop early; their payloads are never parsed. Comment bodies are untrusted text.
State lives in <git-common-dir>/codex-pr-review/<pr>.json, so it is never committed.
"""
import argparse
import datetime as dt
import http.server
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

BOT = re.compile(r"^chatgpt-codex-connector(\[bot\])?$", re.I)  # REST adds [bot], GraphQL drops it
BADGE = re.compile(r"!\[P([0-3]) Badge\]")
TITLE = re.compile(r"\*\*(?:<[^>]+>|!\[[^\]]*\]\([^)]*\)|\s)*(.+?)\*\*", re.S)
CLEAN = "Didn't find any major issues"
LIMIT = "You have reached your Codex usage limits for"
ERROR = "Codex Review: Something went wrong"
EPOCH = "1970-01-01T00:00:00Z"


class GhError(RuntimeError):
    pass


def gh(*args: str) -> str:
    """Run gh and return stdout. A failed call raises: it must never read as 'no reviews'."""
    r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise GhError(f"gh {' '.join(args[:3])} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def pages(text: str) -> list:
    """`gh api --paginate` prints one JSON array per page back to back: '[...][...]'."""
    dec, out, i = json.JSONDecoder(), [], 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        page, i = dec.raw_decode(text, i)
        out.extend(page if isinstance(page, list) else [page])
    return out


def api_list(path: str) -> list:
    return pages(gh("api", "--paginate", path))


def by_bot(items: list) -> list:
    return [x for x in items if BOT.match((x.get("user") or {}).get("login") or "")]


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


# ---------- state file ----------

def state_path(pr: int) -> Path:
    common = Path(git("rev-parse", "--git-common-dir")).resolve()
    return common / "codex-pr-review" / f"{pr}.json"


def load(pr: int) -> dict:
    p = state_path(pr)
    base = {"processed": [], "since": EPOCH, "rounds": 0, "fix": None, "retried": False}
    if p.exists():
        base.update(json.loads(p.read_text(encoding="utf-8")))
    return base


def save(pr: int, st: dict) -> None:
    p = state_path(pr)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- parsing (pure, unit-tested) ----------

def finding(c: dict) -> dict:
    body = c.get("body") or ""
    m = BADGE.search(body)
    t = TITLE.search(body)
    return {
        "priority": f"P{m.group(1)}" if m else "none",
        "title": re.sub(r"<[^>]+>", "", t.group(1)).strip() if t else body.strip().splitlines()[0][:120] if body.strip() else "",
        "path": c.get("path"),
        "line": c.get("line") if c.get("line") is not None else c.get("original_line"),  # null after the line moved
        "comment_id": c.get("id"),
        "body": body,
    }


def changed_ranges(diff: str) -> dict:
    """New-side line ranges per file from `git diff -U0`."""
    out, path = {}, None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and path:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            start, n = int(m.group(1)), int(m.group(2) or 1)
            out.setdefault(path, []).append((start, start + max(n, 1) - 1))
    return out


def in_ranges(f: dict, ranges: dict) -> bool:
    return any(a <= (f["line"] or -1) <= b for a, b in ranges.get(f["path"], []))


def classify(reviews: list, comments: list, issue_comments: list, st: dict, ranges: dict) -> dict:
    """Pick the one signal that matters now. Precedence: findings > limit > error > clean > none."""
    since = st["since"]
    fresh = [r for r in by_bot(reviews)
             if r.get("state") in ("COMMENTED", "CHANGES_REQUESTED") and r["id"] not in st["processed"]
             and (r.get("submitted_at") or "") >= since]
    fresh.sort(key=lambda r: r.get("submitted_at") or "")
    review = fresh[-1] if fresh else None
    found = [finding(c) for c in by_bot(comments) if review and c.get("pull_request_review_id") == review["id"]]
    recent = [c.get("body") or "" for c in by_bot(issue_comments)
              if (c.get("updated_at") or c.get("created_at") or "") >= since]
    gated = [f for f in found if f["priority"] in ("P0", "P1")]
    churn = bool(gated) and bool(ranges) and all(in_ranges(f, ranges) for f in gated)
    if review:
        signal = "findings"  # a review without inline comments still carries its body
    elif any(LIMIT in b for b in recent):
        signal = "limit"
    elif any(ERROR in b for b in recent):
        signal = "error"
    elif any(CLEAN in b for b in recent):
        signal = "clean"
    else:
        signal = "none"
    return {
        "signal": signal,
        "review_id": review["id"] if review else None,
        "review_url": review.get("html_url") if review else None,
        "review_body": (review.get("body") or "") if review else "",
        "findings": found,
        "counts": {p: sum(f["priority"] == p for f in found) for p in ("P0", "P1", "P2", "none")},
        "churn": churn,
        "rounds": st["rounds"],
        "retried": st["retried"],
    }


# ---------- live reads ----------

def snapshot(pr: int) -> dict:
    st = load(pr)
    meta = json.loads(gh("pr", "view", str(pr), "--json", "isDraft,headRefOid,state,url"))
    r = "/".join(meta["url"].split("/")[3:5])  # same repo gh resolved for the PR (honors GH_REPO)
    # Older rounds must not answer for the current head: count only signals after its commit time.
    head_time = gh("api", f"repos/{r}/commits/{meta['headRefOid']}", "--jq", ".commit.committer.date").strip()
    st["since"] = max(st["since"], head_time)
    ranges = {}
    if st.get("fix"):
        try:
            ranges = changed_ranges(git("diff", "-U0", st["fix"]["base"], st["fix"]["head"]))
        except RuntimeError:
            ranges = {}  # fix commits not local (other clone): churn check skipped, not guessed
    out = classify(api_list(f"repos/{r}/pulls/{pr}/reviews"),
                   api_list(f"repos/{r}/pulls/{pr}/comments"),
                   api_list(f"repos/{r}/issues/{pr}/comments"), st, ranges)
    out.update(pr=pr, repo=r, draft=meta["isDraft"], pr_state=meta["state"],
               head=meta["headRefOid"], url=meta["url"])
    return out


# ---------- wait: webhook wake-up, polling backstop ----------

def start_forward(r: str, wake: threading.Event):
    """Return the `gh webhook forward` process, or None when it cannot run here."""
    if not shutil.which("gh"):
        return None
    if "gh-webhook" not in subprocess.run(["gh", "extension", "list"], capture_output=True,
                                          text=True, encoding="utf-8").stdout:
        print("webhook: gh-webhook extension missing, polling (gh extension install cli/gh-webhook)", flush=True)
        return None

    class Hook(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            event = self.headers.get("X-GitHub-Event", "?")
            self.rfile.read(int(self.headers.get("Content-Length") or 0))  # drained, never parsed
            self.send_response(200)
            self.end_headers()
            print(f"webhook: {event}", flush=True)
            wake.set()

        def log_message(self, *a):
            pass

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = http.server.HTTPServer(("127.0.0.1", port), Hook)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    proc = subprocess.Popen(
        ["gh", "webhook", "forward", f"--repo={r}", "--events=pull_request_review,issue_comment",
         f"--url=http://127.0.0.1:{port}/"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    time.sleep(3)
    if proc.poll() is not None:
        print(f"webhook: forward exited ({(proc.stdout.read() or '').strip()[:200]}), polling", flush=True)
        server.shutdown()
        return None
    print(f"webhook: forwarding to 127.0.0.1:{port}", flush=True)
    proc._server = server  # type: ignore[attr-defined]
    return proc


def wait(pr: int, timeout: int, interval: int) -> dict:
    wake = threading.Event()
    start = time.monotonic()
    snap = snapshot(pr)
    if snap["signal"] != "none" or snap["draft"] or snap["pr_state"] != "OPEN":
        return snap
    proc = start_forward(snap["repo"], wake)
    backstop = interval * 4 if proc else interval  # webhook alive: poll rarely, only as insurance
    try:
        while time.monotonic() - start < timeout:
            wake.wait(backstop)
            woke = wake.is_set()
            wake.clear()
            if proc and proc.poll() is not None:
                print("webhook: forward stopped, polling", flush=True)
                proc, backstop = None, interval
            snap = snapshot(pr)
            mins = int((time.monotonic() - start) // 60)
            print(f"waiting {mins}m · {'webhook' if proc else 'polling'} · {'event' if woke else 'tick'} · {snap['signal']}", flush=True)
            if snap["signal"] != "none":
                return snap
        snap["signal"] = "timeout"
        return snap
    finally:
        if proc:
            proc.terminate()  # forward deletes its temporary repo hook on exit
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
            proc._server.shutdown()  # type: ignore[attr-defined]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp949
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("state", "wait", "mark-pushed", "mark-processed", "mark-retried"):
        p = sub.add_parser(name)
        p.add_argument("pr", type=int)
        if name == "wait":
            p.add_argument("--timeout", type=int, default=900)
            p.add_argument("--interval", type=int, default=30)
        if name == "mark-pushed":
            p.add_argument("base")
        if name == "mark-processed":
            p.add_argument("review_id", type=int)
    a = ap.parse_args()
    try:
        if a.cmd == "state":
            print(json.dumps(snapshot(a.pr), ensure_ascii=False))
        elif a.cmd == "wait":
            print(json.dumps(wait(a.pr, a.timeout, a.interval), ensure_ascii=False), flush=True)
        else:
            st = load(a.pr)
            if a.cmd == "mark-pushed":
                st.update(since=now(), rounds=st["rounds"] + 1, fix={"base": a.base, "head": git("rev-parse", "HEAD")})
            elif a.cmd == "mark-processed":
                st["processed"] = sorted(set(st["processed"]) | {a.review_id})
            else:
                st["retried"] = True
            save(a.pr, st)
            print(json.dumps(st, ensure_ascii=False))
    except (GhError, RuntimeError) as e:
        print(json.dumps({"signal": "gh_error", "error": str(e)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
