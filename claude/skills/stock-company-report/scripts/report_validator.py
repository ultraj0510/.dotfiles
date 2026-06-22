"""Validate analysis.json and extract typed fields for report generation."""
from dataclasses import dataclass, field

REQUIRED_KEYS = ["schema_version", "run_id", "ticker", "company_name", "as_of", "status", "rating", "expected_return", "confidence"]

def validate_for_report(analysis):
    errors = []
    if not isinstance(analysis, dict):
        return ["analysis must be a dict"]
    for key in REQUIRED_KEYS:
        if key not in analysis:
            errors.append(f"Missing required key: {key}")
    if analysis.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")
    rating = analysis.get("rating", {})
    if isinstance(rating, dict) and rating.get("final") not in ("BUY", "HOLD", "SELL", "SHORT", "NOT_RATED"):
        errors.append(f"Invalid rating: {rating.get('final')}")
    return errors


@dataclass
class ReportSections:
    ticker: str = ""
    company_name: str = ""
    as_of: str = ""
    status: str = ""
    run_id: str = ""
    final_rating: str = "NOT_RATED"
    pm_proposal: str = ""
    adjusted: bool = False
    adjustment_reasons: list = field(default_factory=list)
    provisional: bool = False
    provisional_reasons: list = field(default_factory=list)
    short_eligible: bool = False
    current_price: float | None = None
    expected_price: float | None = None
    expected_return: float | None = None
    scenario_prices: dict = field(default_factory=dict)
    confidence_level: str = "Low"
    confidence_score: int = 0
    confidence_components: dict = field(default_factory=dict)
    scenarios: list = field(default_factory=list)
    catalysts: list = field(default_factory=list)
    disconfirmers: list = field(default_factory=list)
    unknowns: list = field(default_factory=list)
    analyst_reports: dict = field(default_factory=dict)
    debate: dict = field(default_factory=dict)
    investment_thesis: str = ""
    evidence_pack_sha256: str = ""
    model_id: str = "unknown"
    data_quality_complete: bool = False
    monitoring_triggers: list = field(default_factory=list)
    topix_comparison: dict = field(default_factory=dict)


def extract_sections(analysis):
    r = analysis.get("rating", {})
    er = analysis.get("expected_return", {})
    cf = analysis.get("confidence", {})
    return ReportSections(
        ticker=analysis.get("ticker", ""),
        company_name=analysis.get("company_name", ""),
        as_of=analysis.get("as_of", ""),
        status=analysis.get("status", ""),
        run_id=analysis.get("run_id", ""),
        final_rating=r.get("final", "NOT_RATED"),
        pm_proposal=r.get("portfolio_manager_proposal", ""),
        adjusted=r.get("adjusted", False),
        adjustment_reasons=r.get("adjustment_reasons", []),
        provisional=r.get("provisional", False),
        provisional_reasons=r.get("provisional_reasons", []),
        short_eligible=r.get("short_eligible", False),
        current_price=er.get("current_price"),
        expected_price=er.get("expected_price"),
        expected_return=er.get("expected_return"),
        scenario_prices=er.get("scenario_prices", {}),
        confidence_level=cf.get("level", "Low"),
        confidence_score=cf.get("score", 0),
        confidence_components=cf.get("components", {}),
        scenarios=analysis.get("scenarios", []),
        catalysts=analysis.get("catalysts", []),
        disconfirmers=analysis.get("disconfirmers", []),
        unknowns=analysis.get("unknowns", []),
        analyst_reports=analysis.get("analyst_reports", {}),
        debate=analysis.get("debate", {}),
        investment_thesis=analysis.get("investment_thesis", ""),
        evidence_pack_sha256=analysis.get("evidence_pack_sha256", ""),
        model_id=analysis.get("run_manifest_ref", "unknown"),
        data_quality_complete=analysis.get("data_quality", {}).get("coverage_complete", False) if isinstance(analysis.get("data_quality"), dict) else False,
        monitoring_triggers=analysis.get("monitoring_triggers", []),
        topix_comparison=analysis.get("topix_comparison", {}),
    )
