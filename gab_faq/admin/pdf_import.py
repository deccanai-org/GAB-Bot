"""PDF -> draft FAQ document. Extraction is local (pypdf, no network, no AI): the PM reviews and
edits every drafted entry before it can be published.

The bot answers from numbered entries ("A1. Question" followed by the answer). A guideline PDF is
prose, so the draft is a best-effort split: questions and headings start entries. Expect to
reword titles and merge or split entries in the editor.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from datetime import date

import yaml

MAX_PAGES = 400


class PdfImportError(ValueError):
    """The PDF cannot be turned into a draft; the message is safe to show the PM."""


def extract_pages(data: bytes) -> list[str]:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
    except ImportError as error:  # pragma: no cover - admin extra not installed
        raise PdfImportError("PDF support needs: pip install -r requirements-admin.txt") from error
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise PdfImportError("The PDF is password protected. Remove the password and retry.")
        if len(reader.pages) > MAX_PAGES:
            raise PdfImportError(f"The PDF has more than {MAX_PAGES} pages.")
        pages = [(page.extract_text() or "") for page in reader.pages]
    except PdfImportError:
        raise
    except (PyPdfError, ValueError, KeyError, OSError, RecursionError) as error:
        raise PdfImportError(f"The PDF could not be read ({type(error).__name__}).") from error
    if not any(page.strip() for page in pages):
        raise PdfImportError(
            "The PDF has no selectable text (a scanned image?). OCR is not supported: export "
            "the document as a text PDF."
        )
    return pages


PAGE_NUMBER = re.compile(r"^(page\s*)?\d{1,4}(\s*(/|of)\s*\d{1,4})?$", re.IGNORECASE)
LEADING_NUMBER = re.compile(r"^(?:q(?:uestion)?\s*\d+|\d{1,3}(?:\.\d{1,3})*)\s*[.):-]\s+", re.I)
# "1. Title" or "1.2 Title", not a date such as "14 Nov 2026".
NUMBERED_HEADING = re.compile(r"^(?:\d{1,2}[.)]|\d{1,2}(?:\.\d{1,2})+)\s+[A-Z][^.?!]{2,78}$")
INLINE_QA = re.compile(r"^(?:Q\d+\s*[.:)]\s*)?(?P<q>[^?]{6,200}\?)\s*A\s*:\s*(?P<a>.+)$")
BULLET_SPLIT = re.compile(r"\s*[●•▪◦■]\s*")
STARTS_ITEM = re.compile(r"^(?:[-*]\s|\d{1,2}[.)]\s|[A-Za-z]{1,2}:\s)")
SENTENCE_END = (".", "?", "!", ":")
# The bot reads these line shapes as structure; a body line that merely looks like one is defused.
ENTRY_LIKE = re.compile(r"^([A-Z]{1,3}\d+[a-z]?)\.(\s+)")
HEADING_LIKE = re.compile(r"^#{1,6}\s+")


def body_line(line: str) -> str:
    """A line like 'Q7. text', '# text' or '<!-- text -->' would be taken by the bot as an entry,
    heading or directive, so the PDF's own numbering inside an answer is rewritten ('Q7) text')."""
    line = ENTRY_LIKE.sub(r"\1)\2", line)
    line = HEADING_LIKE.sub("", line)
    if line.startswith("<!--") and line.endswith("-->"):
        line = line[4:-3].strip()
    return line


def clean_lines(pages: list[str]) -> list[str]:
    """Lines in reading order: spaces collapsed, blank lines gone, page numbers and headers or
    footers repeated on most pages removed, run-together bullets split onto their own lines."""
    per_page = [[" ".join(line.split()) for line in page.splitlines()] for page in pages]
    repeated: set[str] = set()
    if len(pages) >= 3:
        counts = Counter(line for lines in per_page for line in set(lines) if line)
        repeated = {line for line, n in counts.items() if n >= max(3, 0.6 * len(pages))}
    out: list[str] = []
    for lines in per_page:
        for line in lines:
            if not line or line in repeated or PAGE_NUMBER.match(line):
                continue
            if BULLET_SPLIT.search(line):
                first, *items = BULLET_SPLIT.split(line)
                if first.strip():
                    out.append(first.strip())
                out.extend(f"- {item.strip()}" for item in items if item.strip())
            else:
                out.append(line)
    return out


def is_question(line: str) -> bool:
    return 8 <= len(line) <= 220 and line.endswith("?") and (line[0].isupper() or line[0].isdigit())


SMALL_WORDS = {"a", "an", "and", "of", "the", "to", "for", "in", "on", "or", "with"}


def is_heading(line: str) -> bool:
    if not 3 <= len(line) <= 80 or line.endswith((".", ",", ";", ":", "?")):
        return False
    if line.startswith(("-", "*")):
        return False
    if NUMBERED_HEADING.match(line):
        return True
    letters = [c for c in line if c.isalpha()]
    if len(letters) >= 4 and all(c.isupper() for c in letters):
        return True
    words = [w for w in line.split() if w[0].isalpha()]
    return (
        (2 <= len(line.split()) <= 8 or (len(line.split()) == 1 and len(line) >= 4))
        and bool(words)
        and words[0][0].isupper()
        and all(w[0].isupper() or w.lower() in SMALL_WORDS for w in words)
        and not any(w.endswith((".", ",")) for w in words)
    )


def choose_prefix(title: str, taken: set[str]) -> str:
    """Entry IDs are global, so pick a 1-3 letter prefix no other document uses."""
    initials = "".join(w[0] for w in re.findall(r"[A-Za-z]+", title))[:3].upper()
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    candidates = ([initials] if initials else []) + list(letters)
    candidates += [a + b for a in letters for b in letters]
    return next(c for c in candidates if c not in taken)


def add_body(body: list[str], line: str) -> None:
    """Append a line, joining it to the previous one when the PDF wrapped a sentence."""
    line = body_line(line)
    if body and not body[-1].endswith(SENTENCE_END) and not STARTS_ITEM.match(line):
        body[-1] += " " + line
    else:
        body.append(line)


def structure(lines: list[str], title: str, prefix: str) -> str:
    """Markdown body: '## section' lines and numbered entries.

    A question starts an entry ('Question? A: answer' on one line is split into both). A short
    heading-like line starts one only at the start of a paragraph (the first line, or after a
    sentence end or another heading), so the wrapped last line of a paragraph is not mistaken for
    a heading. A heading straight before another heading or question becomes a '## section'."""
    blocks: list[tuple[str, str, list[str]]] = []  # (kind, title, body lines)
    current: tuple[str, str, list[str]] | None = None
    previous = ""
    for index, line in enumerate(lines):
        starts_paragraph = (
            not previous
            or previous.endswith(SENTENCE_END)
            or is_heading(previous)
            or is_question(previous)
        )
        following = next(iter(lines[index + 1 : index + 2]), "")
        inline = INLINE_QA.match(line)
        if inline:
            current = ("entry", LEADING_NUMBER.sub("", inline["q"]).strip(), [])
            add_body(current[2], inline["a"].strip())
            blocks.append(current)
        elif is_question(line):
            current = ("entry", LEADING_NUMBER.sub("", line).strip(), [])
            blocks.append(current)
        elif starts_paragraph and is_heading(line):
            kind = "section" if (is_heading(following) or is_question(following)) else "entry"
            current = (kind, LEADING_NUMBER.sub("", line).strip(), [])
            blocks.append(current)
        else:
            if current is None:
                current = ("entry", title, [])
                blocks.append(current)
            add_body(current[2], line)
        previous = line
    out: list[str] = []
    number = 0
    for kind, heading, body in blocks:
        text = "\n".join(body).strip()
        if kind == "section":
            out.append(f"\n## {heading}\n")
        elif text:
            number += 1
            out.append(f"{prefix}{number}. {heading}\n{text}\n")
    return "\n".join(out).strip() + "\n"


def draft_markdown(
    title: str, filename: str, pages: list[str], taken_prefixes: set[str], today: date | None = None
) -> str:
    today = today or date.today()
    header = yaml.safe_dump(
        {
            "title": title,
            "audience": "all",
            "phase": "",
            "updated": today.isoformat(),
            "source": f"{filename} (uploaded {today.isoformat()})",
        },
        sort_keys=False,
        allow_unicode=True,
    )
    prefix = choose_prefix(title, taken_prefixes)
    body = structure(clean_lines(pages), title, prefix)
    return (
        f"---\n{header}---\n"
        "<!-- DRAFT drafted from the PDF text. Check every entry: the question line, the answer, "
        "the audience, and delete anything the bot should not say. -->\n\n"
        f"{body}"
    )
