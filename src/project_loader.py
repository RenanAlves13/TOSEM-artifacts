from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ProjectContext:
    name: str
    system_dir: Path
    requirements_csv: Path
    static_analysis_dir: Path
    static_analysis_files: list[Path]


def discover_projects(
    systems_dir: Path,
    static_analysis_root: Path,
    analysis_extensions: list[str],
) -> list[ProjectContext]:
    if not systems_dir.exists():
        raise FileNotFoundError(f"Systems directory not found: {systems_dir}")

    projects: list[ProjectContext] = []
    for system_dir in sorted(path for path in systems_dir.iterdir() if path.is_dir()):
        requirements_csv = locate_requirements_csv(system_dir)
        static_analysis_dir = static_analysis_root / system_dir.name
        static_analysis_files = locate_static_analysis_files(static_analysis_dir, analysis_extensions)
        projects.append(
            ProjectContext(
                name=system_dir.name,
                system_dir=system_dir,
                requirements_csv=requirements_csv,
                static_analysis_dir=static_analysis_dir,
                static_analysis_files=static_analysis_files,
            )
        )
    return projects


def locate_requirements_csv(system_dir: Path) -> Path:
    csv_files = [path for path in system_dir.rglob("*.csv") if path.is_file()]
    if not csv_files:
        raise FileNotFoundError(f"No CSV file found under {system_dir}")

    def score(path: Path) -> tuple[int, int, int, str]:
        lower_name = path.name.lower()
        lower_path = path.as_posix().lower()
        requirement_hint = 1 if "requis" in lower_name or "requis" in lower_path else 0
        root_distance = len(path.relative_to(system_dir).parts)
        return (-requirement_hint, root_distance, len(path.name), lower_path)

    return sorted(csv_files, key=score)[0]


def locate_static_analysis_files(static_analysis_dir: Path, analysis_extensions: list[str]) -> list[Path]:
    if not static_analysis_dir.exists():
        return []

    allowed = {extension.lower() for extension in analysis_extensions}
    files = [
        path
        for path in static_analysis_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in allowed
    ]
    return sorted(files)
