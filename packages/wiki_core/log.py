"""Activity log."""

from __future__ import annotations

import datetime

from wiki_core.config import LOG_FILE, ensure_directories


def append_log(action_type: str, summary: str) -> str:
    ensure_directories()
    today = datetime.date.today().isoformat()
    line = f"## [{today}] {action_type} | {summary}\n"
    if not LOG_FILE.exists():
        LOG_FILE.write_text("# LLM Wiki Activity Log\n\nChronological record of wiki operations.\n\n")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line)
    return line.strip()
