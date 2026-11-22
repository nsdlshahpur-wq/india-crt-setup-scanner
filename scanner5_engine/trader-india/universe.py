#!/usr/bin/env python3
"""Validate/import an NSE equity master CSV into the scanner's symbol CSV format."""
import argparse,csv,json,os,re

def import_universe(source,destination,series=("EQ",)):
    allowed={x.upper() for x in series};rows=[];seen=set();rejected=[]
    with open(source,encoding="utf-8-sig",newline="") as f:
        for n,row in enumerate(csv.DictReader(f),2):
            low={str(k).strip().lower():v for k,v in row.items()}
            symbol=(low.get("symbol") or low.get("tradingsymbol") or low.get("ticker") or "").strip().upper()
            srs=(low.get("series") or "EQ").strip().upper()
            if not symbol or not re.fullmatch(r"[A-Z0-9&-]+",symbol) or srs not in allowed:
                rejected.append({"row":n,"symbol":symbol,"series":srs,"reason":"invalid symbol or excluded series"});continue
            if symbol in seen:continue
            seen.add(symbol);rows.append({"symbol":symbol,"name":(low.get("name") or low.get("company name") or low.get("name of company") or "").strip()})
    os.makedirs(os.path.dirname(os.path.abspath(destination)),exist_ok=True)
    with open(destination,"w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=["symbol","name"]);writer.writeheader();writer.writerows(rows)
    return {"accepted":len(rows),"rejected":len(rejected),"symbols":rows,"rejected_rows":rejected,
      "note":"Input source is user-supplied. Confirm it is the latest official NSE equity master and review excluded series before scanning."}

def main(argv=None):
    p=argparse.ArgumentParser(description="Import user-downloaded NSE equity master CSV")
    p.add_argument("--input",required=True);p.add_argument("--output",default="trader-india/universe.csv");p.add_argument("--series",default="EQ")
    a=p.parse_args(argv);result=import_universe(a.input,a.output,a.series.split(","))
    print(json.dumps(result,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
