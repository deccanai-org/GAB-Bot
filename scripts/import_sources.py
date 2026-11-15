"""Local HTML/PDF import into a review directory. Never fetch URLs or publish entries."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gab_faq.sources import LocalHTML, safe_url  # noqa: E402


def extract(path):
    path = Path(path)
    if path.suffix.lower() in {".html", ".htm"}:
        parser = LocalHTML()
        parser.feed(path.read_text(encoding="utf-8"))
        return [
            {
                "location": "HTML",
                "text": parser.text,
                "links": [vars(link) for link in parser.links],
            }
        ]
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        result = []
        for number, page in enumerate(PdfReader(path).pages, 1):
            links = []
            for ref in page.get("/Annots", []):
                action = ref.get_object().get("/A", {})
                url = str(action.get("/URI", ""))
                if safe_url(url):
                    links.append(
                        {
                            "url": url,
                            "location": f"page {number}",
                            "association": "needs entry review",
                        }
                    )
            result.append(
                {"location": f"page {number}", "text": page.extract_text() or "", "links": links}
            )
        return result
    raise ValueError("Only local HTML and PDF sources are accepted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if str(args.source).startswith(("http:", "https:")):
        raise SystemExit("Remote URLs are not accepted")
    target = args.output.resolve()
    if target.is_relative_to((ROOT / "knowledge/current").resolve()):
        raise SystemExit("Import drafts must remain outside live knowledge/current")
    target.mkdir(parents=True, exist_ok=True)
    record = {
        "source": args.source.name,
        "sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "status": "draft",
        "approved": False,
        "external_processing_approved": False,
        "pages": extract(args.source),
    }
    (target / (args.source.stem + ".json")).write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
