"""Back up or verify bot state; restore requires a fresh directory and stopped bot."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gab_faq.backups import backup, restore, verify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["backup", "verify", "restore"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.command == "verify":
        verify(args.source)
    else:
        if args.destination is None:
            parser.error("--destination is required")
        if args.command == "backup":
            backup(args.source, args.destination)
        else:
            restore(args.source, args.destination)
    print(f"{args.command}: verified successfully")


if __name__ == "__main__":
    main()
