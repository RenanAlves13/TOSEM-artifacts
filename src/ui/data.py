"""Read-only loaders and safe command builders used by the local dashboard.

The UI deliberately reuses the repository's public loaders instead of
reimplementing project discovery, prompt construction, or comparison rules.
This module has no Streamlit dependency so its path and command safeguards can
be tested independently.
"""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from uuid import uuid4

from src.comparison.evaluate import discover_run_descriptors
from src.config import AppConfig, load_app_config
from src.project_loader import ProjectContext, discover_projects
from src.requirement_translations import load_english_requirements
from src.requirements_loader import RequirementsData, load_requirements
from src.static_analysis_loader import StaticAnalysisData, load_static_analysis, read_text


TRACE_PREVIEW_MAX_EVENTS = 1_000
TRACE_PREVIEW_MAX_BYTES = 4_000_000
MAX_DOWNLOAD_BYTES = 10_000_000
MAX_COMMAND_OUTPUT_BYTES = 1_000_000
COMPARISON_MANIFEST_NAME = "ui_last_comparison.json"


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """Repository-local paths exposed by the dashboard."""

    root: Path
    config_path: Path
    systems_dir: Path
    static_analysis_dir: Path
    outputs_dir: Path
    comparison_dir: Path
    ground_truth_dir: Path


@dataclass(slots=True)
class ProjectSnapshot:
    """The canonical project evidence used both by the UI and generation flow."""

    context: ProjectContext
    requirements: RequirementsData
    static_analysis: StaticAnalysisData


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured outcome of a local CLI command started by an explicit UI action."""

    command: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    output_truncated: bool = False


def repository_root() -> Path:
    """Return the repository root regardless of the current working directory."""
    return Path(__file__).resolve().parents[2]


def default_paths(root: Path | None = None) -> WorkspacePaths:
    """Return the fixed workspace locations used by the project conventions."""
    workspace_root = (root or repository_root()).resolve()
    return WorkspacePaths(
        root=workspace_root,
        config_path=workspace_root / "config.yaml",
        systems_dir=workspace_root / "systems",
        static_analysis_dir=workspace_root / "analysis-results" / "static-analysis",
        outputs_dir=workspace_root / "outputs",
        comparison_dir=workspace_root / "comparison_outputs",
        ground_truth_dir=workspace_root / "ground true",
    )


def load_dashboard_config(paths: WorkspacePaths) -> AppConfig:
    """Load the same configuration and dotenv variables used by the CLI."""
    return load_app_config(paths.config_path)


def resolve_workspace_path(root: Path, value: str | Path) -> Path:
    """Resolve a UI path and reject attempts to read or write outside the workspace."""
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("The selected directory must be inside this repository.") from exc
    return resolved


def resolve_managed_path(
    root: Path,
    value: str | Path,
    managed_root: Path,
) -> Path:
    """Resolve a writable UI path only inside its dedicated artifact directory."""
    resolved = resolve_workspace_path(root, value)
    allowed_root = managed_root.resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError as exc:
        relative_name = allowed_root.relative_to(root.resolve()).as_posix()
        raise ValueError(
            f"The selected directory must be '{relative_name}' or one of its subdirectories."
        ) from exc
    return resolved


@contextmanager
def exclusive_job_lock(workspace_root: Path, *, name: str) -> Iterator[Path]:
    """Prevent two dashboard sessions from mutating repository artifacts at once.

    The lock is created atomically. It is intentionally not removed on behalf of a
    different process: a stale lock is safer than letting concurrent jobs overwrite
    the same output files.
    """
    safe_name = "".join(character for character in name if character.isalnum() or character in "-_")
    if not safe_name:
        raise ValueError("The lock name must contain at least one letter or number.")
    lock_root = workspace_root.resolve()
    lock_path = lock_root / f".ui-{safe_name}.lock"
    token = uuid4().hex
    details = (
        f"token={token}\n"
        f"pid={os.getpid()}\n"
        f"started_at_utc={datetime.now(timezone.utc).isoformat()}\n"
    )
    try:
        with lock_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(details)
    except FileExistsError as exc:
        raise RuntimeError(
            f"Another dashboard job appears to be active ({lock_path.name}). "
            "Wait for it to finish. If it was interrupted, inspect and remove that lock manually."
        ) from exc

    try:
        yield lock_path
    finally:
        try:
            current_details = lock_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            current_details = ""
        if f"token={token}" in current_details:
            try:
                lock_path.unlink()
            except OSError:
                pass


def discover_dashboard_projects(paths: WorkspacePaths, config: AppConfig) -> list[ProjectContext]:
    """Discover projects through the same implementation used by ``src.main``."""
    return discover_projects(
        systems_dir=paths.systems_dir,
        static_analysis_root=paths.static_analysis_dir,
        analysis_extensions=config.experiment.analysis_extensions,
    )


def load_project_snapshot(
    paths: WorkspacePaths,
    config: AppConfig,
    project_name: str,
) -> ProjectSnapshot:
    """Load requirements and static artifacts for a selected discovered project."""
    projects = {project.name: project for project in discover_dashboard_projects(paths, config)}
    context = projects.get(project_name)
    if context is None:
        raise ValueError(f"Project '{project_name}' is not available in systems/.")
    source_requirements = load_requirements(context.requirements_csv)
    return ProjectSnapshot(
        context=context,
        requirements=load_english_requirements(
            source_requirements,
            project_name=context.name,
        ),
        static_analysis=load_static_analysis(
            context.static_analysis_dir,
            context.static_analysis_files,
        ),
    )


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read a trusted CSV artifact while tolerating empty cells and encodings."""
    if not path.exists():
        return []
    reader = csv.DictReader(io.StringIO(read_text(path), newline=""))
    rows: list[dict[str, str]] = []
    for raw_row in reader:
        row: dict[str, str] = {}
        for key, value in raw_row.items():
            if key is None:
                continue
            row[key.strip()] = (value or "").strip()
        if row:
            rows.append(row)
    return rows


def read_jsonl_events(
    path: Path,
    *,
    max_events: int = TRACE_PREVIEW_MAX_EVENTS,
    max_bytes: int = TRACE_PREVIEW_MAX_BYTES,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read a bounded JSONL preview without failing on a partial trace."""
    if not path.exists():
        return [], []

    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    bytes_read = 0
    with path.open("rb") as handle:
        line_number = 0
        while len(events) < max_events:
            remaining_bytes = max_bytes - bytes_read
            if remaining_bytes <= 0:
                if handle.read(1):
                    warnings.append(
                        f"Trace preview stopped after {max_bytes:,} bytes; download the original file for the full content."
                    )
                break
            raw_line = handle.readline(remaining_bytes + 1)
            if not raw_line:
                break
            line_number += 1
            if len(raw_line) > remaining_bytes:
                warnings.append(
                    f"Trace preview stopped after {max_bytes:,} bytes; download the original file for the full content."
                )
                break
            bytes_read += len(raw_line)
            line = raw_line.decode("utf-8", errors="replace")
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                warnings.append(f"Line {line_number}: invalid JSON ({exc.msg}).")
                continue
            if not isinstance(event, dict):
                warnings.append(f"Line {line_number}: event is not a JSON object.")
                continue
            events.append(event)
            if len(events) >= max_events:
                warnings.append(
                    f"Trace preview stopped after {max_events:,} valid events; download the original file for the full content."
                )
                break
    return events, warnings


def read_limited_text(path: Path, *, max_chars: int = 50_000) -> tuple[str, bool]:
    """Return text suitable for a UI preview and whether it was truncated."""
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        content = handle.read(max_chars + 1)
    if len(content) <= max_chars:
        return content, False
    return content[:max_chars] + "\n\n[preview truncated]", True


def read_download_bytes(path: Path, *, max_bytes: int = MAX_DOWNLOAD_BYTES) -> bytes:
    """Read a downloadable artifact only when it fits the UI's explicit limit."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"Could not inspect download size: {exc}") from exc
    if size > max_bytes:
        raise ValueError(
            f"The file is {size:,} bytes, above the dashboard download limit of {max_bytes:,} bytes."
        )
    with path.open("rb") as handle:
        content = handle.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(
            f"The file grew beyond the dashboard download limit of {max_bytes:,} bytes while it was read."
        )
    return content


def static_project_overview(paths: WorkspacePaths) -> list[dict[str, str]]:
    """Read the aggregate static-analysis index when available."""
    summary_path = paths.static_analysis_dir / "project_summaries.csv"
    return read_csv_rows(summary_path)


def numeric_value(value: Any) -> int | float:
    """Convert a table value to a number for cards and charts, defaulting to zero."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return 0
    return int(number) if number.is_integer() else number


def provider_rows(config: AppConfig) -> list[dict[str, Any]]:
    """Return provider configuration without exposing credential values."""
    rows: list[dict[str, Any]] = []
    for provider_name, provider in config.providers.items():
        rows.append(
            {
                "provider": provider_name,
                "enabled": provider.enabled,
                "api_key_environment_variable": provider.api_key_env,
                "api_key_configured": bool(os.getenv(provider.api_key_env)),
                "base_url": provider.base_url or "default",
                "models": ", ".join(model.name for model in provider.models),
            }
        )
    return rows


def run_records(outputs_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Discover output runs with the comparison module's canonical resolver."""
    descriptors, issues = discover_run_descriptors(outputs_dir)
    records: list[dict[str, Any]] = []
    for descriptor in descriptors:
        identity = descriptor.identity
        csv_path = safe_output_file(outputs_dir, descriptor.selected_csv_path())
        trace_path = safe_output_file(outputs_dir, descriptor.selected_trace_path())
        prompt_path = prompt_path_for_run(
            outputs_dir=outputs_dir,
            project_name=identity.project_name,
            approach=identity.approach,
            provider=identity.provider,
            model_name=identity.model_name,
            prompt_template=identity.prompt_template,
            run_id=identity.run_id,
            csv_path=csv_path,
        )
        records.append(
            {
                **identity.as_row(),
                "metadata_status": descriptor.metadata_status,
                "metadata_timestamp": descriptor.metadata_timestamp,
                "metadata_error": descriptor.metadata_error,
                "metadata_record_count": descriptor.metadata_record_count,
                "csv_path": path_text(csv_path),
                "csv_exists": bool(csv_path and csv_path.exists()),
                "trace_path": path_text(trace_path),
                "trace_exists": bool(trace_path and trace_path.exists()),
                "prompt_path": path_text(prompt_path),
                "prompt_exists": bool(prompt_path and prompt_path.exists()),
                "pairing_warnings": " | ".join(descriptor.pairing_warnings()),
            }
        )
    return records, issues


def prompt_path_for_run(
    *,
    outputs_dir: Path,
    project_name: str,
    approach: str,
    provider: str,
    model_name: str,
    prompt_template: str,
    run_id: str,
    csv_path: Path | None,
) -> Path | None:
    """Locate a saved prompt even when dry-run or a failed call produced no CSV."""
    candidates: list[Path] = []
    if csv_path is not None:
        candidates.append(csv_path.with_suffix(".prompt.txt"))
    candidates.append(
        outputs_dir
        / project_name
        / approach
        / provider
        / safe_model_fragment(model_name)
        / prompt_template
        / f"{run_id}.prompt.txt"
    )
    safe_candidates = [safe_output_file(outputs_dir, candidate) for candidate in candidates]
    existing = next((candidate for candidate in safe_candidates if candidate and candidate.exists()), None)
    return existing or next((candidate for candidate in safe_candidates if candidate), None)


def safe_output_file(outputs_dir: Path, path: Path | None) -> Path | None:
    """Return an artifact only when it remains inside the selected output root."""
    if path is None or not is_path_within(path, outputs_dir):
        return None
    return path.resolve()


def safe_model_fragment(value: str) -> str:
    """Match the path sanitization used by ``src.main`` without importing its CLI module."""
    sanitized = value.replace("/", "_").replace("\\", "_").replace(":", "_").strip()
    return sanitized or "model"


def is_path_within(path: Path, parent: Path) -> bool:
    """Return whether a resolved file remains inside a resolved parent directory."""
    try:
        path.resolve().relative_to(parent.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def validate_output_artifacts(outputs_dir: Path) -> list[str]:
    """Reject metadata that would make the UI follow artifacts outside its output root."""
    descriptors, discovery_issues = discover_run_descriptors(outputs_dir)
    problems: list[str] = []
    for issue in discovery_issues:
        if (
            issue.get("issue_type") == "invalid_metadata_row"
            and "outside the selected outputs directory" in issue.get("message", "")
        ):
            problems.append(issue["message"])
    for descriptor in descriptors:
        candidates = [
            descriptor.metadata_output_path,
            descriptor.metadata_trace_path,
            *descriptor.scanned_csv_paths,
            *descriptor.scanned_trace_paths,
        ]
        for candidate in candidates:
            if candidate is not None and not is_path_within(candidate, outputs_dir):
                problems.append(
                    f"Run {descriptor.identity.run_id} has an artifact path outside the selected outputs directory: {candidate}"
                )
    return sorted(set(problems))


def path_text(path: Path | None) -> str:
    return path.as_posix() if path is not None else ""


def ground_truth_files(paths: WorkspacePaths, project_name: str) -> list[Path]:
    """Find read-only reference architecture CSVs, matching project names case-insensitively."""
    if (
        not paths.ground_truth_dir.exists()
        or not is_path_within(paths.ground_truth_dir, paths.root)
    ):
        return []
    matching_directories = [
        directory
        for directory in paths.ground_truth_dir.iterdir()
        if (
            directory.is_dir()
            and is_path_within(directory, paths.ground_truth_dir)
            and directory.name.casefold() == project_name.casefold()
        )
    ]
    if not matching_directories:
        return []
    return sorted(
        path
        for path in matching_directories[0].glob("*.csv")
        if path.is_file() and is_path_within(path, paths.ground_truth_dir)
    )


def comparison_report_paths(comparison_dir: Path, root: Path) -> list[Path]:
    """List generated comparison reports that remain within the workspace."""
    safe_directory = resolve_workspace_path(root, comparison_dir)
    if not safe_directory.exists():
        return []
    return sorted(
        path
        for path in safe_directory.glob("*.csv")
        if path.is_file() and is_path_within(path, safe_directory)
    )


def write_comparison_manifest(comparison_dir: Path, payload: dict[str, Any]) -> Path:
    """Persist the filters and timestamp behind the reports shown by the UI."""
    comparison_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = comparison_dir / COMPARISON_MANIFEST_NAME
    temporary_path = comparison_dir / f".{COMPARISON_MANIFEST_NAME}.{uuid4().hex}.tmp"
    document = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    try:
        temporary_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary_path.replace(manifest_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return manifest_path


def read_comparison_manifest(comparison_dir: Path) -> dict[str, Any] | None:
    """Load the optional manifest for the last UI-triggered comparison run."""
    manifest_path = comparison_dir / COMPARISON_MANIFEST_NAME
    if not manifest_path.exists() or not is_path_within(manifest_path, comparison_dir):
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def build_generation_command(
    *,
    project_name: str,
    provider_name: str,
    model_name: str,
    approaches: Iterable[str],
    prompt_templates: Iterable[str],
    runs: int,
    max_attempts: int,
    output_dir: Path,
    dry_run: bool,
    save_prompts: bool,
) -> list[str]:
    """Build one safe argument vector for ``src.main``; never use a shell string."""
    selected_approaches = list(dict.fromkeys(approaches))
    selected_templates = list(dict.fromkeys(prompt_templates))
    if not project_name:
        raise ValueError("Select at least one project.")
    if not provider_name or not model_name:
        raise ValueError("Select a provider and a model.")
    if not selected_approaches or any(value not in {"direct", "agent"} for value in selected_approaches):
        raise ValueError("Select direct, agent, or both approaches.")
    if not selected_templates:
        raise ValueError("Select at least one prompt template.")
    if runs < 1 or max_attempts < 1:
        raise ValueError("Runs and maximum attempts must be positive integers.")

    command = [
        sys.executable,
        "-m",
        "src.main",
        "--project",
        project_name,
        "--provider",
        provider_name,
        "--model",
        model_name,
        "--output-dir",
        output_dir.as_posix(),
        "--runs",
        str(runs),
        "--max-attempts",
        str(max_attempts),
    ]
    for approach in selected_approaches:
        command.extend(("--approach", approach))
    for template in selected_templates:
        command.extend(("--prompt-template", template))
    if dry_run:
        command.append("--dry-run")
    if save_prompts:
        command.append("--save-prompts")
    return command


def build_static_analysis_command(paths: WorkspacePaths) -> list[str]:
    """Build the repository's existing all-project static-analysis command."""
    script_path = paths.root / "static analysis" / "analyze_systems.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Static-analysis script was not found: {script_path}")
    return [sys.executable, script_path.as_posix()]


def run_local_command(
    command: list[str],
    root: Path,
    *,
    timeout_seconds: int = 7_200,
    max_output_bytes: int = MAX_COMMAND_OUTPUT_BYTES,
) -> CommandResult:
    """Execute an approved command without a shell and retain bounded UI logs."""
    if timeout_seconds < 1 or max_output_bytes < 1:
        raise ValueError("Command timeout and output limit must be positive.")
    with tempfile.TemporaryFile(mode="w+b") as stdout_handle, tempfile.TemporaryFile(
        mode="w+b"
    ) as stderr_handle:
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=os.environ.copy(),
                stdout=stdout_handle,
                stderr=stderr_handle,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            stdout, stdout_truncated = read_captured_output(stdout_handle, max_output_bytes)
            stderr, stderr_truncated = read_captured_output(stderr_handle, max_output_bytes)
            timeout_message = f"Command exceeded the {timeout_seconds:,}-second dashboard timeout."
            return CommandResult(
                command=tuple(command),
                return_code=124,
                stdout=stdout,
                stderr="\n".join(part for part in (stderr, timeout_message) if part),
                timed_out=True,
                output_truncated=stdout_truncated or stderr_truncated,
            )
        stdout, stdout_truncated = read_captured_output(stdout_handle, max_output_bytes)
        stderr, stderr_truncated = read_captured_output(stderr_handle, max_output_bytes)
    return CommandResult(
        command=tuple(command),
        return_code=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        output_truncated=stdout_truncated or stderr_truncated,
    )


def read_captured_output(handle, max_bytes: int) -> tuple[str, bool]:
    """Read a temporary subprocess stream without moving an unbounded log into memory."""
    handle.seek(0)
    content = handle.read(max_bytes + 1)
    truncated = len(content) > max_bytes
    if truncated:
        content = content[:max_bytes]
    text = content.decode("utf-8", errors="replace")
    if truncated:
        text += f"\n[dashboard log truncated after {max_bytes:,} bytes]"
    return text, truncated


def format_command(command: Iterable[str]) -> str:
    """Format an argument vector for display in a Windows terminal."""
    return subprocess.list2cmdline(list(command))
