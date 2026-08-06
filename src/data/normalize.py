import pandas as pd


def normalize_ohlcv(df: pd.DataFrame, symbol: str, source: str) -> pd.DataFrame:
    # yfinance returns timestamps as the DataFrame index - hoist it into a column.
    if "date" not in df.columns and isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
    col_map = {
        "Date": "date",
        "Datetime": "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
        "date": "date",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    required = ["date", "open", "high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            df[col] = 0
    df["symbol"] = symbol
    df["source"] = source
    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    # Drop timezone info so comparisons and epoch conversions stay consistent.
    if getattr(df["date"].dt, "tz", None) is not None:
        df["date"] = df["date"].dt.tz_localize(None)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # yfinance occasionally appends a junk row whose date fails to parse and
    # lands on the epoch (1970). Drop anything before the modern era outright.
    df = df[df["date"] > pd.Timestamp("1975-01-01")]
    return df[required + ["symbol", "source"]].dropna(subset=["close"])


def normalize_polymarket(data: dict) -> pd.DataFrame:
    rows = []
    for market in data.get("markets", []):
        rows.append(
            {
                "date": market.get("end_date_iso", ""),
                "open": market.get("outcome_prices", [0, 0])[0]
                if market.get("outcome_prices")
                else 0,
                "high": 0,
                "low": 0,
                "close": market.get("outcome_prices", [0, 0])[0]
                if market.get("outcome_prices")
                else 0,
                "volume": market.get("volume", 0),
                "symbol": market.get("question", "unknown")[:20],
                "source": "polymarket",
            }
        )
    return pd.DataFrame(rows)


def normalize_solana_token(data: dict) -> pd.DataFrame:
    price = data.get("price", 0)
    return pd.DataFrame(
        [
            {
                "date": pd.Timestamp.now(),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": data.get("volume", 0),
                "symbol": data.get("symbol", "unknown"),
                "source": "solana",
            }
        ]
    )
