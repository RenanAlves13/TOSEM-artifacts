from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.evaluation.cohesion_metrics import compute_relational_cohesion_rc
from src.evaluation.coupling_metrics import (
    compute_afferent_coupling_ac,
    compute_efferent_coupling_ec,
)
from src.evaluation.evaluate_all import build_applicability_rows
from src.evaluation.graph_metrics import (
    compute_run_level_graph_metrics,
    compute_service_level_graph_metrics,
)
from src.evaluation.metric_models import EvaluationContext, MetricDefinition, ProjectArtifacts
from src.evaluation.result_loader import RunDescriptor, load_decomposition_result, parse_communicates_with


class EvaluationMetricsTest(unittest.TestCase):
    def test_parse_communicates_with_handles_empty_and_multiple_values(self) -> None:
        self.assertEqual(parse_communicates_with(""), [])
        self.assertEqual(parse_communicates_with(None), [])
        self.assertEqual(parse_communicates_with("None"), [])
        self.assertEqual(
            parse_communicates_with("Payment Service; Customer Service ;Inventory Service"),
            ["Payment Service", "Customer Service", "Inventory Service"],
        )

    def test_load_decomposition_result_and_graph_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "run_1.csv"
            csv_path.write_text(
                "microservice_name,responsibility,communicates_with\n"
                "Order Service,Handles orders,Payment Service;Customer Service\n"
                "Payment Service,Handles payments,\n"
                "Customer Service,Handles customers,\n",
                encoding="utf-8",
            )

            descriptor = RunDescriptor(
                project_name="bookstore",
                provider="openai",
                model_name="gpt-test",
                prompt_template="zero_shot",
                run_id="run_1",
                csv_path=csv_path,
            )
            result = load_decomposition_result(descriptor)
            artifacts = ProjectArtifacts(
                project_name="bookstore",
                system_dir=Path(tmpdir),
                static_analysis_dir=None,
                available_data=set(),
            )
            context = EvaluationContext(
                result=result,
                artifacts=artifacts,
                min_service_size=5,
                max_service_size=20,
            )

            run_metrics = {record.metric_name: record for record in compute_run_level_graph_metrics(context)}
            self.assertEqual(run_metrics["number_of_microservices"].metric_value, 3)
            self.assertEqual(run_metrics["number_of_communications"].metric_value, 2)
            self.assertAlmostEqual(run_metrics["communication_density"].metric_value, 2 / 6, places=6)
            self.assertEqual(run_metrics["isolated_services_count"].metric_value, 0)

            service_metrics = compute_service_level_graph_metrics(context)
            outgoing = {
                record.microservice_name: record.metric_value
                for record in service_metrics
                if record.metric_name == "outgoing_communications"
            }
            incoming = {
                record.microservice_name: record.metric_value
                for record in service_metrics
                if record.metric_name == "incoming_communications"
            }
            self.assertEqual(outgoing["Order Service"], 2)
            self.assertEqual(incoming["Payment Service"], 1)
            self.assertEqual(incoming["Customer Service"], 1)

    def test_identifies_isolated_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "run_1.csv"
            csv_path.write_text(
                "microservice_name,responsibility,communicates_with\n"
                "A,alpha,\n"
                "B,beta,C\n"
                "C,gamma,\n"
                "D,delta,\n",
                encoding="utf-8",
            )
            descriptor = RunDescriptor(
                project_name="demo",
                provider="openai",
                model_name="gpt-test",
                prompt_template="zero_shot",
                run_id="run_1",
                csv_path=csv_path,
            )
            result = load_decomposition_result(descriptor)
            context = EvaluationContext(
                result=result,
                artifacts=ProjectArtifacts(
                    project_name="demo",
                    system_dir=Path(tmpdir),
                    static_analysis_dir=None,
                    available_data=set(),
                ),
                min_service_size=5,
                max_service_size=20,
            )
            metrics = {record.metric_name: record for record in compute_run_level_graph_metrics(context)}
            self.assertEqual(metrics["isolated_services_count"].metric_value, 2)
            self.assertAlmostEqual(metrics["isolated_services_ratio"].metric_value, 0.5, places=6)

    def test_structural_coupling_metrics_with_mock_graph(self) -> None:
        result = build_mock_result()
        artifacts = ProjectArtifacts(
            project_name="demo",
            system_dir=Path("."),
            static_analysis_dir=None,
            available_data={"component_to_service_mapping", "structural_dependency_graph"},
            component_to_service_mapping_df=pd.DataFrame(
                [
                    {"component_name": "A1", "microservice_name": "ServiceA"},
                    {"component_name": "A2", "microservice_name": "ServiceA"},
                    {"component_name": "B1", "microservice_name": "ServiceB"},
                    {"component_name": "B2", "microservice_name": "ServiceB"},
                ]
            ),
            structural_dependencies_df=pd.DataFrame(
                [
                    {"source": "A1", "target": "A2", "count": 1},
                    {"source": "A1", "target": "B1", "count": 1},
                    {"source": "B2", "target": "A2", "count": 1},
                ]
            ),
        )
        context = EvaluationContext(result=result, artifacts=artifacts, min_service_size=5, max_service_size=20)

        ac_record = compute_afferent_coupling_ac(context)[0]
        ec_record = compute_efferent_coupling_ec(context)[0]
        rc_record = compute_relational_cohesion_rc(context)[0]

        self.assertEqual(ac_record.status, "calculated")
        self.assertEqual(ec_record.status, "calculated")
        self.assertEqual(rc_record.status, "calculated")
        self.assertAlmostEqual(ac_record.metric_value, 1.0, places=6)
        self.assertAlmostEqual(ec_record.metric_value, 1.0, places=6)
        self.assertAlmostEqual(rc_record.metric_value, 0.5, places=6)

    def test_missing_required_data_is_reported_for_structural_metrics(self) -> None:
        result = build_mock_result()
        artifacts = ProjectArtifacts(
            project_name="demo",
            system_dir=Path("."),
            static_analysis_dir=None,
            available_data=set(),
        )
        context = EvaluationContext(result=result, artifacts=artifacts, min_service_size=5, max_service_size=20)

        ac_record = compute_afferent_coupling_ac(context)[0]
        self.assertEqual(ac_record.status, "missing_required_data")

    def test_applicability_rows_are_generated_for_real_metric_names(self) -> None:
        result = build_mock_result()
        context = EvaluationContext(
            result=result,
            artifacts=ProjectArtifacts(
                project_name="demo",
                system_dir=Path("."),
                static_analysis_dir=None,
                available_data=set(),
            ),
            min_service_size=5,
            max_service_size=20,
        )
        metric_definition = MetricDefinition(
            name="basic_run_metrics",
            category="basic",
            description="Grouped basic metrics.",
            required_data=("llm_output_services",),
            output_level="run_level",
            formula_version="v1",
            calculator=compute_run_level_graph_metrics,
        )

        applicability_rows = build_applicability_rows(
            project_name="demo",
            metric_definition=metric_definition,
            context=context,
            records=compute_run_level_graph_metrics(context),
        )
        applicability_metric_names = {row["metric_name"] for row in applicability_rows}

        self.assertIn("number_of_microservices", applicability_metric_names)
        self.assertIn("communication_density", applicability_metric_names)
        self.assertNotIn("basic_run_metrics", applicability_metric_names)


def build_mock_result():
    dataframe = pd.DataFrame(
        [
            {
                "microservice_name": "ServiceA",
                "responsibility": "Handles A behavior",
                "communicates_with": "ServiceB",
            },
            {
                "microservice_name": "ServiceB",
                "responsibility": "Handles B behavior",
                "communicates_with": "",
            },
        ]
    )
    descriptor = RunDescriptor(
        project_name="demo",
        provider="openai",
        model_name="gpt-test",
        prompt_template="zero_shot",
        run_id="run_1",
        csv_path=Path("virtual.csv"),
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "run_1.csv"
        dataframe.to_csv(csv_path, index=False)
        descriptor = RunDescriptor(
            project_name="demo",
            provider="openai",
            model_name="gpt-test",
            prompt_template="zero_shot",
            run_id="run_1",
            csv_path=csv_path,
        )
        return load_decomposition_result(descriptor)
