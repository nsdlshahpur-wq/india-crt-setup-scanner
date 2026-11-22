#!/usr/bin/env python3
"""Exchange-aware event-based paper portfolio. No broker or live order execution."""
import argparse
import datetime as dt
import json
import os

def _exchange(value):
    value=(value or "NSE").upper()
    if value not in ("NSE","BSE"):raise ValueError("exchange must be NSE or BSE")
    return value

def _key(exchange,symbol):
    return _exchange(exchange)+":"+symbol.strip().upper()

def _load(path):
    if not os.path.exists(path):return {"cash":0.0,"events":[]}
    with open(path,encoding="utf-8") as handle:data=json.load(handle)
    if not isinstance(data,dict) or not isinstance(data.get("events"),list):raise ValueError("Invalid paper portfolio")
    return data

def _save(path,data):
    os.makedirs(os.path.dirname(os.path.abspath(path)),exist_ok=True);tmp=path+".tmp"
    with open(tmp,"w",encoding="utf-8") as handle:json.dump(data,handle,indent=2);handle.write("\n")
    os.replace(tmp,path)

def positions(data):
    live={}
    for event in data["events"]:
        exchange=_exchange(event.get("exchange","NSE"));symbol=event["symbol"].strip().upper();key=_key(exchange,symbol)
        if event["event"]=="OPEN":live[key]=dict(event)
        elif event["event"]=="CLOSE":live.pop(key,None)
    return live

def open_position(path,symbol,qty,entry,stop,fee=0,exchange="NSE"):
    exchange=_exchange(exchange);symbol=symbol.strip().upper()
    if not symbol or qty<=0 or entry<=0 or stop<=0 or stop>=entry or fee<0:raise ValueError("Invalid long paper position")
    data=_load(path);key=_key(exchange,symbol)
    if key in positions(data):raise ValueError("Position already open for "+key)
    if qty*entry+fee>data["cash"] and data["cash"]>0:raise ValueError("Insufficient paper cash")
    event={"event":"OPEN","exchange":exchange,"symbol":symbol,"qty":int(qty),"entry":float(entry),
      "stop":float(stop),"fee":float(fee),"time":dt.datetime.now(dt.timezone.utc).isoformat()}
    data["events"].append(event);_save(path,data);return event

def close_position(path,symbol,exit_price,fee=0,exchange="NSE"):
    exchange=_exchange(exchange);symbol=symbol.strip().upper();data=_load(path);key=_key(exchange,symbol)
    live=positions(data)
    if key not in live:raise ValueError("No open position for "+key)
    if exit_price<=0 or fee<0:raise ValueError("Invalid exit price/fee")
    pos=live[key];gross=(exit_price-pos["entry"])*pos["qty"];net=gross-pos.get("fee",0)-fee
    event={"event":"CLOSE","exchange":exchange,"symbol":symbol,"qty":pos["qty"],"entry":pos["entry"],
      "exit":float(exit_price),"gross_pnl":round(gross,2),"net_pnl":round(net,2),"fee":float(fee),
      "time":dt.datetime.now(dt.timezone.utc).isoformat()}
    data["events"].append(event);_save(path,data);return event

def mark_portfolio(path,prices):
    data=_load(path);live=positions(data);rows=[];unrealized=0
    for key,pos in live.items():
        mark_value=prices.get(key,prices.get(pos["symbol"]))
        if mark_value is None:continue
        mark=float(mark_value);pnl=(mark-pos["entry"])*pos["qty"]-pos.get("fee",0);unrealized+=pnl
        rows.append({"exchange":pos.get("exchange","NSE"),"symbol":pos["symbol"],"qty":pos["qty"],
          "entry":pos["entry"],"mark":mark,"stop":pos["stop"],"unrealized_pnl":round(pnl,2),
          "stop_breached":mark<=pos["stop"]})
    closed=[event for event in data["events"] if event["event"]=="CLOSE"]
    realized=sum(event["net_pnl"] for event in closed)
    return {"mode":"paper_only","open_positions":rows,"realized_pnl":round(realized,2),
      "unrealized_pnl":round(unrealized,2),"total_pnl":round(realized+unrealized,2),
      "stop_alerts":[{"exchange":row["exchange"],"symbol":row["symbol"]} for row in rows if row["stop_breached"]],
      "note":"Marks are user-supplied; this function does not execute stop orders."}

def main(argv=None):
    parser=argparse.ArgumentParser(description="Exchange-aware NSE/BSE paper portfolio")
    parser.add_argument("--ledger",default="trader/paper-portfolio.json")
    sub=parser.add_subparsers(dest="cmd",required=True)
    op=sub.add_parser("open");op.add_argument("--symbol",required=True);op.add_argument("--exchange",choices=("NSE","BSE"),default="NSE")
    op.add_argument("--qty",type=int,required=True);op.add_argument("--entry",type=float,required=True);op.add_argument("--stop",type=float,required=True);op.add_argument("--fee",type=float,default=0)
    cl=sub.add_parser("close");cl.add_argument("--symbol",required=True);cl.add_argument("--exchange",choices=("NSE","BSE"),default="NSE");cl.add_argument("--price",type=float,required=True);cl.add_argument("--fee",type=float,default=0)
    mk=sub.add_parser("mark");mk.add_argument("--prices",required=True,help="JSON map keyed by NSE:SYMBOL or BSE:SYMBOL; plain symbol remains NSE-compatible")
    args=parser.parse_args(argv)
    if args.cmd=="open":result=open_position(args.ledger,args.symbol,args.qty,args.entry,args.stop,args.fee,args.exchange)
    elif args.cmd=="close":result=close_position(args.ledger,args.symbol,args.price,args.fee,args.exchange)
    else:
        with open(args.prices,encoding="utf-8") as handle:prices=json.load(handle)
        result=mark_portfolio(args.ledger,prices)
    print(json.dumps(result,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
