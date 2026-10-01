"""What a session working on one architecture may know of what was learned (docs/05-learnings.md, "How
the record works"): the public view of docs/05, its architecture's JOURNAL.md, and the climb rounds run
on that architecture. Nothing about other architectures, opponents, benches or the referee.
"""
from __future__ import annotations

import json
import re

from regateo.core.config import REPO_DIR, agents_dir, data_dir

TRIED_MAX = 15                         # latest climb results shown: a local proposer's context is small
_ENTRY = re.compile(r"^\*\*L\d+\.")
_INTERNAL_SECTION = "<!-- visibility: internal -->"


def learnings_path():
    return REPO_DIR / "docs" / "05-learnings.md"


def public_view(text: str) -> str:
    """docs/05 without internal sections and internal entries."""
    out: list[str] = []
    for section in re.split(r"(?m)^(?=## )", text):
        if _INTERNAL_SECTION in section:
            continue
        blocks = re.split(r"(?m)^(?=\*\*L\d+\.)", section)
        out += [b for b in blocks if not (_ENTRY.match(b) and re.search(r"(?m)^- Visibility: internal", b))]
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip() + "\n"


def journal(arch: str) -> str:
    path = agents_dir() / arch / "JOURNAL.md"
    return path.read_text().strip() if path.exists() else ""


def climb_log_path():
    return data_dir() / "climb" / "log.jsonl"


def tried(arch: str) -> str:
    """Everything a proposer for `arch` may read about what was tried: public learnings, the architecture's
    journal and its latest climb rounds."""
    parts = [public_view(learnings_path().read_text()).strip()] if learnings_path().exists() else []
    if text := journal(arch):
        parts.append(text)
    if climb_log_path().exists():
        rows = [json.loads(line) for line in climb_log_path().read_text().splitlines() if line.strip()]
        rows = [r for r in rows if r["agent"].startswith(f"{arch}/")][-TRIED_MAX:]
        if rows:
            parts.append("## Latest climb rounds\n\n" + "\n".join(
                f"- {r['agent']}: {r['hypothesis']} Changes: {r['changes']}. Result: {r.get('result', 'pending')}"
                for r in rows))
    return "\n\n".join(parts) or "Nothing yet."
