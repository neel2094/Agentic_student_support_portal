"""Cleans the model's answer before it is shown: no ** / __ markers, and tables that the model squeezed onto one
line are put back on separate lines so the UI can draw them as a real table."""
import re

_SEP_IN_LINE = re.compile(r"\|\s*:?-{3,}:?\s*\|")


def clean_answer(text):
    text = str(text or "").replace("\r", "")
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)     # **bold** -> bold
    text = re.sub(r"__(.+?)__", r"\1", text, flags=re.S)         # __bold__ -> bold
    text = text.replace("**", "")                                # stray markers
    fixed = []
    for line in text.split("\n"):
        if len(_SEP_IN_LINE.findall(line)) >= 1 and re.search(r"\|\s+\|", line):  # whole table on one line
            line = re.sub(r"\|\s+\|", "|\n|", line)
            line = re.sub(r"^(?!\s*\|)(.*?)(\|)", lambda m: (m.group(1).rstrip() + "\n\n|") if m.group(1).strip() else "|", line, count=1)
        fixed.append(line)
    text = "\n".join(fixed)
    # a sentence glued after the last table row ("| Status | Paid | You have no balance.") goes to its own paragraph
    text = "\n".join(re.sub(r"^(\s*\|.*\|)\s+([^|\s][^|]*)$", r"\1\n\n\2", l) if l.lstrip().startswith("|") and not l.rstrip().endswith("|") else l
                     for l in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()