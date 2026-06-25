"""
AtlasFX Walk-Forward Backtest
Tests whether edge holds out-of-sample across time periods
Split: 2023 = in-sample | 2024 = validation | 2025 = out-of-sample
"""
import os, zipfile
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path.home() / "Desktop" / "Backtesting data "

# Pair-specific TP from validated config
LONDON_ORB_TP = {
    "AUD_CAD":0.75,"AUD_CHF":0.5,"AUD_NZD":1.5,"AUD_USD":0.75,
    "CAD_JPY":1.0,"CHF_JPY":1.0,"EUR_AUD":0.5,"EUR_CAD":0.75,
    "EUR_GBP":0.5,"EUR_JPY":0.75,"EUR_NZD":0.5,"EUR_USD":1.5,
    "GBP_AUD":0.5,"GBP_CAD":1.0,"GBP_CHF":0.5,"GBP_JPY":1.0,
    "GBP_NZD":0.5,"GBP_USD":1.5,"NZD_CAD":1.5,"NZD_CHF":1.5,
    "NZD_JPY":0.5,"NZD_USD":1.5,"USD_CAD":1.5,"USD_CHF":1.5,
    "USD_JPY":1.5,"XAG_USD":1.0,"XAU_USD":1.0,
}
NY_ORB_TP = {
    "AUD_CAD":1.0,"AUD_USD":1.0,"CAD_JPY":0.75,"CHF_JPY":0.75,
    "EUR_AUD":1.0,"EUR_CAD":1.5,"EUR_JPY":0.5,"EUR_NZD":1.5,
    "EUR_USD":1.5,"GBP_AUD":1.5,"GBP_CAD":0.75,"GBP_CHF":1.5,
    "GBP_JPY":0.5,"GBP_NZD":1.0,"GBP_USD":0.75,"NZD_CAD":1.5,
    "NZD_CHF":1.5,"NZD_JPY":1.5,"NZD_USD":1.5,"USD_CAD":1.0,
    "USD_CHF":0.75,"USD_JPY":1.5,"XAG_USD":1.5,
}
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

def inst(pair): return pair[:3]+"_"+pair[3:]

def load_pair(pair_code):
    dfs = []
    zips = list(DATA_DIR.glob(f"*{pair_code}*.zip"))
    extract_dir = DATA_DIR / f"_ex_{pair_code}"
    extract_dir.mkdir(exist_ok=True)
    for z in sorted(zips):
        with zipfile.ZipFile(z,'r') as zf: zf.extractall(extract_dir)
    csvs = list(extract_dir.glob("*.csv")) + list(DATA_DIR.glob(f"*{pair_code}*.csv"))
    for f in sorted(csvs):
        try:
            df = pd.read_csv(f,sep=';',header=None,
                names=['datetime','Open','High','Low','Close','Volume'])
            df['datetime'] = pd.to_datetime(df['datetime'],format='%Y%m%d %H%M%S')
            df.set_index('datetime',inplace=True)
            dfs.append(df)
        except: pass
    if not dfs: return None
    m1 = pd.concat(dfs).sort_index()
    return m1[['Open','High','Low','Close','Volume']].astype(float).resample('1h').agg(
        {'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()

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

def run_london_orb(h1, pip, rr):
    c=h1['Close'];h=h1['High'];l=h1['Low']
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
            traded=False
            for idx,bar in day[(day.index.hour>=7)&(day.index.hour<14)].iterrows():
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
    return total,wins

def run_ny_orb(h1, pip, rr):
    c=h1['Close'];h=h1['High'];l=h1['Low']
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
            traded=False
            for idx,bar in day[(day.index.hour>=14)&(day.index.hour<17)].iterrows():
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
    return total,wins

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
    return total,wins

def period_stats(h1, pip, year, lorb_tp, nyorb_tp):
    """
    Run all 3 strategies on a specific year.
    IMPORTANT: Indicators computed on FULL history to avoid lookahead bias
    on EMA/ADX warmup, but TRADES only taken in target year.
    This mirrors real trading — you have historical data for indicator
    calculation but only trade going forward.
    """
    if len(h1) < 500:
        return None

    # Compute indicators on full dataset (correct — no future peeking)
    # Then filter trades to target year only
    year_start = pd.Timestamp(f"{year}-01-01")
    year_end = pd.Timestamp(f"{year}-12-31 23:59:59")

    # Filter to only trade in target year
    trade_mask = (h1.index >= year_start) & (h1.index <= year_end)
    if trade_mask.sum() < 200:
        return None

    results = {}

    # London ORB — pass full h1 but restrict trading dates
    t,w = run_london_orb_wf(h1, pip, lorb_tp, year)
    if t >= 5:
        wr = w/t*100
        ev = (wr/100*lorb_tp*1000) - ((1-wr/100)*1000)
        results['lorb'] = (t,w,wr,ev)

    # NY ORB
    t,w = run_ny_orb_wf(h1, pip, nyorb_tp, year)
    if t >= 5:
        wr = w/t*100
        ev = (wr/100*nyorb_tp*1000) - ((1-wr/100)*1000)
        results['nyorb'] = (t,w,wr,ev)

    # EMA Pullback
    t,w = run_ema_pullback_wf(h1, pip, year)
    if t >= 5:
        wr = w/t*100
        ev = (wr/100*2.5*1000) - ((1-wr/100)*1000)
        results['ema'] = (t,w,wr,ev)

    return results

def run_london_orb_wf(h1, pip, rr, year):
    """London ORB with full history indicators but trades restricted to year"""
    c=h1['Close'];h=h1['High'];l=h1['Low']
    # Compute on FULL history
    adx_s=adx_f(h,l,c);atr_s=atr_f(h,l,c)
    e200=c.ewm(span=200,adjust=False).mean()
    e50=c.ewm(span=50,adjust=False).mean()
    # Only trade dates in target year
    dates=pd.Series(h1[h1.index.year==year].index.date).unique()
    wins=0;total=0
    for date in dates:
        try:
            day=h1[h1.index.date==date]
            if len(day)<10 or day.index[0].weekday() in [0,4]: continue
            asian=day[day.index.hour<7]
            if len(asian)<2: continue
            ah=float(asian['High'].max());al=float(asian['Low'].min());ar=ah-al
            if ar<pip*10 or ar>pip*80: continue
            traded=False
            for idx,bar in day[(day.index.hour>=7)&(day.index.hour<14)].iterrows():
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
    return total,wins

def run_ny_orb_wf(h1, pip, rr, year):
    """NY ORB with full history indicators but trades restricted to year"""
    c=h1['Close'];h=h1['High'];l=h1['Low']
    adx_s=adx_f(h,l,c);atr_s=atr_f(h,l,c)
    e200=c.ewm(span=200,adjust=False).mean()
    dates=pd.Series(h1[h1.index.year==year].index.date).unique()
    wins=0;total=0
    for date in dates:
        try:
            day=h1[h1.index.date==date]
            if len(day)<10 or day.index[0].weekday() in [0,4]: continue
            ny=day[day.index.hour==13]
            if len(ny)<1: continue
            nh=float(ny['High'].max());nl=float(ny['Low'].min());nr=nh-nl
            if nr<pip*8 or nr>pip*60: continue
            traded=False
            for idx,bar in day[(day.index.hour>=14)&(day.index.hour<17)].iterrows():
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
    return total,wins

def run_ema_pullback_wf(h1, pip, year):
    """EMA Pullback with full history indicators but trades restricted to year"""
    c=h1['Close'];h=h1['High'];l=h1['Low'];o=h1['Open']
    adx_s=adx_f(h,l,c);atr_s=atr_f(h,l,c);rsi_s=rsi_f(c)
    e21=c.ewm(span=21,adjust=False).mean()
    e50=c.ewm(span=50,adjust=False).mean()
    e200=c.ewm(span=200,adjust=False).mean()
    # Get index positions for target year only
    year_idx = h1.index.year == year
    wins=0;total=0;li=-6
    for i in range(210,len(h1)-20):
        try:
            if not year_idx[i]: continue  # Only trade in target year
            bt=h1.index[i]
            if bt.weekday() in [0,4] or not(7<=bt.hour<16) or i-li<3: continue
            if float(adx_s.iloc[i])<35: continue
            ce21=float(e21.iloc[i]);ce50=float(e50.iloc[i]);ce200=float(e200.iloc[i])
            pe21=float(e21.iloc[i-1]);crsi=float(rsi_s.iloc[i]);catr=float(atr_s.iloc[i])
            bc=float(c.iloc[i]);bo=float(o.iloc[i])
            if abs(bc-bo)<catr*0.3: continue
            if ce21>ce50>ce200 and float(c.iloc[i-1])<=pe21*1.0005 and bc>ce21 and 45<=crsi<=68 and bc>bo:
                sl=ce21-catr;tp=bc+abs(bc-ce21)*2.5
                if abs(bc-sl)>=pip*5:
                    r=sim('BUY',sl,tp,h1['High'].iloc[i+1:i+21].values,h1['Low'].iloc[i+1:i+21].values)
                    if r: wins+=(r=='TP');total+=1;li=i
            elif ce21<ce50<ce200 and float(c.iloc[i-1])>=pe21*0.9995 and bc<ce21 and 32<=crsi<=55 and bc<bo:
                sl=ce21+catr;tp=bc-abs(ce21-bc)*2.5
                if abs(bc-sl)>=pip*5:
                    r=sim('SELL',sl,tp,h1['High'].iloc[i+1:i+21].values,h1['Low'].iloc[i+1:i+21].values)
                    if r: wins+=(r=='TP');total+=1;li=i
        except: continue
    return total,wins

# ── MAIN ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\nAtlasFX Walk-Forward Backtest")
    print("Split: 2023 (in-sample) | 2024 (validation) | 2025 (out-of-sample)")
    print("="*80)

    # Find pairs
    pair_codes = set()
    for f in list(DATA_DIR.glob("*.zip")) + list(DATA_DIR.glob("*.csv")):
        for p in KNOWN_PAIRS:
            if p in f.stem.upper():
                pair_codes.add(p)

    # Aggregate results by year
    year_totals = {2023:{'t':0,'w':0,'ev':0}, 2024:{'t':0,'w':0,'ev':0}, 2025:{'t':0,'w':0,'ev':0}}

    pair_summary = []

    for pair in sorted(pair_codes):
        pip = PIP_MAP.get(pair, 0.0001)
        instrument = inst(pair)
        lorb_tp = LONDON_ORB_TP.get(instrument, 1.5)
        nyorb_tp = NY_ORB_TP.get(instrument, 1.5)

        h1 = load_pair(pair)
        if h1 is None or len(h1) < 500:
            continue

        print(f"\n{pair}", end=" ", flush=True)
        pair_results = {}
        for year in [2023, 2024, 2025]:
            r = period_stats(h1, pip, year, lorb_tp, nyorb_tp)
            if r:
                pair_results[year] = r
                for strat, (t,w,wr,ev) in r.items():
                    year_totals[year]['t'] += t
                    year_totals[year]['w'] += w
                    year_totals[year]['ev'] += ev * t  # total EV

        # Check consistency — does edge hold across all 3 years?
        wr_by_year = {}
        for year in [2023,2024,2025]:
            if year in pair_results:
                all_t = sum(t for t,w,wr,ev in pair_results[year].values())
                all_w = sum(w for t,w,wr,ev in pair_results[year].values())
                wr_by_year[year] = all_w/all_t*100 if all_t>0 else 0

        if len(wr_by_year) == 3:
            wrs = list(wr_by_year.values())
            consistent = all(wr > 40 for wr in wrs)  # All years above breakeven
            trend = "STABLE" if max(wrs)-min(wrs) < 20 else "VOLATILE"
            flag = "✅" if consistent and trend=="STABLE" else ("⚠️" if consistent else "❌")
            print(f"{flag} {wr_by_year[2023]:.0f}%→{wr_by_year[2024]:.0f}%→{wr_by_year[2025]:.0f}% {trend}")
            pair_summary.append((pair, wr_by_year[2023], wr_by_year[2024], wr_by_year[2025], consistent, trend))
        else:
            print(f"incomplete data")

    # Year summary
    print(f"\n{'='*80}")
    print(f"WALK-FORWARD SUMMARY — ALL PAIRS COMBINED")
    print(f"{'='*80}")
    print(f"{'Year':<8} {'Trades':>8} {'Wins':>6} {'WR':>7} {'Total EV':>12} {'Per trade':>10}")
    print(f"{'-'*55}")
    for year in [2023,2024,2025]:
        yt = year_totals[year]
        if yt['t'] > 0:
            wr = yt['w']/yt['t']*100
            avg_ev = yt['ev']/yt['t']
            label = "(in-sample)" if year==2023 else ("(validation)" if year==2024 else "(out-of-sample)")
            print(f"{year} {label:<16} {yt['t']:>6} {yt['w']:>6} {wr:>6.1f}% £{yt['ev']:>10,.0f} £{avg_ev:>8,.0f}")

    # Consistency analysis
    print(f"\n{'='*80}")
    print(f"PAIR CONSISTENCY (WR% per year: 2023→2024→2025)")
    print(f"✅ Stable edge  ⚠️ Volatile but profitable  ❌ Inconsistent")
    print(f"{'-'*55}")
    stable = [p for p in pair_summary if p[4] and p[5]=="STABLE"]
    volatile = [p for p in pair_summary if p[4] and p[5]=="VOLATILE"]
    inconsistent = [p for p in pair_summary if not p[4]]

    print(f"\nSTABLE ({len(stable)} pairs):")
    for p,y1,y2,y3,_,_ in sorted(stable, key=lambda x: x[1]+x[2]+x[3], reverse=True):
        print(f"  {p:<10} {y1:.0f}% → {y2:.0f}% → {y3:.0f}%")

    print(f"\nVOLATILE ({len(volatile)} pairs) — profitable but inconsistent:")
    for p,y1,y2,y3,_,_ in volatile:
        print(f"  {p:<10} {y1:.0f}% → {y2:.0f}% → {y3:.0f}%")

    print(f"\nINCONSISTENT ({len(inconsistent)} pairs) — consider removing:")
    for p,y1,y2,y3,_,_ in inconsistent:
        print(f"  {p:<10} {y1:.0f}% → {y2:.0f}% → {y3:.0f}%")

    print(f"\nVERDICT: {len(stable)} stable pairs, {len(volatile)} volatile, {len(inconsistent)} inconsistent")
    print(f"System edge {'CONFIRMED ✅' if len(stable)>len(inconsistent) else 'QUESTIONABLE ⚠️'} across walk-forward test")
