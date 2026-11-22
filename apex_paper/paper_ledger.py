"""In-memory paper ledger. No Dhan order API is imported or called."""
from dataclasses import dataclass,asdict
from datetime import datetime
@dataclass
class PaperPosition:
    symbol:str; side:str; qty:int; entry:float; stop:float; target:float; opened_at:str
class PaperLedger:
    def __init__(self): self.positions=[]; self.events=[]
    def open_from_signal(self,symbol,result,capital=100000,risk_pct=.5):
        if result.get("mode")!="PAPER_ONLY" or result.get("signal") not in ("BUY","SELL"):
            return {"opened":False,"reason":"No paper entry signal"}
        entry=float(result["entry_reference"]); stop=float(result["stop_loss"])
        dist=abs(entry-stop)
        if dist<=0:return {"opened":False,"reason":"Invalid stop distance"}
        qty=int(capital*risk_pct/100/dist)
        if qty<1:return {"opened":False,"reason":"Risk budget too small"}
        pos=PaperPosition(symbol,result["signal"],qty,entry,stop,float(result["target"]),datetime.now().isoformat())
        self.positions.append(pos); self.events.append({"event":"PAPER_OPEN","position":asdict(pos)})
        return {"opened":True,"position":asdict(pos)}
