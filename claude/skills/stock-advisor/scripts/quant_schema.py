from dataclasses import dataclass, field

ACTIONS = {"BUY", "HOLD", "REDUCE", "SELL", "NO_TRADE"}
CONFIDENCE = {"low", "moderate", "high"}
ORDER_TYPES = {"market", "limit", "none"}


@dataclass
class PositionDecision:
    position_id: str
    ticker: str
    position_type: str
    action: str
    quantity: int
    order_shares: int = 0
    reason: str = ""
    expiry_date: str | None = None
    unrealized_pnl_pct: float | None = None

    def __post_init__(self):
        if self.action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}, got {self.action!r}")
        if self.quantity < 0:
            raise ValueError("quantity must be >= 0")
        if self.order_shares < 0:
            raise ValueError("order_shares must be >= 0")
        if self.order_shares % 100 != 0:
            raise ValueError("order_shares must be a 100-share lot")
        if self.order_shares > self.quantity:
            raise ValueError("order_shares must not exceed quantity")


@dataclass
class QuantDecision:
    ticker: str
    action: str
    confidence: str = "moderate"
    expected_value_after_cost_pct: float | None = None
    p_win_shrunk: float | None = None
    avg_win_pct: float | None = None
    avg_loss_pct: float | None = None
    max_position_value: float = 0.0
    target_shares: int = 0
    order_shares: int = 0
    order_type: str = "none"
    limit_price: float | None = None
    risk_posture: str = "neutral"
    protective_stop_price: float | None = None
    portfolio_weight_pct: float | None = None
    cost_basis_weight_pct: float | None = None
    unrealized_pnl_pct: float | None = None
    downside_10pct_yen: int | None = None
    advisory_plan: dict = field(default_factory=dict)
    position_decisions: list = field(default_factory=list)
    vetoes: list[str] = field(default_factory=list)
    explanations: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}, got {self.action!r}")
        if self.confidence not in CONFIDENCE:
            raise ValueError(f"confidence must be one of {CONFIDENCE}, got {self.confidence!r}")
        if self.order_type not in ORDER_TYPES:
            raise ValueError(f"order_type must be one of {ORDER_TYPES}, got {self.order_type!r}")
        if self.action in ("SELL", "REDUCE") and self.limit_price is None:
            raise ValueError("SELL/REDUCE requires limit_price")
        if self.action == "NO_TRADE" and self.order_shares != 0:
            raise ValueError("NO_TRADE with non-zero order_shares")
        if self.target_shares < 0:
            raise ValueError("target_shares must be >= 0")
        if self.order_shares < 0:
            raise ValueError("order_shares must be >= 0")
