from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.comparison.evaluate import discover_run_descriptors, run_comparison
from src.comparison.trace_metrics import analyze_trace


class StrategyComparisonTests(unittest.TestCase):
    def test_calculates_architecture_process_and_paired_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            outputs_dir = workspace / "outputs"
            comparison_dir = workspace / "comparison"

            direct_dir = outputs_dir / "demo" / "direct" / "openai" / "model-x" / "few_shot"
            agent_dir = outputs_dir / "demo" / "agent" / "openai" / "model-x" / "few_shot"
            write_decomposition(
                direct_dir / "run_1.csv",
                [
                    ("Customer Service", "Manages customer profiles and account information.", "Order Service"),
                    (
                        "Order Service",
                        "Creates orders and manages their status.",
                        "Customer Service; Missing Service",
                    ),
                ],
            )
            write_decomposition(
                agent_dir / "run_1.csv",
                [
                    (
                        "Customer Service",
                        "Manages customer identity and delivery addresses.",
                        "Delivery Operations Service",
                    ),
                    (
                        "Delivery Operations Service",
                        "Manages delivery requests, routes, and parcel status.",
                        "Customer Service",
                    ),
                ],
            )
            write_trace(
                direct_dir / "run_1.trace.jsonl",
                [
                    {"timestamp": "2026-01-01T00:00:00+00:00", "event_type": "run_started"},
                    {
                        "timestamp": "2026-01-01T00:00:01+00:00",
                        "event_type": "agent_call",
                        "role": "direct_generator",
                        "attempt": 1,
                        "status": "success",
                        "duration_ms": 100,
                        "system_prompt": "system",
                        "user_prompt": "user",
                        "raw_response": "response",
                    },
                    {
                        "timestamp": "2026-01-01T00:00:01+00:00",
                        "event_type": "architecture_snapshot",
                        "phase": "final",
                        "architecture": {"microservices": []},
                    },
                    {
                        "timestamp": "2026-01-01T00:00:02+00:00",
                        "event_type": "run_finished",
                        "status": "success",
                    },
                ],
            )
            write_trace(
                agent_dir / "run_1.trace.jsonl",
                [
                    {"timestamp": "2026-01-01T00:00:00+00:00", "event_type": "run_started"},
                    {
                        "timestamp": "2026-01-01T00:00:01+00:00",
                        "event_type": "agent_call",
                        "role": "domain_analyst",
                        "attempt": 1,
                        "status": "success",
                        "duration_ms": 100,
                        "system_prompt": "system",
                        "user_prompt": "user",
                        "raw_response": "response",
                    },
                    {
                        "timestamp": "2026-01-01T00:00:02+00:00",
                        "event_type": "agent_call",
                        "role": "critic",
                        "attempt": 1,
                        "status": "success",
                        "duration_ms": 120,
                        "system_prompt": "system",
                        "user_prompt": "user",
                        "raw_response": "response",
                    },
                    {
                        "timestamp": "2026-01-01T00:00:02+00:00",
                        "event_type": "critique_decision",
                        "requires_revision": True,
                        "issue_count": 2,
                        "issue_categories": ["missing_interaction", "nanoservice"],
                        "issue_severities": ["high", "medium"],
                    },
                    {
                        "timestamp": "2026-01-01T00:00:02+00:00",
                        "event_type": "architecture_snapshot",
                        "phase": "candidate",
                        "architecture": {"microservices": []},
                    },
                    {
                        "timestamp": "2026-01-01T00:00:03+00:00",
                        "event_type": "architecture_snapshot",
                        "phase": "refined",
                        "architecture": {"microservices": []},
                        "changes": {
                            "services_added": ["Delivery Operations Service"],
                            "services_removed": [],
                            "interactions_added": [
                                "Customer Service -> Delivery Operations Service"
                            ],
                            "interactions_removed": [],
                        },
                    },
                    {
                        "timestamp": "2026-01-01T00:00:04+00:00",
                        "event_type": "run_finished",
                        "status": "success",
                    },
                ],
            )

            result = run_comparison(outputs_dir=outputs_dir, comparison_dir=comparison_dir)

            self.assertEqual(result.discovered_run_count, 2)
            self.assertEqual(result.architecture_run_count, 2)
            self.assertEqual(result.paired_run_count, 1)
            self.assertEqual(
                {path.name for path in comparison_dir.iterdir()},
                {
                    "architecture_metrics_by_run.csv",
                    "process_metrics_by_run.csv",
                    "run_metrics_long.csv",
                    "approach_metric_summary.csv",
                    "pairing_report.csv",
                    "paired_architecture_similarity.csv",
                    "paired_metric_deltas.csv",
                    "paired_metric_summary.csv",
                    "stability_by_approach.csv",
                    "comparison_issues.csv",
                },
            )

            architecture_rows = read_csv(comparison_dir / "architecture_metrics_by_run.csv")
            direct_row = next(row for row in architecture_rows if row["approach"] == "direct")
            self.assertEqual(direct_row["service_count"], "2")
            self.assertEqual(direct_row["valid_communication_count"], "2")
            self.assertEqual(direct_row["invalid_communication_target_count"], "1")
            self.assertEqual(direct_row["communication_density"], "1.0")

            process_rows = read_csv(comparison_dir / "process_metrics_by_run.csv")
            agent_row = next(row for row in process_rows if row["approach"] == "agent")
            self.assertEqual(agent_row["llm_call_count"], "2")
            self.assertEqual(agent_row["revision_request_count"], "1")
            self.assertEqual(agent_row["services_added_during_refinement_count"], "1")

            pairing_rows = read_csv(comparison_dir / "pairing_report.csv")
            self.assertEqual(pairing_rows[0]["pair_status"], "paired")
            similarity_rows = read_csv(comparison_dir / "paired_architecture_similarity.csv")
            self.assertEqual(similarity_rows[0]["service_set_jaccard"], str(1 / 3))

    def test_classifies_legacy_output_as_direct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            outputs_dir = Path(temporary_directory) / "outputs"
            legacy_path = outputs_dir / "demo" / "openai" / "model-x" / "zero_shot" / "run_2.csv"
            write_decomposition(
                legacy_path,
                [("Catalog Service", "Manages the item catalog.", "")],
            )

            descriptors, issues = discover_run_descriptors(outputs_dir)

            self.assertEqual(issues, [])
            self.assertEqual(len(descriptors), 1)
            self.assertEqual(descriptors[0].identity.approach, "direct")
            self.assertEqual(descriptors[0].identity.run_id, "run_2")

    def test_uses_current_metadata_paths_with_a_custom_outputs_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            outputs_dir = workspace / "experiment-results"
            direct_path = (
                outputs_dir / "demo" / "direct" / "openai" / "model-x" / "zero_shot" / "run_1.csv"
            )
            agent_path = (
                outputs_dir / "demo" / "agent" / "openai" / "model-x" / "zero_shot" / "run_1.csv"
            )
            write_decomposition(
                direct_path,
                [("Catalog Service", "Manages the item catalog.", "")],
            )
            write_decomposition(
                agent_path,
                [("Catalog Service", "Manages the item catalog.", "")],
            )
            write_metadata(
                outputs_dir / "metadata.csv",
                [
                    {
                        "project_name": "demo",
                        "approach": "direct",
                        "provider": "openai",
                        "model": "model-x",
                        "prompt_template": "zero_shot",
                        "run_number": "1",
                        "output_path": "experiment-results/demo/direct/openai/model-x/zero_shot/run_1.csv",
                        "trace_path": "",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "status": "success",
                        "error": "",
                    },
                    {
                        "project_name": "demo",
                        "approach": "agent",
                        "provider": "openai",
                        "model": "model-x",
                        "prompt_template": "zero_shot",
                        "run_number": "1",
                        "output_path": "experiment-results/demo/agent/openai/model-x/zero_shot/run_1.csv",
                        "trace_path": "",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "status": "success",
                        "error": "",
                    },
                ],
            )

            result = run_comparison(
                outputs_dir=outputs_dir,
                comparison_dir=workspace / "comparison",
            )

            self.assertEqual(result.architecture_run_count, 2)
            rows = read_csv(workspace / "comparison" / "architecture_metrics_by_run.csv")
            self.assertEqual({row["metadata_status"] for row in rows}, {"success"})

    def test_marks_duplicate_direct_csvs_as_unpaired(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            outputs_dir = workspace / "outputs"
            write_decomposition(
                outputs_dir / "demo" / "direct" / "openai" / "model-x" / "zero_shot" / "run_1.csv",
                [("Catalog Service", "Manages the item catalog.", "")],
            )
            write_decomposition(
                outputs_dir / "demo" / "openai" / "model-x" / "zero_shot" / "run_1.csv",
                [("Catalog Service", "Manages the item catalog.", "")],
            )
            write_decomposition(
                outputs_dir / "demo" / "agent" / "openai" / "model-x" / "zero_shot" / "run_1.csv",
                [("Catalog Service", "Manages the item catalog.", "")],
            )

            run_comparison(outputs_dir=outputs_dir, comparison_dir=workspace / "comparison")

            pairing_rows = read_csv(workspace / "comparison" / "pairing_report.csv")
            self.assertEqual(pairing_rows[0]["pair_status"], "duplicate_direct")

    def test_treats_a_completely_invalid_trace_as_partial(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            trace_path = Path(temporary_directory) / "run_1.trace.jsonl"
            trace_path.write_text("{not valid JSON}\n", encoding="utf-8")

            metrics, warnings = analyze_trace(trace_path)

            self.assertEqual(metrics["trace_status"], "partial")
            self.assertEqual(metrics["trace_invalid_json_line_count"], 1)
            self.assertTrue(
                any("not valid JSON" in warning for warning in warnings),
                warnings,
            )

    def test_treats_a_trace_without_a_terminal_event_as_partial(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            trace_path = Path(temporary_directory) / "run_1.trace.jsonl"
            trace_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "event_type": "run_started",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            metrics, warnings = analyze_trace(trace_path)

            self.assertEqual(metrics["trace_status"], "partial")
            self.assertEqual(metrics["trace_invalid_json_line_count"], 0)
            self.assertTrue(
                any("no run_finished event" in warning for warning in warnings),
                warnings,
            )

    def test_replaces_a_non_finite_duration_and_marks_the_trace_partial(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            trace_path = Path(temporary_directory) / "run_1.trace.jsonl"
            write_trace(
                trace_path,
                [
                    {"event_type": "run_started"},
                    {
                        "event_type": "agent_call",
                        "attempt": 1,
                        "status": "success",
                        "duration_ms": "NaN",
                    },
                    {"event_type": "run_finished", "status": "success"},
                ],
            )

            metrics, warnings = analyze_trace(trace_path)

            self.assertEqual(metrics["trace_status"], "partial")
            self.assertEqual(metrics["trace_invalid_json_line_count"], 0)
            self.assertEqual(metrics["total_call_duration_ms"], 0.0)
            self.assertTrue(any("non-finite duration_ms" in warning for warning in warnings), warnings)

    def test_trace_metric_preview_can_limit_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            trace_path = Path(temporary_directory) / "run_1.trace.jsonl"
            write_trace(
                trace_path,
                [
                    {"event_type": "run_started"},
                    {
                        "event_type": "agent_call",
                        "attempt": 1,
                        "status": "success",
                        "duration_ms": 25,
                    },
                    {"event_type": "run_finished", "status": "success"},
                ],
            )

            metrics, warnings = analyze_trace(trace_path, max_events=1)

            self.assertEqual(metrics["trace_status"], "partial")
            self.assertEqual(metrics["trace_event_count"], 1)
            self.assertTrue(any("1 valid events" in warning for warning in warnings), warnings)

    def test_trace_metric_preview_can_limit_a_single_large_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            trace_path = Path(temporary_directory) / "run_1.trace.jsonl"
            trace_path.write_bytes(b"{" + (b"x" * 100) + b"}\n")

            metrics, warnings = analyze_trace(trace_path, max_bytes=16)

            self.assertEqual(metrics["trace_status"], "partial")
            self.assertEqual(metrics["trace_event_count"], 0)
            self.assertTrue(any("16 bytes" in warning for warning in warnings), warnings)

    def test_rejects_pair_with_conflicting_raw_model_names_in_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            outputs_dir = workspace / "outputs"
            direct_path = (
                outputs_dir / "demo" / "direct" / "openai" / "model_x" / "zero_shot" / "run_1.csv"
            )
            agent_path = (
                outputs_dir / "demo" / "agent" / "openai" / "model_x" / "zero_shot" / "run_1.csv"
            )
            write_decomposition(
                direct_path,
                [("Catalog Service", "Manages the item catalog.", "")],
            )
            write_decomposition(
                agent_path,
                [("Catalog Service", "Manages the item catalog.", "")],
            )
            write_metadata(
                outputs_dir / "metadata.csv",
                [
                    metadata_row("direct", "model/x", direct_path),
                    metadata_row("agent", "model_x", agent_path),
                ],
            )

            run_comparison(outputs_dir=outputs_dir, comparison_dir=workspace / "comparison")

            pairing_rows = read_csv(workspace / "comparison" / "pairing_report.csv")
            self.assertEqual(pairing_rows[0]["pair_status"], "ambiguous_model_identity")
            self.assertEqual(
                read_csv(workspace / "comparison" / "approach_metric_summary.csv"),
                [],
            )
            self.assertEqual(
                read_csv(workspace / "comparison" / "stability_by_approach.csv"),
                [],
            )

    def test_rejects_metadata_artifact_path_outside_selected_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            outputs_dir = workspace / "outputs"
            external_csv = workspace / "external" / "run_1.csv"
            write_decomposition(
                external_csv,
                [("Catalog Service", "Manages the item catalog.", "")],
            )
            write_metadata(
                outputs_dir / "metadata.csv",
                [metadata_row("direct", "model-x", external_csv)],
            )

            result = run_comparison(
                outputs_dir=outputs_dir,
                comparison_dir=workspace / "comparison",
            )
            issue_rows = read_csv(workspace / "comparison" / "comparison_issues.csv")

            self.assertEqual(result.discovered_run_count, 0)
            self.assertEqual(result.architecture_run_count, 0)
            self.assertTrue(
                any(row["issue_type"] == "invalid_metadata_row" for row in issue_rows),
                issue_rows,
            )


def write_decomposition(path: Path, rows: list[tuple[str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["microservice_name", "responsibility", "communicates_with"],
        )
        writer.writeheader()
        for service_name, responsibility, communicates_with in rows:
            writer.writerow(
                {
                    "microservice_name": service_name,
                    "responsibility": responsibility,
                    "communicates_with": communicates_with,
                }
            )


def write_trace(path: Path, events: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def write_metadata(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def metadata_row(approach: str, model_name: str, output_path: Path) -> dict[str, str]:
    return {
        "project_name": "demo",
        "approach": approach,
        "provider": "openai",
        "model": model_name,
        "prompt_template": "zero_shot",
        "run_number": "1",
        "output_path": output_path.as_posix(),
        "trace_path": "",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "status": "success",
        "error": "",
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
