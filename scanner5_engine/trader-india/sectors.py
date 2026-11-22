#!/usr/bin/env python3
"""Sector relative-strength snapshot for NSE and BSE sample universes."""
import argparse
import csv
import json
import os
import sys
sys.path.insert(0,os.path.dirname(__file__))
from india import fetch_chart,IST
from intraday import SECTORS
BSE_SECTORS={"500325":"Energy","532540":"IT","500180":"Banks","532174":"Banks",
 "500209":"IT","500112":"Banks","532454":"Telecom","500875":"FMCG","500510":"Industrials",
 "532215":"Banks","500247":"Banks","500696":"FMCG","500034":"Financials","532500":"Auto",
 "524715":"Pharma","500114":"Consumer","532555":"Utilities","532898":"Utilities",
 "500312":"Energy","500570":"Auto"}

def sector_snapshot(symbols,fetcher=fetch_chart,exchange="NSE"):
    mapping=BSE_SECTORS if exchange=="BSE" else SECTORS
    groups={};errors=[]
    for symbol in dict.fromkeys(s.strip().upper() for s in symbols if s.strip()):
        try:
            bars=fetcher(symbol)
            if len(bars)<2:raise ValueError("Need at least two daily bars")
            previous=float(bars[-2]["close"]);last=float(bars[-1]["close"])
            if previous<=0:raise ValueError("Invalid previous close")
            change=(last/previous-1)*100;sector=mapping.get(symbol,"Other")
            groups.setdefault(sector,[]).append({"symbol":symbol,"change_pct":round(change,2)})
        except Exception as exc:errors.append({"symbol":symbol,"error":str(exc)})
    rows=[]
    for name,members in groups.items():
        rows.append({"sector":name,"members":len(members),
          "average_change_pct":round(sum(x["change_pct"] for x in members)/len(members),2),
          "constituents":sorted(members,key=lambda x:x["change_pct"],reverse=True)})
    rows.sort(key=lambda row:row["average_change_pct"],reverse=True)
    return {"market":exchange,"as_of":IST.tzname(None),"sectors":rows,"errors":errors,
      "note":"Curated sample sector map only; this is not official index breadth or a complete sector index return."}

def main(argv=None):
    parser=argparse.ArgumentParser(description="NSE/BSE sector relative strength")
    group=parser.add_mutually_exclusive_group(required=True);group.add_argument("--symbols");group.add_argument("--universe")
    parser.add_argument("--output");parser.add_argument("--exchange",choices=("NSE","BSE"),default="NSE")
    args=parser.parse_args(argv)
    if args.symbols:symbols=args.symbols.split(",")
    else:
        with open(args.universe,encoding="utf-8-sig",newline="") as handle:
            symbols=[row["symbol"] for row in csv.DictReader(handle) if row.get("symbol")]
    if args.exchange=="BSE":
        import bse
        result=sector_snapshot(symbols,fetcher=bse.fetch_bse_chart,exchange="BSE")
    else:result=sector_snapshot(symbols,exchange="NSE")
    rendered=json.dumps(result,indent=2)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)),exist_ok=True)
        with open(args.output,"w",encoding="utf-8") as handle:handle.write(rendered+"\n")
    print(rendered);return 0
if __name__=="__main__":raise SystemExit(main())
