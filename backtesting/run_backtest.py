"""
AtlasFX Master Backtest Script
Usage: cd ~/Desktop/AtlasFX && python3 backtesting/run_backtest.py
Reads all zip files from ~/Desktop/Backtesting data/ automatically
Tests London ORB, NY ORB and EMA Pullback at optimal TP levels
"""
import os, zipfile, glob
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path.home() / "Desktop" / "Backtesting data "

def load_pair(pair_code):
    dfs = []
    zips = list(DATA_DIR.glob(f"*{pair_code}*.zip"))
    for z in sorted(zips):
        extract_dir = DATA_DIR / f"_extracted_{pair_code}"
        extract_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(z, 'r') as zf:
            zf.extractall(extract_dir)
    csvs = list((DATA_DIR / f"_extracted_{pair_code}").glob("*.csv")) if (DATA_DIR / f"_extracted_{pair_code}").exists() else []
    csvs += list(DATA_DIR.glob(f"*{pair_code}*.csv"))
    for f in sorted(csvs):
        try:
            df = pd.read_csv(f, sep=';', header=None,
                names=['datetime','Open','High','Low','Close','Volume'])
            df['datetime'] = pd.to_datetime(df['datetime'], format='%Y%m%d %H%M%S')
            df.set_index('datetime', inplace=True)
            dfs.append(df)
        except: pass
    if not dfs: return None
    m1 = pd.concat(dfs).sort_index()
    h1 = m1[['Open','High','Low','Close','Volume']].astype(float).resample('1h').agg(
        {'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    return h1

def adx_f(h,l,c,p=14):
    tr=pd.concat([h-l,abs(h-c.shift()),abs(l-c.shift())],axis=1).max(axis=1)
    up=h.diff();dn=-l.diff()
    dmp=pd.Series(np.where((up>dn)&(up>0),up,0),index=h.index)
    dmm=pd.Series(np.where((dn>up)&(dn>0),dn,0),index=h.index)
    a=tr.ewm(span=p,adjust=False).mean()
    dip=(dmp.ewm(span=p,adjust=False).mean()/a.replace(0,1e-9))*100
    dim=(dmm.ewm(span=p,adjust=False).mean()/a.replace(0,1e-9))*100
    dx=(abs(dip-dim)/(dip+dim).replace(0,1e-9))*100
    return dx.ewm(span=p,adjust=False).mean()

def atr_f(h,l,c,p=14):
    tr=pd.concat([h-l,abs(h-c.shift()),abs(l-c.shift())],axis=1).max(axis=1)
    return tr.ewm(span=p,adjust=False).mean()

def rsi_f(c,p=14):
    d=c.diff();g=d.clip(lower=0).ewm(span=p,adjust=False).mean()
    l=(-d.clip(upper=0)).ewm(span=p,adjust=False).mean()
    return 100-(100/(1+g/l.replace(0,1e-9)))

def sim(d,sl,tp,fh,fl):
    for h2,l2 in zip(fh[:26],fl[:26]):
        if d=='BUY':
            if l2<=sl: return 'SL'
            if h2>=tp: return 'TP'
        else:
            if h2>=sl: return 'SL'
            if l2<=tp: return 'TP'
    return None

def run_london_orb(h1, pip, rr=1.5):
    c=h1['Close'];h=h1['High'];l=h1['Low'];o=h1['Open']
    adx_s=adx_f(h,l,c);atr_s=atr_f(h,l,c)
    e200=c.ewm(span=200,adjust=False).mean()
    e50=c.ewm(span=50,adjust=False).mean()
    dates=pd.Series(h1.index.date).unique()
    wins=0;total=0
    for date in dates:
        try:
            day=h1[h1.index.date==date]
            if len(day)<10 or day.index[0].weekday() in [0,4]: continue
            asian=day[day.index.hour<7]
            if len(asian)<2: continue
            ah=float(asian['High'].max());al=float(asian['Low'].min());ar=ah-al
            if ar<pip*10 or ar>pip*80: continue
            session=day[(day.index.hour>=7)&(day.index.hour<14)]
            traded=False
            for idx,bar in session.iterrows():
                if traded: break
                i=h1.index.get_loc(idx)
                bc=float(bar['Close']);bo=float(bar['Open'])
                if adx_s.iloc[i]<25 or abs(bc-bo)<float(atr_s.iloc[i])*0.4: continue
                ce200=float(e200.iloc[i]);ce50=float(e50.iloc[i])
                if bc>ah and bo<ah and bc>ce200 and bc>ce50 and bc>=ah+ar*0.2:
                    r=sim('BUY',ah-ar*0.5,ah+ar*rr,h1['High'].iloc[i+1:i+26].values,h1['Low'].iloc[i+1:i+26].values)
                    if r: wins+=(r=='TP');total+=1;traded=True
                elif bc<al and bo>al and bc<ce200 and bc<ce50 and bc<=al-ar*0.2:
                    r=sim('SELL',al+ar*0.5,al-ar*rr,h1['High'].iloc[i+1:i+26].values,h1['Low'].iloc[i+1:i+26].values)
                    if r: wins+=(r=='TP');total+=1;traded=True
        except: continue
    return total, wins

def run_ny_orb(h1, pip, rr=1.5):
    c=h1['Close'];h=h1['High'];l=h1['Low'];o=h1['Open']
    adx_s=adx_f(h,l,c);atr_s=atr_f(h,l,c)
    e200=c.ewm(span=200,adjust=False).mean()
    dates=pd.Series(h1.index.date).unique()
    wins=0;total=0
    for date in dates:
        try:
            day=h1[h1.index.date==date]
            if len(day)<10 or day.index[0].weekday() in [0,4]: continue
            ny=day[day.index.hour==13]
            if len(ny)<1: continue
            nh=float(ny['High'].max());nl=float(ny['Low'].min());nr=nh-nl
            if nr<pip*8 or nr>pip*60: continue
            session=day[(day.index.hour>=14)&(day.index.hour<17)]
            traded=False
            for idx,bar in session.iterrows():
                if traded: break
                i=h1.index.get_loc(idx)
                bc=float(bar['Close']);bo=float(bar['Open'])
                if adx_s.iloc[i]<25 or abs(bc-bo)<float(atr_s.iloc[i])*0.5: continue
                ce200=float(e200.iloc[i])
                if bc>nh and bo<nh and bc>ce200 and bc>=nh+nr*0.2:
                    r=sim('BUY',nh-nr*0.5,nh+nr*rr,h1['High'].iloc[i+1:i+21].values,h1['Low'].iloc[i+1:i+21].values)
                    if r: wins+=(r=='TP');total+=1;traded=True
                elif bc<nl and bo>nl and bc<ce200 and bc<=nl-nr*0.2:
                    r=sim('SELL',nl+nr*0.5,nl-nr*rr,h1['High'].iloc[i+1:i+21].values,h1['Low'].iloc[i+1:i+21].values)
                    if r: wins+=(r=='TP');total+=1;traded=True
        except: continue
    return total, wins

def run_ema_pullback(h1, pip):
    c=h1['Close'];h=h1['High'];l=h1['Low'];o=h1['Open']
    adx_s=adx_f(h,l,c);atr_s=atr_f(h,l,c);rsi_s=rsi_f(c)
    e21=c.ewm(span=21,adjust=False).mean()
    e50=c.ewm(span=50,adjust=False).mean()
    e200=c.ewm(span=200,adjust=False).mean()
    wins=0;total=0;li=-6
    for i in range(210,len(h1)-20):
        try:
            bt=h1.index[i]
            if bt.weekday() in [0,4] or not(7<=bt.hour<16) or i-li<3: continue
            if float(adx_s.iloc[i])<35: continue
            ce21=float(e21.iloc[i]);ce50=float(e50.iloc[i]);ce200=float(e200.iloc[i])
            pe21=float(e21.iloc[i-1]);crsi=float(rsi_s.iloc[i]);catr=float(atr_s.iloc[i])
            bc=float(c.iloc[i]);bo=float(o.iloc[i]);pbc=float(c.iloc[i-1])
            if abs(bc-bo)<catr*0.3: continue
            if ce21>ce50>ce200 and pbc<=pe21*1.0005 and bc>ce21 and 45<=crsi<=68 and bc>bo:
                sl=ce21-catr;tp=bc+abs(bc-ce21)*2.5
                if abs(bc-sl)>=pip*5:
                    r=sim('BUY',sl,tp,h1['High'].iloc[i+1:i+21].values,h1['Low'].iloc[i+1:i+21].values)
                    if r: wins+=(r=='TP');total+=1;li=i
            elif ce21<ce50<ce200 and pbc>=pe21*0.9995 and bc<ce21 and 32<=crsi<=55 and bc<bo:
                sl=ce21+catr;tp=bc-abs(ce21-bc)*2.5
                if abs(bc-sl)>=pip*5:
                    r=sim('SELL',sl,tp,h1['High'].iloc[i+1:i+21].values,h1['Low'].iloc[i+1:i+21].values)
                    if r: wins+=(r=='TP');total+=1;li=i
        except: continue
    return total, wins

PIP_MAP = {
    "EURUSD":0.0001,"GBPUSD":0.0001,"AUDUSD":0.0001,"NZDUSD":0.0001,
    "USDCAD":0.0001,"USDCHF":0.0001,"EURGBP":0.0001,"EURAUD":0.0001,
    "EURCAD":0.0001,"EURNZD":0.0001,"GBPAUD":0.0001,"GBPCAD":0.0001,
    "GBPNZD":0.0001,"GBPCHF":0.0001,"AUDCAD":0.0001,"AUDCHF":0.0001,
    "AUDNZD":0.0001,"NZDCAD":0.0001,"NZDCHF":0.0001,
    "USDJPY":0.01,"GBPJPY":0.01,"EURJPY":0.01,"AUDJPY":0.01,
    "CADJPY":0.01,"CHFJPY":0.01,"NZDJPY":0.01,
    "XAUUSD":1.0,"XAGUSD":0.01,
}

KNOWN_PAIRS = list(PIP_MAP.keys())

if __name__ == "__main__":
    print(f"\nAtlasFX Master Backtest")
    print(f"Data: {DATA_DIR}")

    # Find pairs
    pair_codes = set()
    for f in list(DATA_DIR.glob("*.zip")) + list(DATA_DIR.glob("*.csv")):
        for p in KNOWN_PAIRS:
            if p in f.stem.upper():
                pair_codes.add(p)

    print(f"Pairs found: {sorted(pair_codes)}\n")
    print(f"{'='*72}")
    print(f"{'Pair':<10} {'Strategy':<14} {'TP':>5} {'n':>5} {'WR':>7} {'PF':>5} {'EV':>7}  Verdict")
    print(f"{'-'*72}")

    results = []
    for pair in sorted(pair_codes):
        pip = PIP_MAP.get(pair, 0.0001)
        print(f"\n{pair}: loading...", end=" ", flush=True)
        h1 = load_pair(pair)
        if h1 is None or len(h1) < 500:
            print("insufficient data"); continue
        print(f"{len(h1):,} bars | {h1.index[0].date()} to {h1.index[-1].date()}")

        # London ORB — find best TP
        best_ev = -9999; best = None
        for rr in [1.5, 1.0, 0.75, 0.5]:
            t,w = run_london_orb(h1, pip, rr)
            if t < 20: continue
            wr=w/t*100; pf=(w*rr)/(t-w) if t-w>0 else 0
            ev=(wr/100*rr*1000)-((1-wr/100)*1000)
            if ev > best_ev: best_ev=ev; best=(t,w,wr,pf,ev,rr)
        if best:
            t,w,wr,pf,ev,rr = best
            v="DEPLOY ✅" if ev>200 else ("MARGINAL ⚠️" if ev>0 else "SKIP ❌")
            print(f"  {'London ORB':<14} {rr}R {t:>5}t {wr:>6.1f}% {pf:>4.2f} £{ev:>6.0f}  {v}")
            results.append((pair,"London ORB",rr,t,wr,pf,ev))

        # NY ORB — find best TP
        best_ev = -9999; best = None
        for rr in [1.5, 1.0, 0.75, 0.5]:
            t,w = run_ny_orb(h1, pip, rr)
            if t < 20: continue
            wr=w/t*100; pf=(w*rr)/(t-w) if t-w>0 else 0
            ev=(wr/100*rr*1000)-((1-wr/100)*1000)
            if ev > best_ev: best_ev=ev; best=(t,w,wr,pf,ev,rr)
        if best:
            t,w,wr,pf,ev,rr = best
            v="DEPLOY ✅" if ev>200 else ("MARGINAL ⚠️" if ev>0 else "SKIP ❌")
            print(f"  {'NY ORB':<14} {rr}R {t:>5}t {wr:>6.1f}% {pf:>4.2f} £{ev:>6.0f}  {v}")
            results.append((pair,"NY ORB",rr,t,wr,pf,ev))

        # EMA Pullback
        t,w = run_ema_pullback(h1, pip)
        if t >= 20:
            wr=w/t*100; pf=(w*2.5)/(t-w) if t-w>0 else 0
            ev=(wr/100*2.5*1000)-((1-wr/100)*1000)
            v="DEPLOY ✅" if ev>200 else ("MARGINAL ⚠️" if ev>0 else "SKIP ❌")
            print(f"  {'EMA Pullback':<14} 2.5R {t:>5}t {wr:>6.1f}% {pf:>4.2f} £{ev:>6.0f}  {v}")
            results.append((pair,"EMA Pullback",2.5,t,wr,pf,ev))

    # Final summary
    print(f"\n{'='*72}")
    print(f"DEPLOY LIST (EV > £200) — sorted by EV:")
    deploy = [(p,s,rr,t,wr,pf,ev) for p,s,rr,t,wr,pf,ev in results if ev>200]
    deploy.sort(key=lambda x: x[6], reverse=True)
    for p,s,rr,t,wr,pf,ev in deploy:
        print(f"  {p:<10} {s:<14} {rr}R  {t:>4}t {wr:>6.1f}%  £{ev:>6.0f}/trade")
    print(f"\nTotal DEPLOY combos: {len(deploy)}")
    skip = [(p,s,rr,t,wr,pf,ev) for p,s,rr,t,wr,pf,ev in results if ev<=0]
    print(f"Total SKIP combos:   {len(skip)}")
