"""Reads one PDF in a separate process: PDF bytes on stdin, JSON on stdout.

The embedded admin tab runs inside the bot, which holds the Discord token, the Qwen key and the
database account. PDF parsers have a history of hostile-file bugs (hangs, huge memory), so the
parsing happens here instead: a fresh interpreter with none of those secrets in its environment,
a memory ceiling and a CPU ceiling (where the OS supports them), and a wall-clock limit enforced by
the parent (`pdf_import.extract_pages_isolated`).

Usage (done for you): python -I pdf_worker.py <memory_mb> <cpu_seconds> < file.pdf
"""

import json
import sys
from pathlib import Path


def main() -> int:
    memory_mb, cpu_seconds = int(sys.argv[1]), int(sys.argv[2])
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 2**20, memory_mb * 2**20))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5))
    except (ImportError, ValueError, OSError):
        pass  # no `resource` module (Windows): the parent's timeout still applies
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # -I drops the script directory
    data = sys.stdin.buffer.read()
    from gab_faq.admin.pdf_import import PdfImportError, extract_pages

    try:
        result = {"pages": extract_pages(data)}
    except PdfImportError as error:
        result = {"error": str(error)}
    except MemoryError:
        result = {"error": "The PDF is too large or too complex to read."}
    sys.stdout.buffer.write(json.dumps(result).encode("ascii"))  # ensure_ascii: always safe bytes
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
