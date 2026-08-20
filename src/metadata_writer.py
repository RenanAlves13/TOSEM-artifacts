from __future__ import annotations

import csv
from pathlib import Path


METADATA_FIELDS = [
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


class MetadataWriter:
    def __init__(self, metadata_path: Path) -> None:
        self.metadata_path = metadata_path
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self._upgrade_legacy_file()

    def append_row(
        self,
        *,
        project_name: str,
        approach: str,
        provider: str,
        model: str,
        prompt_template: str,
        run_number: int,
        output_path: str,
        trace_path: str,
        timestamp: str,
        status: str,
        error: str,
    ) -> None:
        file_exists = self.metadata_path.exists()
        with self.metadata_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=METADATA_FIELDS,
            )
            if not file_exists:
                writer.writeheader()
            writer.writerow(
                {
                    "project_name": project_name,
                    "approach": approach,
                    "provider": provider,
                    "model": model,
                    "prompt_template": prompt_template,
                    "run_number": run_number,
                    "output_path": output_path,
                    "trace_path": trace_path,
                    "timestamp": timestamp,
                    "status": status,
                    "error": error,
                }
            )

    def _upgrade_legacy_file(self) -> None:
        if not self.metadata_path.exists() or self.metadata_path.stat().st_size == 0:
            return

        with self.metadata_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames == METADATA_FIELDS:
                return
            rows = list(reader)

        temporary_path = self.metadata_path.with_suffix(".csv.tmp")
        with temporary_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=METADATA_FIELDS)
            writer.writeheader()
            for row in rows:
                upgraded = {field: row.get(field, "") for field in METADATA_FIELDS}
                upgraded["approach"] = upgraded["approach"] or "direct"
                writer.writerow(upgraded)
        temporary_path.replace(self.metadata_path)
