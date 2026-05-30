"""Signal reliability: Bayesian shrinkage, expected value, veto classification."""


def shrink_win_probability(wins: int, losses: int, prior_p: float = 0.5, prior_n: int = 10) -> float:
    """Bayesian shrinkage: pull observed win rate toward prior_p using prior_n pseudo-observations.

    Returns 0.5 when wins + losses == 0.
    """
    if wins + losses == 0:
        return 0.5
    return (wins + prior_p * prior_n) / (wins + losses + prior_n)


def expected_value_after_cost_pct(
    p_win: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    round_trip_cost_pct: float,
) -> float:
    """Expected value after transaction costs. avg_loss_pct is negative."""
    return p_win * avg_win_pct + (1 - p_win) * avg_loss_pct - round_trip_cost_pct


def reliability_vetoes(
    sample_count: int,
    p_win_shrunk: float,
    ev_after_cost_pct: float,
    walk_forward: dict | None = None,
) -> list[str]:
    """Return list of reliability-related veto strings."""
    vetoes = []
    if sample_count < 5:
        vetoes.append("low_sample")
    if ev_after_cost_pct <= 0:
        vetoes.append("negative_ev")
    if walk_forward:
        sharpe_is = walk_forward.get("sharpe_is")
        sharpe_oos = walk_forward.get("sharpe_oos")
        if sharpe_oos is not None and sharpe_oos < 0:
            vetoes.append("negative_walk_forward")
        if sharpe_is is not None and sharpe_oos is not None and sharpe_is > 0:
            drop = (sharpe_is - sharpe_oos) / sharpe_is
            if drop > 0.5:
                vetoes.append("overfit_walk_forward")
    return vetoes
