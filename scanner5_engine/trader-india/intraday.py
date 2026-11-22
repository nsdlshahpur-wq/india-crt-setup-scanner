#!/usr/bin/env python3
"""NSE intraday scanner: completed 5-minute bars, ORB and volume confirmation."""
import argparse
import csv
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from india import IST, fetch_chart, analyze_opening_range

# Curated sector tags; extend through a CSV with symbol,sector columns.
SECTORS = {
 "RELIANCE":"Energy","ONGC":"Energy","COALINDIA":"Energy","NTPC":"Utilities","POWERGRID":"Utilities",
 "TCS":"IT","INFY":"IT","WIPRO":"IT","HCLTECH":"IT","TECHM":"IT",
 "HDFCBANK":"Banks","ICICIBANK":"Banks","SBIN":"Banks","AXISBANK":"Banks","KOTAKBANK":"Banks",
 "BHARTIARTL":"Telecom","ITC":"FMCG","HINDUNILVR":"FMCG","TITAN":"Consumer","MARUTI":"Auto",
 "TATAMOTORS":"Auto","BAJFINANCE":"Financials","BAJAJFINSV":"Financials","SUNPHARMA":"Pharma",
 "CIPLA":"Pharma","DRREDDY":"Pharma","LT":"Industrials","ULTRACEMCO":"Materials","TATASTEEL":"Materials"
}

def _completed_today(bars, now):
    out=[]
    for b in bars:
        stamp=dt.datetime.fromisoformat(b["time"].replace("Z","+00:00"))
        if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=IST)
        local=stamp.astimezone(IST)
        if local.date()==now.date() and (local+dt.timedelta(minutes=5))<=now:
            out.append(dict(b))
    return sorted(out,key=lambda x:x["time"])

def analyze_intraday(symbol,bars,now=None,volume_multiple=1.5):
    now=now or dt.datetime.now(IST)
    bars=_completed_today(bars,now)
    orb=analyze_opening_range(bars,now=now,range_minutes=15)
    vols=[float(b.get("volume") or 0) for b in bars]
    baseline=sorted(vols[:-1]) if len(vols)>1 else []
    median=baseline[len(baseline)//2] if baseline else 0
    last_vol=vols[-1] if vols else 0
    ratio=(last_vol/median) if median>0 else None
    confirmed=bool(orb.get("signal")) and ratio is not None and ratio>=volume_multiple
    return {"symbol":symbol,"sector":SECTORS.get(symbol,"Other"),"as_of":now.isoformat(),
      "status":"ok" if bars else "no_completed_bars","completed_bars":len(bars),
      "orb":orb,"last_close":bars[-1].get("close") if bars else None,
      "last_volume":last_vol,"median_prior_bar_volume":median or None,
      "volume_multiple":round(ratio,2) if ratio is not None else None,
      "volume_confirmed":ratio is not None and ratio>=volume_multiple,
      "paper_watch":confirmed,
      "rule":"15-minute ORB close above range high AND latest completed 5m volume >= configured multiple of prior-bar median; not a trade recommendation."}

def sector_strength(daily_results):
    groups={}
    for row in daily_results:
        sector=SECTORS.get(row.get("symbol"),"Other")
        change=row.get("change_pct")
        if change is not None: groups.setdefault(sector,[]).append(float(change))
    return [{"sector":k,"members":len(v),"average_change_pct":round(sum(v)/len(v),2)}
            for k,v in sorted(groups.items(),key=lambda kv:sum(kv[1])/len(kv[1]),reverse=True)]

def main(argv=None):
    p=argparse.ArgumentParser(description="NSE intraday ORB scanner (paper-only)")
    g=p.add_mutually_exclusive_group(required=True); g.add_argument("--symbols"); g.add_argument("--universe")
    p.add_argument("--output"); p.add_argument("--volume-multiple",type=float,default=1.5)
    a=p.parse_args(argv)
    symbols=[s.strip().upper() for s in a.symbols.split(",") if s.strip()] if a.symbols else []
    if a.universe:
        with open(a.universe,encoding="utf-8-sig",newline="") as f: symbols=[r["symbol"].strip().upper() for r in csv.DictReader(f) if r.get("symbol")]
    now=dt.datetime.now(IST); results=[]; errors=[]
    for symbol in dict.fromkeys(symbols):
        try: results.append(analyze_intraday(symbol,fetch_chart(symbol,interval="5m",range_="5d"),now,a.volume_multiple))
        except Exception as e: errors.append({"symbol":symbol,"error":str(e)})
    payload={"market":"NSE","mode":"paper_only","as_of":now.isoformat(),"results":results,"errors":errors,
      "signals":[r for r in results if r["paper_watch"]],"data_warning":"Yahoo Finance intraday feed is unofficial and may be delayed/incomplete."}
    rendered=json.dumps(payload,indent=2)
    if a.output:
        os.makedirs(os.path.dirname(os.path.abspath(a.output)),exist_ok=True)
        with open(a.output,"w",encoding="utf-8") as f:f.write(rendered+"\n")
    print("Intraday scanned:",len(results),"signals:",len(payload["signals"]),"errors:",len(errors))
    print(rendered if not a.output else "Saved: "+a.output)
    return 0 if results else 1
if __name__=="__main__": raise SystemExit(main())
