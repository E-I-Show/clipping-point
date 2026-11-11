from sim import *
import math, collections, sys
CORN=[("T1",152.5,285.3),("T2",325.3,428.2),("T3",453.2,527.7),("T4",587.7,650.7),("T5",670.7,767.5),("T6",1003.4,1110.7),("T7",1180.7,1239.8),("T8",1284.8,1426.3),("T9",1484.1,1680.0)]
def corner(s):
    for n,a,b in CORN:
        if a-40<=s<=b+40: return n
    return "str"
def diag(cid, analog, kw, laps=3, mode="full", levels=None, tweak=None, ndetail=6, back=(60,30)):
    assist = InputAssist(levels, preset="analog" if analog else "digital", assist_on=(mode=="full")) if mode!="raw" else PassThrough()
    for k,v in (tweak or {}).items(): setattr(assist,k,v)
    drv = Driver(cid, analog, seed=1, **kw); drv.assist_ref=assist
    w = World(cid, assist)
    ev=collections.Counter(); prev=(0,0,0,0)
    detail=[]; hist=[]
    for i in range(60*400):
        st, th, bk = drv.decide(w.car, w.q, w.tick)
        w.step(st, th, bk, analog, analog)
        c=w.car; q=w.q
        cn=corner(q.s)
        hist.append((round(q.s),round(q.d,1),"v",round(c.speed*3.6),"vt",round(drv.v_target(q.s)*3.6),"in",st,th,bk,"out",round(getattr(assist,'thr_out',th),2),round(getattr(assist,'brk_out',bk),2),"beta",round(math.degrees(c.body_slip)),"steer",round(c.steer,3),"lim",round(assist.limit,3),"syf",round(max(abs(c.wheel_sy[0]),abs(c.wheel_sy[1])),2),"syr",round(max(abs(c.wheel_sy[2]),abs(c.wheel_sy[3])),2),"g",round(c.ay/9.81,2),q.surface[:3],"cs",int(assist.counter)))
        cur=(w.spins,w.off2,w.walls,w.resets)
        if cur!=prev:
            kind="spin" if cur[0]!=prev[0] else ("off" if cur[1]!=prev[1] else ("wall" if cur[2]!=prev[2] else "reset"))
            ev[(cn,kind)]+=1
            if len(detail)<ndetail:
                detail.append((kind,cn,"lap",w.laps.lap))
                for b in back:
                    if len(hist)>b: detail.append(("   -%d"%b,)+hist[-b-1])
                detail.append(("   now",)+hist[-1])
            prev=cur
        if w.laps.lap>=laps+1: break
    print(cid, "analog" if analog else "digital", mode, kw, [round(t,1) for t in w.laps.lap_times])
    print("  incidents:", dict(ev))
    for d in detail: print("   ", *d)
if __name__=="__main__":
    diag("shirogane", False, {"look_t":0.9,"dig_th":0.2})
    diag("kazane", False, {"look_t":0.9,"dig_th":0.2})
