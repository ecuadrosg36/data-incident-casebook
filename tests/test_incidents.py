"""Each incident must reach its root cause from the evidence and the fix must actually fix it."""

from pathlib import Path

import duckdb
import pytest

from casebook.case import CONFIRMED, REJECTED, CaseFile, pct
from casebook.cli import INCIDENTS, doc_path, main, render
from casebook.incidents import duplicate_events, join_loss, key_format


def run(incident) -> CaseFile:
    with duckdb.connect() as con:
        return incident.INCIDENT.run(con)


def verdicts(case: CaseFile) -> list[str]:
    return [e.verdict for e in case.evidence]


def metric(case: CaseFile, starts_with: str):
    return next(m for m in case.metrics if m.name.startswith(starts_with))


def test_join_loss_is_traced_to_the_dimension_and_fixed() -> None:
    case = run(join_loss)

    assert verdicts(case) == [REJECTED, REJECTED, CONFIRMED, CONFIRMED]
    assert metric(case, "Days where report").before == "3"
    assert metric(case, "Days where report").after == "0"
    assert metric(case, "Impressions in report").after == f"{join_loss.IMPRESSIONS_PER_DAY:,}"


def test_key_format_is_traced_to_the_crm_and_fixed() -> None:
    case = run(key_format)

    assert verdicts(case) == [REJECTED, REJECTED, CONFIRMED]
    # Everything still unmatched after the fix is a genuinely new contact.
    assert metric(case, "Unmatched contacts").after == f"{key_format.NEW_CONTACTS:,}"
    assert metric(case, "Staged keys breaking").after == "0"


def test_duplicate_events_are_traced_to_appends_and_fixed() -> None:
    case = run(duplicate_events)

    assert verdicts(case) == [REJECTED, REJECTED, CONFIRMED, CONFIRMED]
    assert metric(case, "Dashboard revenue").after == "0.0%"
    assert metric(case, "Duplicate rows").after == "0"
    assert metric(case, "Safe to re-run").after == "yes"


def test_every_case_file_has_all_sections() -> None:
    for incident in INCIDENTS:
        text = render(incident)
        for section in ("## Symptom", "## Investigation", "## Root cause", "## Fix", "## Guard", "## Before and after"):
            assert section in text, (incident.slug, section)


def test_committed_docs_match_the_code() -> None:
    """The case files in docs/ are generated. If this fails, run `casebook docs`."""
    for incident in INCIDENTS:
        path = Path(__file__).parent.parent / doc_path(incident)
        assert path.read_text(encoding="utf-8") == render(incident), f"{path} is stale"


def test_cli_list_run_and_docs(tmp_path: Path, capsys) -> None:
    assert main(["list"]) == 0
    assert "silent-join-loss" in capsys.readouterr().out

    assert main(["run", "key-format-change"]) == 0
    assert "# Incident 02" in capsys.readouterr().out

    assert main(["docs", "--out", str(tmp_path)]) == 0
    assert len(list(tmp_path.glob("*.md"))) == len(INCIDENTS)


def test_cli_rejects_unknown_incident() -> None:
    with pytest.raises(SystemExit, match="unknown incident"):
        main(["run", "99"])


def test_pct_never_prints_negative_zero() -> None:
    assert pct(-0.00001) == "0.0%"
    assert pct(0.153) == "15.3%"
