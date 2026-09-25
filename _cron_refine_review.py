#!/usr/bin/env python3
"""nightly-refine: dump today's user messages + error patterns per non-cron session."""
import sqlite3, datetime, sys

DB = "/Users/zantao/.hermes/state.db"
c = sqlite3.connect(DB)

sessions = c.execute(
    "SELECT id, title, started_at, message_count FROM sessions "
    "WHERE date(started_at,'unixepoch','+8 hours')='2026-09-03' "
    "AND id NOT LIKE 'cron_%' AND message_count >= 10 ORDER BY started_at"
).fetchall()

for sid, title, ts, mc in sessions:
    print("=" * 80)
    print(f"SESSION {sid} title={title!r} msgs={mc}")
    rows = c.execute(
        "SELECT role, content FROM messages WHERE session_id=? AND active=1 "
        "AND role IN ('user','assistant') ORDER BY id", (sid,)
    ).fetchall()
    for role, content in rows:
        if content is None:
            continue
        text = content.strip()
        if role == "user":
            # skip tool-result-ish and cron boilerplate
            if text.startswith("[IMPORTANT: You are running as a scheduled"):
                continue
            print(f"USER: {text[:400]}")
    # count error-ish assistant mentions
    errs = c.execute(
        "SELECT content FROM messages WHERE session_id=? AND role='assistant' AND active=1 "
        "AND (content LIKE ? OR content LIKE ? OR content LIKE ? OR content LIKE ?)",
        (sid, "%报错%", "%失败%", "%根因%", "%不对%"),
    ).fetchall()
    print(f"[assistant msgs mentioning 失败/报错/根因/不对: {len(errs)}]")