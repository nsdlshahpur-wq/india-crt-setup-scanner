#!/usr/bin/env python3
"""Import a user-downloaded BSE scrip master into the BSE scanner universe."""
import argparse
import csv
import json
import os
import re
CODE_FIELDS=("scrip_cd","scrip_code","scripcode","security_code","securitycode","sc_code","code")
NAME_FIELDS=("scrip_name","security_name","company_name","issuer_name","name")

def import_bse_master(source,destination):
    accepted=[];rejected=[];seen=set()
    with open(source,encoding="utf-8-sig",newline="") as handle:
        for number,row in enumerate(csv.DictReader(handle),2):
            low={str(key).strip().lower().replace(" ","_"):value for key,value in row.items()}
            code=next((str(low[key]).strip() for key in CODE_FIELDS if low.get(key)), "")
            name=next((str(low[key]).strip() for key in NAME_FIELDS if low.get(key)), "")
            if not re.fullmatch(r"[0-9]{5,8}",code):
                rejected.append({"row":number,"scrip_code":code,"reason":"missing or invalid numeric BSE scrip code"})
                continue
            if code not in seen:
                seen.add(code);accepted.append({"symbol":code,"name":name})
    os.makedirs(os.path.dirname(os.path.abspath(destination)),exist_ok=True)
    with open(destination,"w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=("symbol","name"));writer.writeheader();writer.writerows(accepted)
    return {"exchange":"BSE","accepted":len(accepted),"rejected":len(rejected),"symbols":accepted,
      "rejected_rows":rejected,"note":"Verify this is the current official BSE equity scrip master and excludes non-equity instruments."}

def main(argv=None):
    parser=argparse.ArgumentParser(description="Import a downloaded BSE equity scrip master CSV")
    parser.add_argument("--input",required=True);parser.add_argument("--output",default="trader-india/bse-universe.csv")
    args=parser.parse_args(argv);result=import_bse_master(args.input,args.output)
    print(json.dumps(result,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
