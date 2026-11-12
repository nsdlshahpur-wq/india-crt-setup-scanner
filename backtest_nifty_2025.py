from pathlib import Path
import pandas as pd
import numpy as np

DATA_DIR = Path("research_data")
FILES = sorted(DATA_DIR.glob("2025_part_*.csv"))
if not FILES:
    raise SystemExit("No data chunks found")
raw = pd.concat([pd.read_csv(p) for p in FILES], ignore_index=True)
raw = raw.drop_duplicates("Epoch").sort_values("Epoch")
raw["Timestamp"] = pd.to_datetime(raw["Timestamp"])
raw = raw.set_index("Timestamp")
raw = raw[["Open","High","Low","Close"]].astype(float)
# Retain regular NSE continuous session only; timestamps are IST and bar-start labels.
raw = raw.between_time("09:15", "15:29")
raw = raw[~raw.index.duplicated(keep="first")]

def resample(df, rule):
    # The data timestamps are bar starts. Anchor each trading session at 09:15.
    out=[]
    for day, g in df.groupby(df.index.date):
        g=g.sort_index()
        x=g.resample(rule, origin=pd.Timestamp(str(day)+" 09:15:00"), label="left", closed="left").agg(
            {"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
        out.append(x)
    return pd.concat(out).sort_index()

h1=resample(raw,"1h")
m15=resample(raw,"15min")

def pivots(arr, typ, left=2, right=2):
    vals=[]
    for i in range(left, len(arr)-right):
        w=arr[i-left:i+right+1]
        v=arr[i]
        if typ=="H" and v==max(w) and w.count(v)==1: vals.append((i,v))
        if typ=="L" and v==min(w) and w.count(v)==1: vals.append((i,v))
    return vals

def make_events(hourly, mode):
    hi=hourly["High"].tolist(); lo=hourly["Low"].tolist()
    op=hourly["Open"].tolist(); cl=hourly["Close"].tolist()
    ph=pivots(hi,"H"); pl=pivots(lo,"L")
    events=[]
    for i in range(12,len(hourly)-1):
        known_h=[p for p in ph if p[0] <= i-2]
        known_l=[p for p in pl if p[0] <= i-2]
        bull_level=known_h[-1][1] if known_h else None
        bear_level=known_l[-1][1] if known_l else None
        direction=None
        if bull_level is not None and cl[i]>bull_level and cl[i-1]<=bull_level: direction="Bullish"
        elif bear_level is not None and cl[i]<bear_level and cl[i-1]>=bear_level: direction="Bearish"
        if not direction: continue
        ob=None; fvg=None
        # Last opposing candle among previous 8 fully closed hourly candles
        for j in range(i-1,max(-1,i-9),-1):
            opposing=(cl[j]<op[j]) if direction=="Bullish" else (cl[j]>op[j])
            if opposing:
                ob=(lo[j],hi[j]); break
        # Three-candle gap completed on the CHoCH candle
        if i>=2:
            if direction=="Bullish" and lo[i]>hi[i-2]: fvg=(hi[i-2],lo[i])
            if direction=="Bearish" and hi[i]<lo[i-2]: fvg=(hi[i],lo[i-2])
        events.append({"time":hourly.index[i+1] if i+1<len(hourly) else hourly.index[i],
                       "signal_time":hourly.index[i],"direction":direction,"ob":ob,"fvg":fvg})
    return events

def run_variant(events, m15, zone_key, confirm, variant):
    trades=[]
    idx=m15.index
    busy_until=-1
    for ev in events:
        if ev[zone_key] is None: continue
        zlo,zhi=ev[zone_key]
        start=idx.searchsorted(ev["time"],side="left")
        if start>=len(idx) or start<=busy_until: continue
        side=1 if ev["direction"]=="Bullish" else -1
        entry_i=None; entry=None; sl=None
        # Retest must occur within next 64 15m bars (~16 trading hours)
        for k in range(start,min(start+64,len(idx)-1)):
            row=m15.iloc[k]
            touched=(row.Low<=zhi and row.High>=zlo)
            if not touched: continue
            if confirm:
                prev=m15.iloc[k-1] if k>0 else None
                ok=(row.Close>row.Open and prev is not None and row.Close>prev.High) if side==1 else (row.Close<row.Open and prev is not None and row.Close<prev.Low)
                if not ok: continue
            entry_i=k+1
            entry=float(m15.Open.iloc[entry_i])
            sl=float(zlo if side==1 else zhi)
            if (side==1 and sl>=entry) or (side==-1 and sl<=entry): continue
            risk=abs(entry-sl)
            if risk<1: continue
            target=entry+side*2*risk
            break
        if entry_i is None: continue
        exit_price=None; outcome=None; exit_i=None
        for k in range(entry_i,min(entry_i+160,len(idx))):
            row=m15.iloc[k]
            stop_hit=(row.Low<=sl) if side==1 else (row.High>=sl)
            target_hit=(row.High>=target) if side==1 else (row.Low<=target)
            # Conservative when both levels trade in one candle: assume stop first.
            if stop_hit:
                exit_price=sl; outcome="Loss"; exit_i=k; break
            if target_hit:
                exit_price=target; outcome="Win"; exit_i=k; break
        if exit_price is None:
            exit_i=min(entry_i+159,len(idx)-1)
            exit_price=float(m15.Close.iloc[exit_i]); outcome="Open/Timed exit"
        # Simple index-point friction: 1 point each side (2 points round trip).
        gross=side*(exit_price-entry)
        net=gross-2.0
        r_net=net/abs(entry-sl)
        trades.append({"Variant":variant,"Signal":ev["signal_time"],"EntryTime":idx[entry_i],
                       "Direction":ev["direction"],"Entry":entry,"SL":sl,"Target":target,
                       "ExitTime":idx[exit_i],"Exit":exit_price,"Outcome":outcome,
                       "GrossPoints":gross,"NetPoints":net,"R":r_net})
        busy_until=exit_i
    return pd.DataFrame(trades)

events=make_events(h1,"")
configs=[
    ("A: 1H CHoCH + OB retest","ob",False),
    ("B: 1H CHoCH + FVG retest","fvg",False),
    ("C: 1H CHoCH + OB/FVG retest + 15M confirmation","either",True),
]
alltr=[]
for name,key,confirm in configs:
    if key=="either":
        # combine OB and FVG zones, but do not duplicate the same CHoCH event
        ee=[]
        for ev in events:
            zones=[z for z in [ev["ob"],ev["fvg"]] if z is not None]
            if zones:
                # pick most recently defined zone by choosing FVG first where available
                e=dict(ev); e["either"]=zones[-1]; ee.append(e)
        t=run_variant(ee,m15,"either",confirm,name)
    else:
        t=run_variant(events,m15,key,confirm,name)
    if not t.empty: alltr.append(t)

trades=pd.concat(alltr,ignore_index=True) if alltr else pd.DataFrame()
summary=[]
for name,_,_ in configs:
    t=trades[trades.Variant==name] if not trades.empty else pd.DataFrame()
    n=len(t); wins=int((t.Outcome=="Win").sum()) if n else 0
    losses=int((t.Outcome=="Loss").sum()) if n else 0
    gross_profit=float(t.loc[t.NetPoints>0,"NetPoints"].sum()) if n else 0
    gross_loss=float(-t.loc[t.NetPoints<0,"NetPoints"].sum()) if n else 0
    equity=t.NetPoints.cumsum() if n else pd.Series(dtype=float)
    dd=float((equity-equity.cummax()).min()) if n else 0
    summary.append({"Variant":name,"Trades":n,"Wins":wins,"Losses":losses,
                    "WinRatePct":round(100*wins/n,2) if n else 0,
                    "ProfitFactor":round(gross_profit/gross_loss,3) if gross_loss else None,
                    "NetPoints":round(float(t.NetPoints.sum()),2) if n else 0,
                    "AvgR":round(float(t.R.mean()),3) if n else 0,
                    "MaxDrawdownPoints":round(dd,2) if n else 0})
pd.DataFrame(summary).to_csv("backtest_summary.csv",index=False)
if not trades.empty: trades.to_csv("backtest_trades.csv",index=False)
print("DATA_ROWS",len(raw),"FROM",raw.index.min(),"TO",raw.index.max())
print("H1_BARS",len(h1),"M15_BARS",len(m15))
print(pd.DataFrame(summary).to_string(index=False))
