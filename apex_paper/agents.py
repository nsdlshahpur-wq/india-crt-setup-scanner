"""Research-only multi-agent signal engine for completed OHLCV candles."""
from __future__ import annotations
import pandas as pd
import numpy as np

def normalize(df):
    x=df.copy()
    x.columns=[str(c).lower() for c in x.columns]
    if not {"open","high","low","close"}.issubset(x.columns):
        raise ValueError("OHLC columns required")
    if "volume" not in x: x["volume"]=0
    return x.dropna(subset=["open","high","low","close"]).sort_index()

def _agent(name, side=0, reason="No confirmation", weight=1):
    return {"agent":name,"signal":{1:"BUY",-1:"SELL",0:"HOLD"}[int(np.sign(side))],"weight":weight if side else 0,"reason":reason}

def evaluate_agents(df):
    x=normalize(df)
    if len(x)<60: return [_agent("DataQuality",0,"Need at least 60 completed candles")]
    c=x.close; p=x.iloc[-1]; prev=x.iloc[-2]
    e9=c.ewm(span=9,adjust=False).mean(); e21=c.ewm(span=21,adjust=False).mean()
    e20=c.ewm(span=20,adjust=False).mean(); e50=c.ewm(span=50,adjust=False).mean()
    delta=c.diff(); gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean()
    loss=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    rsi=100-100/(1+gain/loss.replace(0,np.nan))
    volavg=x.volume.rolling(20).mean()
    swing_hi=x.high.shift(1).rolling(10).max(); swing_lo=x.low.shift(1).rolling(10).min()
    agents=[]
    agents.append(_agent("Trend",1 if p.close>e20.iloc[-1]>e50.iloc[-1] else -1 if p.close<e20.iloc[-1]<e50.iloc[-1] else 0,"EMA20/50 regime"))
    agents.append(_agent("EMA_RSI",1 if e9.iloc[-1]>e21.iloc[-1] and 50<rsi.iloc[-1]<70 else -1 if e9.iloc[-1]<e21.iloc[-1] and 30<rsi.iloc[-1]<50 else 0,"EMA9/21 with RSI"))
    agents.append(_agent("LiquiditySweep",1 if p.low<swing_lo.iloc[-1] and p.close>swing_lo.iloc[-1] else -1 if p.high>swing_hi.iloc[-1] and p.close<swing_hi.iloc[-1] else 0,"Prior 10-candle swing sweep and reclaim",2))
    agents.append(_agent("VolumeBreakout",1 if p.close>prev.high and p.volume>volavg.iloc[-1] else -1 if p.close<prev.low and p.volume>volavg.iloc[-1] else 0,"Breakout with relative volume"))
    # FVG proxy: 3-candle imbalance, only if last candle trades back into zone.
    bull_gap=x.low.iloc[-1]>x.high.iloc[-3]
    bear_gap=x.high.iloc[-1]<x.low.iloc[-3]
    agents.append(_agent("FVG",1 if bull_gap and x.high.iloc[-3]<=p.close<=x.low.iloc[-1] else -1 if bear_gap and x.high.iloc[-1]<=p.close<=x.low.iloc[-3] else 0,"Three-candle gap/retest proxy",2))
    return agents

def consensus(agents, min_points=4):
    buy=sum(a["weight"] for a in agents if a["signal"]=="BUY")
    sell=sum(a["weight"] for a in agents if a["signal"]=="SELL")
    side="BUY" if buy>=min_points and buy>sell else "SELL" if sell>=min_points and sell>buy else "HOLD"
    return {"signal":side,"buy_points":buy,"sell_points":sell,"agents":agents}

def paper_signal(df, rr=2.0, risk_pct=0.5):
    x=normalize(df); result=consensus(evaluate_agents(x)); px=float(x.close.iloc[-1])
    tr=pd.concat([x.high-x.low,(x.high-x.close.shift()).abs(),(x.low-x.close.shift()).abs()],axis=1).max(axis=1)
    atr=float(tr.rolling(14).mean().iloc[-1])
    stop=target=None
    if result["signal"] in ("BUY","SELL") and np.isfinite(atr) and atr>0:
        dist=1.5*atr
        stop=px-dist if result["signal"]=="BUY" else px+dist
        target=px+rr*dist if result["signal"]=="BUY" else px-rr*dist
    return {**result,"entry_reference":px,"stop_loss":stop,"target":target,
            "risk_per_trade_pct":risk_pct,"mode":"PAPER_ONLY",
            "note":"Illustrative research signal on supplied candles; no broker order is sent."}
