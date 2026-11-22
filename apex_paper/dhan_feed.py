"""Dhan historical candle adapter. Credentials are read from environment only."""
import os, requests
BASE="https://api.dhan.co/v2"
def get_intraday_candles(security_id, exchange_segment="IDX_I", instrument="INDEX", interval="5", from_date=None, to_date=None):
    token=os.getenv("DHAN_ACCESS_TOKEN")
    if not token: raise RuntimeError("Set DHAN_ACCESS_TOKEN in deployment secrets.")
    if not from_date or not to_date: raise ValueError("from_date and to_date required (YYYY-MM-DD HH:MM:SS)")
    payload={"securityId":str(security_id),"exchangeSegment":exchange_segment,"instrument":instrument,
             "interval":str(interval),"oi":False,"fromDate":from_date,"toDate":to_date}
    r=requests.post(BASE+"/charts/intraday",headers={"access-token":token,"Content-Type":"application/json","Accept":"application/json"},json=payload,timeout=30)
    r.raise_for_status(); data=r.json()
    import pandas as pd
    if not data.get("timestamp"): raise RuntimeError(f"Dhan returned no candle timestamps: {data}")
    frame=pd.DataFrame({"open":data["open"],"high":data["high"],"low":data["low"],"close":data["close"],"volume":data.get("volume",[0]*len(data["timestamp"]))})
    frame.index=pd.to_datetime(data["timestamp"],unit="s",utc=True).tz_convert("Asia/Kolkata")
    return frame.sort_index()
