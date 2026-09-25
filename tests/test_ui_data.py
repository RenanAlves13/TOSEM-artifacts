from __future__ import annotations

import json
import sys
import tempfile
import unittest
import csv
from pathlib import Path

from src.static_analysis_loader import StaticAnalysisData, load_csv_rows, static_analysis_totals
from src.ui.data import (
    build_generation_command,
    build_static_analysis_command,
    default_paths,
    exclusive_job_lock,
    read_comparison_manifest,
    read_csv_rows,
    read_jsonl_events,
    resolve_managed_path,
    resolve_workspace_path,
    run_local_command,
    run_records,
    validate_output_artifacts,
    write_comparison_manifest,
)


class UiDataTests(unittest.TestCase):
    def test_resolve_workspace_path_rejects_paths_outside_the_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "workspace"
            root.mkdir()

            self.assertEqual(
                resolve_workspace_path(root, "outputs"),
                (root / "outputs").resolve(),
            )
            with self.assertRaises(ValueError):
                resolve_workspace_path(root, "../outside")

    def test_resolve_managed_path_rejects_repository_source_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "workspace"
            outputs = root / "outputs"
            outputs.mkdir(parents=True)

            self.assertEqual(
                resolve_managed_path(root, "outputs/experiment-a", outputs),
                (outputs / "experiment-a").resolve(),
            )
            with self.assertRaises(ValueError):
                resolve_managed_path(root, "src", outputs)
            with self.assertRaises(ValueError):
                resolve_managed_path(root, ".", outputs)

    def test_generation_command_uses_an_argument_vector_and_repeats_selected_options(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            command = build_generation_command(
                project_name="demo",
                provider_name="deepseek",
                model_name="deepseek-chat",
                approaches=["direct", "agent"],
                prompt_templates=["zero_shot", "few_shot"],
                runs=2,
                max_attempts=3,
                output_dir=root / "outputs",
                dry_run=True,
                save_prompts=True,
            )

            self.assertIn("-m", command)
            self.assertIn("src.main", command)
            self.assertEqual(command.count("--approach"), 2)
            self.assertEqual(command.count("--prompt-template"), 2)
            self.assertIn("--dry-run", command)
            self.assertIn("--save-prompts", command)
            self.assertNotIn("shell=True", command)

    def test_static_analysis_command_targets_the_repository_runner(self) -> None:
        paths = default_paths(Path.cwd())

        command = build_static_analysis_command(paths)

        self.assertEqual(command[1], (paths.root / "static analysis" / "analyze_systems.py").as_posix())

    def test_run_records_discovers_a_safe_inferred_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            csv_path = root / "outputs" / "demo" / "direct" / "deepseek" / "deepseek-chat" / "zero_shot" / "run_1.csv"
            csv_path.parent.mkdir(parents=True)
            csv_path.write_text(
                "microservice_name,responsibility,communicates_with\n"
                "Catalog Service,Manages product catalog,\n",
                encoding="utf-8",
            )

            records, issues = run_records(root / "outputs")

            self.assertEqual(issues, [])
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]["csv_exists"])
            self.assertEqual(records[0]["approach"], "direct")
            self.assertEqual(records[0]["provider"], "deepseek")

    def test_run_records_finds_saved_prompt_when_dry_run_has_no_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            outputs_dir = root / "outputs"
            prompt_path = (
                outputs_dir
                / "demo"
                / "direct"
                / "deepseek"
                / "deepseek-chat"
                / "zero_shot"
                / "run_1.prompt.txt"
            )
            prompt_path.parent.mkdir(parents=True)
            prompt_path.write_text("saved prompt", encoding="utf-8")
            write_metadata(
                outputs_dir / "metadata.csv",
                [
                    {
                        "project_name": "demo",
                        "approach": "direct",
                        "provider": "deepseek",
                        "model": "deepseek-chat",
                        "prompt_template": "zero_shot",
                        "run_number": "1",
                        "output_path": "",
                        "trace_path": "",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "status": "dry_run",
                        "error": "",
                    }
                ],
            )

            records, issues = run_records(outputs_dir)

            self.assertEqual(issues, [])
            self.assertEqual(len(records), 1)
            self.assertFalse(records[0]["csv_exists"])
            self.assertTrue(records[0]["prompt_exists"])
            self.assertEqual(Path(records[0]["prompt_path"]), prompt_path.resolve())

    def test_run_records_does_not_follow_a_prompt_path_outside_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            outputs_dir = root / "outputs"
            external_prompt = (
                root
                / "escaped-project"
                / "direct"
                / "deepseek"
                / "deepseek-chat"
                / "zero_shot"
                / "run_1.prompt.txt"
            )
            external_prompt.parent.mkdir(parents=True)
            external_prompt.write_text("must remain hidden", encoding="utf-8")
            write_metadata(
                outputs_dir / "metadata.csv",
                [
                    {
                        "project_name": "../escaped-project",
                        "approach": "direct",
                        "provider": "deepseek",
                        "model": "deepseek-chat",
                        "prompt_template": "zero_shot",
                        "run_number": "1",
                        "output_path": "",
                        "trace_path": "",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "status": "dry_run",
                        "error": "",
                    }
                ],
            )

            records, _ = run_records(outputs_dir)

            self.assertEqual(len(records), 1)
            self.assertFalse(records[0]["prompt_exists"])
            self.assertEqual(records[0]["prompt_path"], "")

    def test_validate_output_artifacts_blocks_metadata_pointing_outside_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            outputs_dir = root / "outputs"
            outside_path = root / "outside.csv"
            outside_path.write_text("not an output", encoding="utf-8")
            write_metadata(
                outputs_dir / "metadata.csv",
                [
                    {
                        "project_name": "demo",
                        "approach": "direct",
                        "provider": "deepseek",
                        "model": "deepseek-chat",
                        "prompt_template": "zero_shot",
                        "run_number": "1",
                        "output_path": outside_path.as_posix(),
                        "trace_path": "",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "status": "success",
                        "error": "",
                    }
                ],
            )

            problems = validate_output_artifacts(outputs_dir)
            records, _ = run_records(outputs_dir)

            self.assertEqual(len(problems), 1)
            self.assertEqual(records, [])

    def test_csv_reader_preserves_newlines_inside_quoted_cells(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "requirements.csv"
            csv_path.write_text(
                'id,responsibility\n1,"first line\nsecond line"\n',
                encoding="utf-8",
            )

            rows = read_csv_rows(csv_path)

            self.assertEqual(rows[0]["responsibility"], "first line\nsecond line")

    def test_static_analysis_loader_preserves_newlines_inside_quoted_cells(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "classes.csv"
            csv_path.write_text(
                'type_name,annotations\nExample,"first line\nsecond line"\n',
                encoding="utf-8",
            )

            rows = load_csv_rows(csv_path)

            self.assertEqual(rows[0]["annotations"], "first line\nsecond line")

    def test_static_analysis_totals_derive_values_from_loaded_artifacts(self) -> None:
        data = StaticAnalysisData(
            root_dir=Path("analysis-results/demo"),
            files=[],
            summary={"counts": {"source_roots": 2, "java_files": 3}},
            modules=[
                {"declared_submodules": "api|web", "parse_error": ""},
                {"declared_submodules": "", "parse_error": "invalid XML"},
            ],
            package_metrics=[{"package": "demo.api"}, {"package": "demo.web"}],
            package_dependencies=[
                {"category": "internal", "count": "4"},
                {"category": "external", "count": "7"},
            ],
            entrypoints=[{"type_name": "Application"}],
            classes=[
                {
                    "source_set": "main",
                    "type_kind": "class",
                    "role": "controller",
                    "method_count": "0",
                    "public_method_count": "0",
                    "line_count": "12",
                    "effective_line_count": "8",
                    "import_count": "3",
                    "internal_import_count": "1",
                    "external_import_count": "2",
                },
                {
                    "source_set": "test",
                    "type_kind": "interface",
                    "role": "test",
                    "method_count": "2",
                    "public_method_count": "2",
                    "line_count": "20",
                    "effective_line_count": "16",
                    "import_count": "5",
                    "internal_import_count": "0",
                    "external_import_count": "5",
                },
            ],
        )

        totals = static_analysis_totals(data)

        self.assertEqual(totals["build_files"], 2)
        self.assertEqual(totals["declared_submodules"], 2)
        self.assertEqual(totals["modules_with_parse_errors"], 1)
        self.assertEqual(totals["classes"], 2)
        self.assertEqual(totals["methods"], 2)
        self.assertEqual(totals["public_methods"], 2)
        self.assertEqual(totals["source_lines"], 32)
        self.assertEqual(totals["effective_source_lines"], 24)
        self.assertEqual(totals["internal_imports"], 1)
        self.assertEqual(totals["external_imports"], 7)
        self.assertEqual(totals["package_dependency_edges"], 2)
        self.assertEqual(totals["internal_package_dependency_occurrences"], 4)
        self.assertEqual(totals["external_package_dependency_occurrences"], 7)
        self.assertEqual(totals["inferred_roles"], 2)
        self.assertEqual(totals["type_kinds"], 2)

    def test_jsonl_reader_keeps_valid_events_when_a_line_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            trace_path = Path(temporary_directory) / "run_1.trace.jsonl"
            trace_path.write_text(
                json.dumps({"event_type": "run_started"}) + "\n{invalid}\n",
                encoding="utf-8",
            )

            events, warnings = read_jsonl_events(trace_path)

            self.assertEqual(events, [{"event_type": "run_started"}])
            self.assertEqual(len(warnings), 1)

    def test_jsonl_reader_stops_at_the_requested_event_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            trace_path = Path(temporary_directory) / "run_1.trace.jsonl"
            trace_path.write_text(
                "\n".join(json.dumps({"event_type": f"event-{index}"}) for index in range(3)),
                encoding="utf-8",
            )

            events, warnings = read_jsonl_events(trace_path, max_events=1)

            self.assertEqual(events, [{"event_type": "event-0"}])
            self.assertTrue(any("1 valid events" in warning for warning in warnings))

    def test_jsonl_reader_stops_before_an_oversized_single_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            trace_path = Path(temporary_directory) / "run_1.trace.jsonl"
            trace_path.write_bytes(b"{" + (b"x" * 100) + b"}\n")

            events, warnings = read_jsonl_events(trace_path, max_bytes=16)

            self.assertEqual(events, [])
            self.assertTrue(any("16 bytes" in warning for warning in warnings))

    def test_exclusive_job_lock_releases_only_its_own_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            lock_path = root / ".ui-workbench.lock"
            with exclusive_job_lock(root, name="workbench"):
                self.assertTrue(lock_path.exists())
                with self.assertRaises(RuntimeError):
                    with exclusive_job_lock(root, name="workbench"):
                        pass
            self.assertFalse(lock_path.exists())

    def test_comparison_manifest_keeps_filter_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            comparison_dir = Path(temporary_directory) / "comparison_outputs"

            write_comparison_manifest(
                comparison_dir,
                {"outputs_directory": "outputs/deepseek", "filters": {"project": "demo"}},
            )
            manifest = read_comparison_manifest(comparison_dir)

            self.assertIsNotNone(manifest)
            assert manifest is not None
            self.assertEqual(manifest["outputs_directory"], "outputs/deepseek")
            self.assertEqual(manifest["filters"], {"project": "demo"})

    def test_local_command_truncates_large_logs_without_losing_the_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = run_local_command(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.write('x' * 64); sys.stderr.write('y' * 64)",
                ],
                Path(temporary_directory),
                max_output_bytes=16,
            )

            self.assertEqual(result.return_code, 0)
            self.assertTrue(result.output_truncated)
            self.assertIn("truncated after 16 bytes", result.stdout)
            self.assertIn("truncated after 16 bytes", result.stderr)


def write_metadata(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "project_name",
        "approach",
        "provider",
        "model",
        "prompt_template",
        "run_number",
        "output_path",
        "trace_path",
        "timestamp",
        "status",
        "error",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
