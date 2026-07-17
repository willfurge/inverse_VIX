"""Shared ingest-time validation pass (thesis.md §9, plan.md Sprint 1.2 step 4).

Every loader calls this; failures raise, they never warn-and-continue.
"""


def validate_panel(df, checks: list[str] | None = None) -> None:
    """Run the shared validation suite against a freshly-loaded panel. Sprint 1.

    Raises on any failed check (monotonic dates, no duplicates, expected gaps
    only on known holidays, etc.) — never logs a warning and continues.
    """
    raise NotImplementedError("Sprint 1: implement shared validation checks.")
