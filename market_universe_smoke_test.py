"""Optional exchange-universe coverage smoke test."""
from __future__ import annotations

from universe import get_nse_equity_universe, get_nse_sme_universe, get_bse_equity_universe, _index_rows


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

    if len(nse) < 1000:
        print("WARNING: NSE EQ universe is smaller than expected.")
        return 1
    if len(sme) < 10:
        print("WARNING: NSE SME universe is unexpectedly small.")
        return 1
    if len(bse) < 100:
        print("WARNING: BSE universe is unexpectedly small; fallback may be partial.")
        return 1
    print("EXCHANGE UNIVERSE SMOKE TEST PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
