"""Optional exchange-universe coverage smoke test."""
from __future__ import annotations

from universe import (
    get_nse_equity_universe, get_nse_sme_universe, get_bse_equity_universe,
    _index_rows, YAHOO_INDEX_SYMBOLS,
)
from data_fetch import download_market_data


def main() -> int:
    nse = get_nse_equity_universe(force_refresh=True)
    print(f"NSE active EQ-series symbols: {len(nse):,}")
    try:
        sme = get_nse_sme_universe(force_refresh=True)
        print(f"NSE SME symbols: {len(sme):,}")
    except Exception as exc:
        print(f"NSE SME list unavailable: {exc}")
        return 1

    try:
        bse, source = get_bse_equity_universe(force_refresh=True)
        print(f"BSE equity symbols: {len(bse):,}")
        print(f"BSE source: {source}")
    except Exception as exc:
        print(f"BSE universe unavailable: {exc}")
        return 1

    indices = _index_rows()
    mapped = sum(bool(row["DataAvailable"]) for row in indices)
    print(f"Nifty/BSE equity index catalogue entries: {len(indices):,}")
    print(f"Yahoo Finance index mappings: {mapped:,}")
    print(f"Catalogue-only / unmapped index names: {len(indices) - mapped:,}")

    index_tickers = sorted(set(YAHOO_INDEX_SYMBOLS.values()))
    index_data, index_errors = download_market_data(
        index_tickers, period="3mo", batch_size=40
    )
    print(f"Yahoo Finance index OHLC returned: {len(index_data):,}/{len(index_tickers):,}")
    for ticker, reason in index_errors.items():
        print(f"INDEX DATA UNAVAILABLE {ticker}: {reason}")

    if len(nse) < 1000:
        print("WARNING: NSE EQ universe is smaller than expected.")
        return 1
    if len(sme) < 10:
        print("WARNING: NSE SME universe is unexpectedly small.")
        return 1
    if len(bse) < 100:
        print("WARNING: BSE universe is unexpectedly small; fallback may be partial.")
        return 1
    if not index_data:
        print("WARNING: No mapped index series returned OHLC data.")
        return 1
    print("EXCHANGE UNIVERSE AND INDEX DATA SMOKE TEST PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
