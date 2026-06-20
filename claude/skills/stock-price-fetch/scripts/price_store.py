import json
import os
import tempfile
from pathlib import Path


class PriceStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path_for(self, ticker: str) -> Path:
        return self.root / ticker / "raw" / "stock-price-fetch" / "prices.json"

    def load(self, ticker: str) -> dict | None:
        path = self.path_for(ticker)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if payload.get("schema_version") != "1.0":
            return None
        if payload.get("ticker") != ticker:
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        if not isinstance(data.get("daily"), list):
            return None
        if not isinstance(data.get("intraday_1h"), list):
            return None
        return payload

    def save(self, ticker: str, payload: dict) -> Path:
        path = self.path_for(ticker)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(payload, temporary, ensure_ascii=False, indent=2, allow_nan=False)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
        return path
