from __future__ import annotations

import csv
from pathlib import Path


class MetadataWriter:
    def __init__(self, metadata_path: Path) -> None:
        self.metadata_path = metadata_path
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)

    def append_row(
        self,
        *,
        project_name: str,
        provider: str,
        model: str,
        prompt_template: str,
        run_number: int,
        output_path: str,
        timestamp: str,
        status: str,
        error: str,
    ) -> None:
        file_exists = self.metadata_path.exists()
        with self.metadata_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "project_name",
                    "provider",
                    "model",
                    "prompt_template",
                    "run_number",
                    "output_path",
                    "timestamp",
                    "status",
                    "error",
                ],
            )
            if not file_exists:
                writer.writeheader()
            writer.writerow(
                {
                    "project_name": project_name,
                    "provider": provider,
                    "model": model,
                    "prompt_template": prompt_template,
                    "run_number": run_number,
                    "output_path": output_path,
                    "timestamp": timestamp,
                    "status": status,
                    "error": error,
                }
            )
