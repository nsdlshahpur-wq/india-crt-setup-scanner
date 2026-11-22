#!/usr/bin/env python3
"""BSE 5-minute intraday ORB scanner using the BSE .BO Yahoo symbol suffix."""
import argparse
import datetime as dt
import json
import os
import sys
sys.path.insert(0,os.path.dirname(__file__))
import bse
import intraday as common

def analyze_bse_intraday(symbol,bars,now=None,volume_multiple=1.5):
    now=now or dt.datetime.now(bse.IST)
    bars=common._completed_today(bars,now)
    orb=bse.india.analyze_opening_range(bars,now=now,range_minutes=15)
    vols=[float(row.get("volume") or 0) for row in bars]
    baseline=sorted(vols[:-1]) if len(vols)>1 else []
    median=baseline[len(baseline)//2] if baseline else 0
    ratio=(vols[-1]/median) if median>0 and vols else None
    return {"exchange":"BSE","symbol":symbol,"ticker":bse.bse_ticker(symbol),
      "sector":common.SECTORS.get(symbol,"Other"),"as_of":now.isoformat(),
      "status":"ok" if bars else "no_completed_bars","completed_bars":len(bars),"orb":orb,
      "last_close":bars[-1].get("close") if bars else None,"volume_multiple":round(ratio,2) if ratio is not None else None,
      "volume_confirmed":ratio is not None and ratio>=volume_multiple,
      "paper_watch":bool(orb.get("signal")) and ratio is not None and ratio>=volume_multiple,
      "data_note":"Yahoo Finance BSE intraday coverage may be unavailable or delayed; verify before use."}

def main(argv=None):
    parser=argparse.ArgumentParser(description="BSE intraday ORB scanner (paper-only)")
    group=parser.add_mutually_exclusive_group(required=True);group.add_argument("--symbols");group.add_argument("--universe")
    parser.add_argument("--output");parser.add_argument("--volume-multiple",type=float,default=1.5)
    args=parser.parse_args(argv)
    symbols=[x.strip().upper() for x in args.symbols.split(",") if x.strip()] if args.symbols else bse.load_bse_universe(args.universe)
    now=dt.datetime.now(bse.IST);results=[];errors=[]
    for symbol in dict.fromkeys(symbols):
        try:results.append(analyze_bse_intraday(symbol,bse.fetch_bse_chart(symbol,"5m","5d"),now,args.volume_multiple))
        except Exception as exc:errors.append({"exchange":"BSE","symbol":symbol,"error":str(exc)})
    payload={"market":"BSE","exchange":"BSE","mode":"paper_only","as_of":now.isoformat(),
      "results":results,"errors":errors,"signals":[row for row in results if row["paper_watch"]]}
    rendered=json.dumps(payload,indent=2)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)),exist_ok=True)
        with open(args.output,"w",encoding="utf-8") as handle:handle.write(rendered+"\n")
    print("BSE intraday scanned:",len(results),"signals:",len(payload["signals"]),"errors:",len(errors))
    print(rendered if not args.output else "Saved: "+args.output)
    return 0 if results else 1
if __name__=="__main__":raise SystemExit(main())
