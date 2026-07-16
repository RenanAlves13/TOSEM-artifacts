from __future__ import annotations

import csv
from pathlib import Path

from .response_parser import MicroserviceProposal


def write_microservices_csv(
    output_path: Path,
    proposal: MicroserviceProposal,
    empty_communication_value: str = "",
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "microservice_name",
                "responsibility",
                "communicates_with",
            ],
        )
        writer.writeheader()
        for item in proposal.microservices:
            writer.writerow(
                {
                    "microservice_name": item.microservice_name,
                    "responsibility": item.responsibility,
                    "communicates_with": (
                        ";".join(item.communicates_with)
                        if item.communicates_with
                        else empty_communication_value
                    ),
                }
            )
