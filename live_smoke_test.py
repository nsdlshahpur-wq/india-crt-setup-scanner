"""Optional live-data smoke test for the Yahoo Finance integration.

This test is run in GitHub Actions as a separate, non-blocking job because
third-party data vendors can throttle or block automated runners.
"""
from __future__ import annotations

import sys

from data_fetch import download_market_data
from scanner import ScanConfig, scan_symbol


def main() -> int:
    symbols = ["^NSEI", "RELIANCE.NS"]
    print("Requesting one-year daily OHLC data for:", ", ".join(symbols))
    data, errors = download_market_data(symbols, period="1y", batch_size=2)
    if not data:
        print("LIVE DATA SMOKE TEST FAILED: no symbols returned data.")
        for symbol, reason in errors.items():
            print(f"  {symbol}: {reason}")
        return 1

    for symbol, frame in data.items():
        last = frame.iloc[-1]
        print(
            f"OK {symbol}: rows={len(frame)}, last_date={frame.index[-1]}, "
            f"close={float(last['Close']):.2f}"
        )
        result = scan_symbol(symbol, symbol, frame, ScanConfig())
        if result is None:
            print(f"WARNING {symbol}: OHLC received, but history was insufficient for a scan.")
        else:
            print(f"SCAN OK {symbol}: bias={result['Bias']}, stage={result['Stage']}, setup={result['Setup']}")

    for symbol, reason in errors.items():
        print(f"WARNING no data for {symbol}: {reason}")

    print("LIVE DATA SMOKE TEST PASSED: at least one real market data series was downloaded and scanned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
