#!/usr/bin/env python3
"""Conservative exchange-aware position sizing and local paper ledger. Never calls a broker."""
import argparse
import datetime as dt
import json
import math
import os

def size_position(capital,entry,stop,risk_pct=0.5,max_position_pct=20.0):
    values=(capital,entry,stop,risk_pct,max_position_pct)
    if any(not math.isfinite(float(value)) for value in values):raise ValueError("All sizing inputs must be finite numbers")
    if capital<=0 or entry<=0 or stop<=0 or stop>=entry:raise ValueError("Require positive capital/prices and stop below entry for a long")
    if not 0<risk_pct<=0.5:raise ValueError("Conservative risk_pct must be > 0 and <= 0.5")
    if not 0<max_position_pct<=20:raise ValueError("Conservative max_position_pct must be > 0 and <= 20")
    risk_budget=capital*risk_pct/100.0;risk_per_share=entry-stop
    by_risk=math.floor(risk_budget/risk_per_share);by_cap=math.floor(capital*max_position_pct/100.0/entry)
    quantity=max(0,min(by_risk,by_cap))
    return {"quantity":quantity,"entry":round(float(entry),2),"stop":round(float(stop),2),
      "risk_budget":round(risk_budget,2),"risk_per_share":round(risk_per_share,2),
      "estimated_max_loss":round(quantity*risk_per_share,2),"notional":round(quantity*entry,2),
      "mode":"paper_only","warning":"Position sizing estimate only. Gaps, slippage and taxes can increase losses."}

def append_paper_record(path,record):
    os.makedirs(os.path.dirname(os.path.abspath(path)),exist_ok=True);rows=[]
    if os.path.exists(path):
        with open(path,encoding="utf-8") as handle:rows=json.load(handle)
        if not isinstance(rows,list):raise ValueError("Paper ledger must contain a JSON list")
    item=dict(record);item["recorded_at"]=dt.datetime.now(dt.timezone.utc).isoformat();item["mode"]="paper_only"
    rows.append(item);tmp=path+".tmp"
    with open(tmp,"w",encoding="utf-8") as handle:
        json.dump(rows,handle,indent=2);handle.write("\n")
    os.replace(tmp,path);return item

def main(argv=None):
    parser=argparse.ArgumentParser(description="Scanner 5.0 NSE/BSE conservative paper position sizing")
    parser.add_argument("--symbol",required=True);parser.add_argument("--exchange",choices=("NSE","BSE"),default="NSE")
    parser.add_argument("--capital",type=float,required=True);parser.add_argument("--entry",type=float,required=True)
    parser.add_argument("--stop",type=float,required=True);parser.add_argument("--risk-pct",type=float,default=0.5)
    parser.add_argument("--max-position-pct",type=float,default=20.0);parser.add_argument("--record")
    args=parser.parse_args(argv)
    plan=size_position(args.capital,args.entry,args.stop,args.risk_pct,args.max_position_pct)
    plan["symbol"]=args.symbol.strip().upper();plan["exchange"]=args.exchange
    print(json.dumps(plan,indent=2))
    if args.record:
        append_paper_record(args.record,plan)
        print("Recorded in paper ledger only; no broker order was sent.")
    return 0
if __name__=="__main__":raise SystemExit(main())
