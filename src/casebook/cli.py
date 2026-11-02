"""`casebook list`, `casebook run <n|all>` and `casebook docs` (rewrites the case files in docs/)."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb

from casebook.case import Incident, to_markdown
from casebook.incidents import duplicate_events, join_loss, key_format

INCIDENTS: tuple[Incident, ...] = (join_loss.INCIDENT, key_format.INCIDENT, duplicate_events.INCIDENT)
DOCS_DIR = Path("docs")


def doc_path(incident: Incident, folder: Path = DOCS_DIR) -> Path:
    return folder / f"{incident.number:02d}-{incident.slug}.md"


def render(incident: Incident) -> str:
    """Each incident gets a fresh in-memory database, so runs never affect each other."""
    with duckdb.connect() as con:
        return to_markdown(incident.run(con))


def _select(choice: str) -> tuple[Incident, ...]:
    if choice == "all":
        return INCIDENTS
    matches = tuple(i for i in INCIDENTS if str(i.number) == choice or i.slug == choice)
    if not matches:
        raise SystemExit(f"casebook: unknown incident {choice!r}. Try `casebook list`.")
    return matches


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="casebook", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="Show the incidents")
    run = commands.add_parser("run", help="Investigate one incident (number or slug) or all")
    run.add_argument("incident", nargs="?", default="all")
    docs = commands.add_parser("docs", help="Write every case file to a folder")
    docs.add_argument("--out", type=Path, default=DOCS_DIR)
    args = parser.parse_args(argv)

    if args.command == "list":
        for incident in INCIDENTS:
            print(f"{incident.number:02d}  {incident.slug:<20} {incident.title}")
    elif args.command == "run":
        print("\n".join(render(incident) for incident in _select(args.incident)))
    else:
        args.out.mkdir(parents=True, exist_ok=True)
        for incident in INCIDENTS:
            doc_path(incident, args.out).write_text(render(incident), encoding="utf-8")
            print(f"wrote {doc_path(incident, args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
