import json, time, requests
from collections import deque
from datetime import datetime, timezone

# === MERGED CONFIG V8.3 + V5.3 ===
SYMBOL = "XAUUSD"
LOOKBACK = 20
TOUCH_PERC = 0.5  # your V5.3 50% invasion
EXPIRY_SEC = 300  # 5 min expiry (GitHub cron)

# Load history
try:
    with open("candles.json","r") as f:
        hist=json.load(f)
        candles=deque(hist.get("candles",[]), maxlen=100)
        ticks_buffer=deque(hist.get("ticks",[]), maxlen=100)
        active_sweep=hist.get("active_sweep",{"type":None,"fifty":0,"ignition_vol":0,"time":0})
        bal=hist.get("bal",10000)
        pos=hist.get("pos",[])
        bullets=hist.get("bullets",0)
except:
    candles=deque(maxlen=100); ticks_buffer=deque(maxlen=100)
    active_sweep={"type":None,"fifty":0,"ignition_vol":0,"time":0}
    bal=10000; pos=[]; bullets=0

def get_xau():
    try:
        r=requests.get("https://api.gold-api.com/price/XAU",timeout=10).json()
        return float(r['price'])
    except: return 4027.5

def avg_vol():
    if len(ticks_buffer)<20: return 1
    return sum(ticks_buffer)/len(ticks_buffer)

# === POLL XAU (simulating OnTick) ===
xau=get_xau()
candles.append(xau)
ticks_buffer.append(1)  # each cron = 1 tick bucket, builds real volume

if len(candles) < LOOKBACK+2:
    status={"xau":xau,"htf_regime":"BUILDING","htf_sweep":"NO SWEEP","signal":"WAIT","bal":bal,"pos":pos,"last_check":str(datetime.now())}
else:
    recent_low=min(list(candles)[-LOOKBACK-1:-1])
    recent_high=max(list(candles)[-LOOKBACK-1:-1])
    curr_high=max(list(candles)[-2:])
    curr_low=min(list(candles)[-2:])

    is_bear_sweep=curr_high>recent_high
    is_bull_sweep=curr_low<recent_low

    avg=avg_vol()
    ignition_vol=ticks_buffer[-2] if len(ticks_buffer)>2 else avg
    confirmation_vol=ticks_buffer[-1] if len(ticks_buffer)>1 else avg

    # === V5.3 CAPTURE SWEEP (YOUR LOGIC) ===
    if is_bear_sweep and active_sweep["type"] is None:
        sweep_low=min(list(candles)[-5:])
        fifty=curr_high - (curr_high - sweep_low)*TOUCH_PERC
        active_sweep={"type":"BEAR","fifty":fifty,"ignition_vol":ignition_vol,"time":time.time()}
        print(f"SWEEP CAPTURED: BEAR High {curr_high:.2f} Fifty {fifty:.2f} Vol {ignition_vol}")

    if is_bull_sweep and active_sweep["type"] is None:
        sweep_high=max(list(candles)[-5:])
        fifty=curr_low + (sweep_high - curr_low)*TOUCH_PERC
        active_sweep={"type":"BULL","fifty":fifty,"ignition_vol":ignition_vol,"time":time.time()}
        print(f"SWEEP CAPTURED: BULL Low {curr_low:.2f} Fifty {fifty:.2f} Vol {ignition_vol}")

    # === V5.3 WAIT FOR 50% INVASION TOUCH ===
    signal="BALANCE RANDOM"
    ghost_confirmed=False

    if active_sweep["type"]=="BEAR":
        fifty=active_sweep["fifty"]
        high_vol=active_sweep["ignition_vol"]>avg*1.5
        # Touch invasion = price bounces to 50% then rejects
        touch_invasion = (xau>=fifty*0.998 and xau < fifty*1.002) or (max(list(candles)[-3:])>=fifty and xau < fifty)
        
        if touch_invasion:
            if high_vol and confirmation_vol < avg:
                signal="🔴 GHOST SHORT - 50% INVASION"
                ghost_confirmed=True
                print(f"GHOST SHORT - Level {fifty:.2f} Price {xau:.2f} Ignition HIGH({active_sweep['ignition_vol']}) -> Confirm LOW({confirmation_vol})")
            elif confirmation_vol > avg*1.2:
                print(f"STATE B SKIP - trend running, invasion trap avoided")
                active_sweep={"type":None,"fifty":0,"ignition_vol":0,"time":0}

    if active_sweep["type"]=="BULL":
        fifty=active_sweep["fifty"]
        high_vol=active_sweep["ignition_vol"]>avg*1.5
        touch_invasion = (xau<=fifty*1.002 and xau > fifty*0.998) or (min(list(candles)[-3:])<=fifty and xau > fifty)
        if touch_invasion:
            if high_vol and confirmation_vol < avg:
                signal="🟢 GHOST LONG - 50% INVASION"
                ghost_confirmed=True

    # Expire after 5 min if no touch (GitHub cron)
    if active_sweep["type"] and time.time()-active_sweep["time"]>EXPIRY_SEC:
        active_sweep={"type":None,"fifty":0,"ignition_vol":0,"time":0}

    # === DELPHIAN MERGE: bullets + TP/SL ===
    if ghost_confirmed and bullets<2 and not pos:
        if "SHORT" in signal:
            pos.append({"pair":SYMBOL,"type":"SELL","entry":xau,"sl":xau+5,"tp":xau-8,"fifty":fifty})
        else:
            pos.append({"pair":SYMBOL,"type":"BUY","entry":xau,"sl":xau-5,"tp":xau+8,"fifty":fifty})
        bullets+=1
        active_sweep={"type":None,"fifty":0,"ignition_vol":0,"time":0}

    # Check TP/SL
    new_pos=[]
    for p in pos:
        hit=False
        if p['type']=='SELL' and (xau<=p['tp'] or xau>=p['sl']): hit=True
        if p['type']=='BUY' and (xau>=p['tp'] or xau<=p['sl']): hit=True
        if hit:
            pnl=(p['entry']-xau)*90 if p['type']=='SELL' else (xau-p['entry'])*90
            bal+=pnl
        else: new_pos.append(p)
    pos=new_pos

    status={
        "xau":xau,
        "htf_regime":f"AVG VOL {avg:.1f} | IGN {ignition_vol} CONF {confirmation_vol}",
        "htf_sweep": f"{active_sweep['type']} SWEEP Fifty {active_sweep['fifty']:.2f}" if active_sweep["type"] else "NO SWEEP - STAY OUT",
        "breath": "BEAR INVASION" if active_sweep["type"]=="BEAR" else "BULL INVASION" if active_sweep["type"]=="BULL" else "NONE",
        "bumps_hh_lh":0,
        "bumps_ll_hl":0,
        "valley_top": "TOUCH WAIT" if active_sweep["type"] else "EXPIRED" if signal=="BALANCE RANDOM" else "CONFIRMED",
        "atr_ltf":f"{TOUCH_PERC*100}% INVASION",
        "atr_htf":f"IGN {active_sweep['ignition_vol']}>AVG*1.5 ? {active_sweep['ignition_vol']>avg*1.5}",
        "bullets":f"{bullets}/2",
        "signal":signal,
        "bal":round(bal,2),
        "pos":pos,
        "server":"BEAST V5.3 INVASION + V8.3 FREE",
        "last_check":str(datetime.now()),
        "ny":True,
        "fifty":active_sweep["fifty"]
    }

# SAVE FOR V6 APP TRACKING
with open("status.json","w") as f: json.dump(status,f,indent=2)
with open("candles.json","w") as f: json.dump({"candles":list(candles),"ticks":list(ticks_buffer),"active_sweep":active_sweep,"bal":bal,"pos":pos,"bullets":bullets},f)

print(json.dumps(status,indent=2))
