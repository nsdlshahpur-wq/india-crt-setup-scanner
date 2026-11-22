#!/usr/bin/env python3
"""Offline alert rules for scanner outputs; no webhook or order execution."""
import argparse,json,os,datetime

def build_alerts(payload,min_volume_multiple=1.5):
    alerts=[]
    for row in payload.get("results",[]):
        symbol=row.get("symbol","UNKNOWN")
        if row.get("paper_watch"):alerts.append({"symbol":symbol,"type":"intraday_orb_volume_confirmed","detail":"ORB and volume rule matched"})
        if row.get("conservative_watch"):alerts.append({"symbol":symbol,"type":"daily_setup_watch","detail":",".join(row.get("setups",[]))})
        if row.get("volume_multiple") is not None and row["volume_multiple"]>=min_volume_multiple and not row.get("paper_watch"):
            alerts.append({"symbol":symbol,"type":"high_volume_watch","detail":"Volume multiple threshold met; other confirmation missing"})
    return {"generated_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"mode":"paper_only","alerts":alerts,
      "note":"Informational local alerts only. No push notification, broker order or automated execution."}

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--output",default="trader/india-alerts.json");p.add_argument("--min-volume-multiple",type=float,default=1.5)
    a=p.parse_args(argv)
    with open(a.input,encoding="utf-8") as f:payload=json.load(f)
    result=build_alerts(payload,a.min_volume_multiple);os.makedirs(os.path.dirname(os.path.abspath(a.output)),exist_ok=True)
    with open(a.output,"w",encoding="utf-8") as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
