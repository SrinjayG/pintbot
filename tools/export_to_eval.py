"""Turn a WhatsApp chat export into an eval file you can label.

WhatsApp → open the group → group info → Export chat → Include media.
Unzip it, then:  python tools/export_to_eval.py path/to/_chat.txt > evals/labelled.jsonl
Open the file and fill in "expected_points" for ~50 messages (leave null to skip a line).
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

# iOS:     [20/11/2026, 01:23:45] Name: text
# Android: 20/11/2026, 01:23 - Name: text
LINE = re.compile(
    r"^‎?\[?(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),? (?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap][Mm])?)\]?"
    r"(?: -)? (?P<name>[^:]+): (?P<text>.*)$"
)
ATTACH = re.compile(r"<attached: (?P<file>[^>]+)>|(?P<file2>\S+\.(?:jpg|jpeg|png|webp)) \(file attached\)")


def parse(path: Path):
    messages = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.replace("‎", "").strip()
        m = LINE.match(line)
        if m:
            messages.append({"name": m["name"].strip(), "text": m["text"].strip(), "date": m["date"], "time": m["time"]})
        elif messages and line:
            messages[-1]["text"] += "\n" + line  # continuation of a multi-line message
    return messages


def main() -> None:
    src = Path(sys.argv[1])
    for i, m in enumerate(parse(src)):
        text, photo = m["text"], None
        a = ATTACH.search(text)
        if a:
            fname = a["file"] or a["file2"]
            photo = str((src.parent / fname).resolve())
            text = ATTACH.sub("", text).strip()
        print(json.dumps({"id": f"export-{i}", "sender_name": m["name"], "text": text,
                          "photo": photo, "when": f'{m["date"]} {m["time"]}', "expected_points": None},
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
