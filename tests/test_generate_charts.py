from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.evaluation.generate_charts import generate_charts


class GenerateChartsTest(unittest.TestCase):
    def test_generate_charts_creates_dashboard_and_svgs(self) -> None:
        metrics_by_run_df = pd.DataFrame(
            [
                {
                    "project_name": "pet-clinic",
                    "provider": "openai",
                    "model_name": "gpt-test",
                    "prompt_template": "zero_shot",
                    "run_id": "run_1",
                    "metric_name": "number_of_microservices",
                    "metric_value": 3,
                    "metric_category": "basic",
                    "status": "calculated",
                    "formula_version": "v1",
                    "notes": "",
                },
                {
                    "project_name": "pet-clinic",
                    "provider": "anthropic",
                    "model_name": "claude-test",
                    "prompt_template": "few_shot",
                    "run_id": "run_1",
                    "metric_name": "number_of_microservices",
                    "metric_value": 4,
                    "metric_category": "basic",
                    "status": "calculated",
                    "formula_version": "v1",
                    "notes": "",
                },
            ]
        )
        applicability_df = pd.DataFrame(
            [
                {
                    "project_name": "pet-clinic",
                    "metric_name": "number_of_microservices",
                    "metric_category": "basic",
                    "required_data": "llm_output_services",
                    "available_data": "llm_output_services",
                    "status": "calculated",
                    "notes": "",
                },
                {
                    "project_name": "pet-clinic",
                    "metric_name": "afferent_coupling_ac",
                    "metric_category": "coupling",
                    "required_data": "component_to_service_mapping;structural_dependency_graph",
                    "available_data": "structural_dependency_graph",
                    "status": "missing_required_data",
                    "notes": "Missing mapping.",
                },
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            charts_dir = Path(tmpdir) / "charts"
            generated_files = generate_charts(
                metrics_by_run_df=metrics_by_run_df,
                applicability_df=applicability_df,
                charts_dir=charts_dir,
                core_metrics=["number_of_microservices"],
            )

            self.assertTrue((charts_dir / "index.html").exists())
            self.assertTrue((charts_dir / "run_metric_number_of_microservices.svg").exists())
            self.assertTrue((charts_dir / "provider_summary_number_of_microservices.svg").exists())
            self.assertTrue((charts_dir / "prompt_summary_number_of_microservices.svg").exists())
            self.assertTrue((charts_dir / "applicability_by_metric.svg").exists())
            self.assertGreaterEqual(len(generated_files), 5)


if __name__ == "__main__":
    unittest.main()
