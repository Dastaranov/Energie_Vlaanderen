from __future__ import annotations

import os
from pathlib import Path

import pytest


REQUIRED_DATA_FILES = (
    "DnbPerGemeente.csv",
    "DNB_ELEK_2026.csv",
    "master_vast_2026.csv",
    "master_var_dyn_2026.csv",
)


def has_required_data(path: Path) -> bool:
    return path.is_dir() and all(
        (path / filename).is_file()
        for filename in REQUIRED_DATA_FILES
    )


@pytest.fixture(scope="session")
def project_root() -> Path:
    root = Path(__file__).resolve().parents[1]

    if not (root / "pyproject.toml").is_file():
        pytest.fail(
            f"Projectroot lijkt ongeldig: {root}. "
            "pyproject.toml werd niet gevonden."
        )

    return root


@pytest.fixture(scope="session")
def data_root(project_root: Path) -> Path:
    candidates: list[Path] = []

    configured = os.getenv("ENERGIEVERGELIJKER_DATA_DIR")
    if configured:
        candidates.append(
            Path(configured).expanduser().resolve()
        )

    current_pointer = project_root / "data" / "current.txt"

    if current_pointer.is_file():
        version = current_pointer.read_text(
            encoding="utf-8"
        ).strip()

        if version:
            candidates.append(
                project_root / "data" / "versions" / version
            )

    candidates.extend(
        [
            project_root / "data" / "current",
            project_root / "data",
            project_root,
        ]
    )

    for candidate in candidates:
        if has_required_data(candidate):
            return candidate

    checked = "\n".join(
        f"  - {candidate}"
        for candidate in candidates
    )

    pytest.skip(
        "Geen volledige integratiedataset gevonden.\n"
        f"Gecontroleerde locaties:\n{checked}\n"
        "Stel ENERGIEVERGELIJKER_DATA_DIR in om "
        "integratietests uit te voeren."
    )