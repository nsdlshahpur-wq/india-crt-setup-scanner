"""Three-month CRT model with Daily CHoCH and strict FVG/IFVG/OB confluence retest."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import time as dtime
from typing import Any
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class ScanConfig:
    atr_length: int = 14
    displacement_atr: float = 1.2
    pivot_left: int = 3
    pivot_right: int = 3
    sweep_lookback: int = 10
    entry_valid_days: int = 3

def _normalise_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty: return pd.DataFrame()
    data=frame.copy()
    if isinstance(data.columns,pd.MultiIndex):
        names={"open","high","low","close","volume"}
        data.columns=[next((str(x).title() for x in col if str(x).lower() in names),str(col[0]).title()) for col in data.columns]
    data.columns=[str(c).strip().title() for c in data.columns]
    required=["Open","High","Low","Close"]
    if not all(c in data.columns for c in required): return pd.DataFrame()
    cols=required+(["Volume"] if "Volume" in data.columns else [])
    data=data[cols].copy(); data.index=pd.to_datetime(data.index)
    if getattr(data.index,"tz",None) is not None: data.index=data.index.tz_localize(None)
    data=data[~data.index.duplicated(keep="last")].sort_index()
    for c in cols: data[c]=pd.to_numeric(data[c],errors="coerce")
    return data.dropna(subset=required)

def _wilder_atr(data: pd.DataFrame,length:int)->pd.Series:
    prev=data.Close.shift(1)
    tr=pd.concat([data.High-data.Low,(data.High-prev).abs(),(data.Low-prev).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/length,adjust=False,min_periods=length).mean()

def _confirmed_pivots(series:pd.Series,left:int,right:int,is_high:bool)->pd.Series:
    vals=series.to_numpy(float); out=np.full(len(vals),np.nan); width=left+right+1
    for i in range(width-1,len(vals)):
        p=i-right; w=vals[i-width+1:i+1]; v=vals[p]
        if np.isfinite(w).all() and v==(np.max(w) if is_high else np.min(w)) and np.count_nonzero(w==v)==1: out[i]=v
    return pd.Series(out,index=series.index)

def _three_month_context(data:pd.DataFrame)->dict[str,Any]|None:
    if data.empty:return None
    keys=data.index.to_period("M")
    months=data.groupby(keys).agg(High=("High","max"),Low=("Low","min"),Close=("Close","last"))
    # Need two completed months plus current/active third month; exclude last month if data ends in it only as M3.
    if len(months)<3:return None
    m1,m2,m3=months.iloc[-3],months.iloc[-2],months.iloc[-1]
    m1p,m2p,m3p=months.index[-3],months.index[-2],months.index[-1]
    rows2=data.loc[keys==m2p]; rows3=data.loc[keys==m3p]
    if rows2.empty or rows3.empty:return None
    bull=float(m2.Low)<float(m1.Low) and float(m2.Close)>float(m1.Low)
    bear=float(m2.High)>float(m1.High) and float(m2.Close)<float(m1.High)
    return dict(m1_high=float(m1.High),m1_low=float(m1.Low),m2_high=float(m2.High),m2_low=float(m2.Low),
        m2_close=float(m2.Close),m2_start=rows2.index[0],m3_start=rows3.index[0],
        m1_period=str(m1p),m2_period=str(m2p),m3_period=str(m3p),bias=1 if bull else (-1 if bear else 0))

def _zones(data:pd.DataFrame, start:int, end:int, direction:int):
    """Collect directional FVGs, IFVGs (failed opposing FVGs), and OBs as price intervals."""
    fvg=[]; ifvg=[]; ob=[]
    for i in range(max(start+2,2),end+1):
        # FVG: classic three-candle gap, with direction.
        if direction==1 and data.Low.iloc[i]>data.High.iloc[i-2]:
            fvg.append((float(data.High.iloc[i-2]),float(data.Low.iloc[i]),i))
        elif direction==-1 and data.High.iloc[i]<data.Low.iloc[i-2]:
            fvg.append((float(data.High.iloc[i]),float(data.Low.iloc[i-2]),i))
        # IFVG: a prior opposite FVG is invalidated by close-through; its interval flips.
        if direction==1 and data.High.iloc[i-2]<data.Low.iloc[i] and data.Close.iloc[i]<data.High.iloc[i-2]:
            ifvg.append((float(data.High.iloc[i-2]),float(data.Low.iloc[i]),i))
        if direction==-1 and data.Low.iloc[i-2]>data.High.iloc[i] and data.Close.iloc[i]>data.Low.iloc[i-2]:
            ifvg.append((float(data.High.iloc[i]),float(data.Low.iloc[i-2]),i))
        # OB proxy: last opposite candle before directional displacement; range = full candle.
        if i>=1:
            opposite=(data.Close.iloc[i-1]<data.Open.iloc[i-1]) if direction==1 else (data.Close.iloc[i-1]>data.Open.iloc[i-1])
            atr=_wilder_atr(data.iloc[:i+1],14).iloc[-1]
            body=abs(data.Close.iloc[i]-data.Open.iloc[i])
            displacement=(data.Close.iloc[i]>data.Open.iloc[i] if direction==1 else data.Close.iloc[i]<data.Open.iloc[i])
            if opposite and displacement and pd.notna(atr) and body>=1.2*atr:
                ob.append((float(data.Low.iloc[i-1]),float(data.High.iloc[i-1]),i))
    return fvg,ifvg,ob

def scan_symbol(symbol:str,name:str,raw_data:pd.DataFrame,config:ScanConfig)->dict[str,Any]|None:
    data=_normalise_ohlc(raw_data)
    now=pd.Timestamp.now(tz=ZoneInfo("Asia/Kolkata"))
    if not data.empty and data.index[-1].date()==now.date() and now.time()<dtime(15,40): data=data.iloc[:-1]
    if len(data)<max(config.atr_length+10,80):return None
    ctx=_three_month_context(data)
    if ctx is None:return None
    direction=ctx["bias"]; last=len(data)-1; ltp=float(data.Close.iloc[-1])
    entry=sl=np.nan; sweep_date=entry_date=None; zone_low=zone_high=np.nan; choch_date=None
    stage=0
    if direction:
        m3_idxs=np.flatnonzero(data.index>=ctx["m3_start"])
        m2_idxs=np.flatnonzero((data.index>=ctx["m2_start"])&(data.index<ctx["m3_start"]))
        # The M2 sweep/reclaim is the monthly validation. Search the active M3 daily structure.
        if len(m3_idxs)>0:
            start=int(m3_idxs[0]); highs=_confirmed_pivots(data.High,config.pivot_left,config.pivot_right,True).ffill()
            lows=_confirmed_pivots(data.Low,config.pivot_left,config.pivot_right,False).ffill()
            ch_idx=None
            for i in range(max(start+1,config.pivot_left+config.pivot_right+1),last+1):
                prior=highs.iloc[i-1] if direction==1 else lows.iloc[i-1]
                broken=(data.Close.iloc[i]>prior) if direction==1 and pd.notna(prior) else ((data.Close.iloc[i]<prior) if direction==-1 and pd.notna(prior) else False)
                if broken: ch_idx=i; break
            if ch_idx is not None:
                fvg,ifvg,ob=_zones(data,start,ch_idx,direction)
                # Strict confluence: overlap of at least one FVG, IFVG and OB interval.
                common=None
                for zf in fvg:
                    for zi in ifvg:
                        for zo in ob:
                            lo=max(zf[0],zi[0],zo[0]); hi=min(zf[1],zi[1],zo[1])
                            if lo<=hi: common=(lo,hi); break
                        if common:break
                    if common:break
                if common:
                    zone_low,zone_high=common
                    # Retest then confirmation close in expected direction, after CHoCH.
                    for i in range(ch_idx+1,last+1):
                        touched=data.Low.iloc[i]<=zone_high and data.High.iloc[i]>=zone_low
                        confirm=data.Close.iloc[i]>data.Open.iloc[i] and data.Close.iloc[i]>zone_high if direction==1 else data.Close.iloc[i]<data.Open.iloc[i] and data.Close.iloc[i]<zone_low
                        if touched and confirm:
                            entry=float(data.Close.iloc[i]); entry_date=data.index[i].date().isoformat()
                            sl=float(data.Low.iloc[m2_idxs].min()) if direction==1 and len(m2_idxs) else (float(data.High.iloc[m2_idxs].max()) if len(m2_idxs) else (ctx["m2_low"] if direction==1 else ctx["m2_high"]))
                            stage=3; choch_date=data.index[ch_idx].date().isoformat(); sweep_date=ctx["m2_period"]; break
                else: stage=2
            else: stage=1
    target=ctx["m1_high"] if direction==1 else (ctx["m1_low"] if direction==-1 else np.nan)
    bias_name="Bullish" if direction==1 else ("Bearish" if direction==-1 else "Neutral")
    setup="BUY" if stage==3 and direction==1 else ("SELL" if stage==3 and direction==-1 else ("Wait CHoCH" if stage==1 else ("Wait Retest" if stage==2 else "-")))
    return {"Symbol":symbol,"Name":name,"Bias":bias_name,"Stage":stage,"Setup":setup,"LTP":ltp,"Entry":entry,"SL":sl,
        "T1 (2R)":(entry+2*(entry-sl) if direction==1 and pd.notna(entry) and pd.notna(sl) else (entry-2*(sl-entry) if direction==-1 and pd.notna(entry) and pd.notna(sl) else np.nan)),
        "T2 (M1 H/L)":target,"Invalidation":ctx["m1_low"] if direction==1 else (ctx["m1_high"] if direction==-1 else np.nan),
        "M1 High":ctx["m1_high"],"M1 Low":ctx["m1_low"],"M2 High":ctx["m2_high"],"M2 Low":ctx["m2_low"],
        "M2 Close":ctx["m2_close"],"M1 Month":ctx["m1_period"],"M2 Month":ctx["m2_period"],"M3 Month":ctx["m3_period"],
        "Sweep Date":sweep_date,"CHoCH Date":choch_date,"Entry Date":entry_date,"Zone Low":zone_low,"Zone High":zone_high,
        "Last Candle":data.index[-1].date().isoformat()}
