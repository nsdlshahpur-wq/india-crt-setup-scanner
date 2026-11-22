#!/usr/bin/env python3
"""BSE cash-equity daily scanner. Separate .BO adapter; research/paper only."""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0,os.path.dirname(__file__))
import india

IST=india.IST
def bse_ticker(symbol):
    symbol=symbol.strip().upper()
    if not symbol or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&-" for ch in symbol):
        raise ValueError("Invalid BSE scrip code/symbol: "+symbol)
    return symbol+".BO"

def fetch_bse_chart(symbol,interval="1d",range_="3mo",timeout=20):
    """Fetch BSE OHLCV from the same Yahoo Finance source via yfinance."""
    return india.fetch_yahoo_ticker(bse_ticker(symbol), interval=interval, range_=range_, timeout=timeout)


def load_bse_universe(path):
    import csv
    symbols=[]
    with open(path,encoding="utf-8-sig",newline="") as handle:
        for row in csv.DictReader(handle):
            symbol=(row.get("symbol") or "").strip().upper()
            if symbol:bse_ticker(symbol);symbols.append(symbol)
    return list(dict.fromkeys(symbols))

def scan_bse(symbols,fetcher=fetch_bse_chart,now=None):
    results=[];errors=[]
    for symbol in symbols:
        try:
            row=india.analyze_daily(symbol,fetcher(symbol),now=now)
            row["exchange"]="BSE";row["ticker"]=bse_ticker(symbol)
            results.append(row)
        except Exception as exc:errors.append({"exchange":"BSE","symbol":symbol,"error":str(exc)})
    return {"market":"BSE","exchange":"BSE","mode":"research_only","symbols_requested":len(symbols),
      "symbols_returned":len(results),"failed":len(errors),"as_of":(now or dt.datetime.now(IST)).isoformat(),
      "results":results,"errors":errors,"data_warning":"Yahoo Finance .BO mapping is unofficial; coverage, scrip-code mapping and intraday availability must be verified."}

def main(argv=None):
    parser=argparse.ArgumentParser(description="Scanner 5.0 BSE daily scanner (research/paper only)")
    group=parser.add_mutually_exclusive_group(required=True);group.add_argument("--symbols");group.add_argument("--universe")
    parser.add_argument("--offline");parser.add_argument("--output");parser.add_argument("--show",type=int,default=25)
    args=parser.parse_args(argv)
    symbols=[x.strip().upper() for x in args.symbols.split(",") if x.strip()] if args.symbols else load_bse_universe(args.universe)
    if args.offline:
        with open(args.offline,encoding="utf-8") as handle:fixture=json.load(handle)
        payload=scan_bse(symbols,fetcher=lambda symbol:fixture[symbol])
    else:payload=scan_bse(symbols)
    rendered=json.dumps(payload,indent=2,ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)),exist_ok=True)
        with open(args.output,"w",encoding="utf-8") as handle:handle.write(rendered+"\n")
    print("BSE Scanner: requested {0}, returned {1}, failed {2}".format(payload["symbols_requested"],payload["symbols_returned"],payload["failed"]))
    for row in [r for r in payload["results"] if r.get("setups")][:max(0,args.show)]:
        print("{symbol:14} {close:>10} RSI={rsi14} MA20={ma20} setups={setups}".format(**row))
    if args.output:print("Saved: "+args.output)
    return 0 if payload["symbols_returned"] else 1
if __name__=="__main__":raise SystemExit(main())
