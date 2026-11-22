#!/usr/bin/env python3
"""Offline F&O bhavcopy CSV normalizer and futures OI buildup classifier."""
import argparse
import csv
import json
import os

REQUIRED=("symbol","instrument","expiry","open_interest","change_in_oi","volume","close","underlying_close")
ALIASES={"symbol":["symbol","underlying","ticker"],"instrument":["instrument","instrument_type"],
 "expiry":["expiry","expiry_dt","expiry_date"],"open_interest":["open_interest","open_int","oi","openint"],
 "change_in_oi":["change_in_oi","chg_in_oi","change_oi"],"volume":["volume","contracts"],
 "close":["close","settle_pr","close_price"],"underlying_close":["underlying_close","underlying_price","underlying_value"]}

def normalize_row(row):
    low={str(k).strip().lower():v for k,v in row.items()}
    out={}
    for key in REQUIRED:
        value=next((low[a] for a in ALIASES[key] if a in low and low[a] not in (None,"")),None)
        if value is None: raise ValueError("Missing required field: "+key)
        out[key]=value
    for key in ("open_interest","change_in_oi","volume","close","underlying_close"):
        out[key]=float(str(out[key]).replace(",",""))
    previous=next((low[a] for a in ("previous_underlying_close","prev_underlying_close","prev_close") if a in low and low[a] not in (None,"")),None)
    out["previous_underlying_close"]=float(str(previous).replace(",","")) if previous is not None else None
    out["symbol"]=str(out["symbol"]).strip().upper()
    out["instrument"]=str(out["instrument"]).strip().upper()
    return out

def classify_buildup(price_change,oi_change):
    if price_change>0 and oi_change>0:return "long_buildup"
    if price_change<0 and oi_change>0:return "short_buildup"
    if price_change>0 and oi_change<0:return "short_covering"
    if price_change<0 and oi_change<0:return "long_unwinding"
    return "neutral_or_flat"

def analyze_rows(rows):
    parsed=[];errors=[]
    for n,row in enumerate(rows,2):
        try:parsed.append(normalize_row(row))
        except (ValueError,TypeError) as exc:errors.append({"row":n,"error":str(exc)})
    by_symbol={}
    for row in parsed:
        if row["instrument"] not in ("FUTSTK","FUTIDX","FUTURE","FUT"):continue
        previous=row.get("previous_underlying_close")
        change=((row["underlying_close"]/previous)-1)*100 if previous else None
        row["price_change_pct"]=round(change,2) if change is not None else None
        prior_oi=row["open_interest"]-row["change_in_oi"]
        row["oi_change_pct"]=round(row["change_in_oi"]/prior_oi*100,2) if prior_oi else None
        row["buildup"]=classify_buildup(change,row["change_in_oi"]) if change is not None else "oi_only_no_price_baseline"
        by_symbol.setdefault(row["symbol"],[]).append(row)
    return {"records_parsed":len(parsed),"futures_symbols":len(by_symbol),"symbols":by_symbol,"errors":errors,
      "note":"Price/OI buildup requires a previous underlying close. Option-chain PCR and max pain are not inferred from incomplete files."}

def main(argv=None):
    parser=argparse.ArgumentParser(description="Analyze normalized NSE F&O bhavcopy CSV")
    parser.add_argument("--csv",required=True);parser.add_argument("--output")
    args=parser.parse_args(argv)
    with open(args.csv,encoding="utf-8-sig",newline="") as handle:result=analyze_rows(list(csv.DictReader(handle)))
    rendered=json.dumps(result,indent=2)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)),exist_ok=True)
        with open(args.output,"w",encoding="utf-8") as handle:handle.write(rendered+"\n")
    print(rendered);return 0
if __name__=="__main__":raise SystemExit(main())
