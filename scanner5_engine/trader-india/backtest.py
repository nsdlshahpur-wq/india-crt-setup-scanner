#!/usr/bin/env python3
"""Deterministic daily breakout backtest with next-open fills and fixed ATR stop.

This is a transparent baseline, not a predictive model. It uses no future bar
for an entry: a signal on close[t] is entered at open[t+1].
"""
import argparse,csv,json,math,os,sys
sys.path.insert(0,os.path.dirname(__file__))
from india import atr_wilder

def run_backtest(bars,initial_capital=100000,risk_pct=0.5,fee_bps=5,slippage_bps=5,lookback=20):
    if initial_capital<=0 or not 0<risk_pct<=0.5 or lookback<5:raise ValueError("Invalid backtest parameters")
    trades=[];cash=float(initial_capital);equity=[cash];position=None
    for i in range(lookback+1,len(bars)):
        bar=bars[i];prev=bars[:i]
        if position:
            exit_price=None;reason=None
            if float(bar["low"])<=position["stop"]:exit_price=position["stop"];reason="stop"
            elif i-position["entry_index"]>=10:exit_price=float(bar["close"]);reason="time_exit"
            if exit_price is not None:
                gross=(exit_price-position["entry"])*position["qty"]
                costs=(position["entry"]+exit_price)*position["qty"]*(fee_bps+slippage_bps)/10000
                pnl=gross-costs;cash+=position["qty"]*exit_price-costs
                trades.append({"entry":position["entry"],"exit":exit_price,"qty":position["qty"],"pnl":round(pnl,2),"reason":reason})
                position=None
        if not position and i+1<len(bars):
            closes=[float(x["close"]) for x in prev]
            signal=float(prev[-1]["close"])>max(closes[-lookback-1:-1])
            atr=atr_wilder(prev,14)
            if signal and atr and float(bar["open"])>0:
                entry=float(bar["open"]);stop=entry-2*atr
                risk_cash=cash*risk_pct/100;qty=max(0,math.floor(risk_cash/(entry-stop)))
                qty=min(qty,math.floor(cash*0.2/entry))
                if qty:
                    cash-=qty*entry
                    position={"entry":entry,"stop":stop,"qty":qty,"entry_index":i}
        mark=cash+(position["qty"]*float(bar["close"]) if position else 0)
        equity.append(mark)
    if position:
        last=float(bars[-1]["close"]);gross=(last-position["entry"])*position["qty"]
        costs=(position["entry"]+last)*position["qty"]*(fee_bps+slippage_bps)/10000
        trades.append({"entry":position["entry"],"exit":last,"qty":position["qty"],"pnl":round(gross-costs,2),"reason":"end_of_data"})
        equity.append(cash+position["qty"]*last-costs)
    wins=[t for t in trades if t["pnl"]>0];losses=[t for t in trades if t["pnl"]<=0]
    peak=equity[0];max_dd=0
    for v in equity:
        peak=max(peak,v);max_dd=max(max_dd,(peak-v)/peak if peak else 0)
    return {"trades":trades,"trade_count":len(trades),"win_rate_pct":round(100*len(wins)/len(trades),2) if trades else 0,
      "net_pnl":round(sum(t["pnl"] for t in trades),2),"profit_factor":round(sum(t["pnl"] for t in wins)/abs(sum(t["pnl"] for t in losses)),2) if losses and sum(t["pnl"] for t in losses)!=0 else None,
      "max_drawdown_pct":round(max_dd*100,2),"initial_capital":initial_capital,
      "caveats":"Daily OHLC approximation; stop fills, gaps, slippage, costs and survivorship bias can materially change results. Not investment advice."}

def main(argv=None):
    p=argparse.ArgumentParser(description="Daily breakout backtest using OHLCV CSV")
    p.add_argument("--csv",required=True);p.add_argument("--capital",type=float,default=100000);p.add_argument("--output")
    a=p.parse_args(argv)
    with open(a.csv,encoding="utf-8-sig",newline="") as f:bars=list(csv.DictReader(f))
    for b in bars:
        for k in ("open","high","low","close","volume"):b[k]=float(b[k])
    result=run_backtest(bars,a.capital);data=json.dumps(result,indent=2)
    if a.output:
        os.makedirs(os.path.dirname(os.path.abspath(a.output)),exist_ok=True)
        with open(a.output,"w",encoding="utf-8") as f:f.write(data+"\n")
    print(data);return 0
if __name__=="__main__":raise SystemExit(main())
