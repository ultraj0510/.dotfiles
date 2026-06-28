"""Read analysis.json v2.0. Schema following is confined to this module."""
import json
from pathlib import Path


def read_analysis_v2(path: Path) -> dict:
    """Extract runner-relevant keys from analysis.json v2.0.

    Raises:
        ValueError: schema_version is not '2.0' or required keys are missing.
    """
    data = json.loads(Path(path).read_text())

    sv = data.get("schema_version")
    if sv != "2.0":
        raise ValueError(
            f"Unsupported schema_version={sv!r} in {path}, expected '2.0'"
        )

    try:
        return {
            "ticker": data["ticker"],
            "as_of": data.get("as_of"),
            "investment_rating": data["integrated"]["investment_rating"],
            "execution_posture": data["integrated"]["execution_posture"],
            "reasoning": data["integrated"]["reasoning"],
            "risk_flags": list(data["integrated"].get("risk_flags", [])),
            "fundamental_rating": data["fundamental"]["rating"],
            "technical_direction": data["technical"]["direction"],
            "technical_signal_raw": data["technical"].get("signal_raw"),
            "scenarios": data["fundamental"].get("scenarios", []),
            "investment_thesis": data["fundamental"].get("investment_thesis", ""),
            "catalysts": data["fundamental"].get("catalysts", []),
            "monitoring_triggers": data["fundamental"].get("monitoring_triggers", []),
        }
    except KeyError as e:
        raise ValueError(
            f"Missing required key {e} in analysis.json v2.0: {path}"
        ) from e
