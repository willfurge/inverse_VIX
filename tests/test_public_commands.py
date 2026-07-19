from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SCRIPTS = (
    "refresh_data.py",
    "run_signal.py",
    "run_sprint3_gate.py",
    "attribution.py",
    "computation_C.py",
)
DATA_COMMANDS = (
    ("run_sprint3_gate.py", ()),
    ("attribution.py", ()),
    ("computation_C.py", ("--offline",)),
)


@pytest.mark.parametrize("script_name", PUBLIC_SCRIPTS)
def test_public_script_help_is_root_independent(tmp_path: Path, script_name: str) -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script_name), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


@pytest.mark.parametrize("script_name, extra_args", DATA_COMMANDS)
def test_data_commands_report_missing_inputs(
    tmp_path: Path, script_name: str, extra_args: tuple[str, ...]
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / script_name),
            "--data-dir",
            str(tmp_path),
            "--results-dir",
            str(tmp_path / "results"),
            *extra_args,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Missing required input files:" in result.stderr
    assert "Traceback" not in result.stderr
