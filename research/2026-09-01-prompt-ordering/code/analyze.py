import sys,os,json,random
SP=os.path.dirname(os.path.abspath(__file__))
from scipy.stats import binomtest
ORD=["STI","SIT","STIT"]
CLEAN={"yes":"yes","no":"no","yes.":"yes","no.":"no"}
recs=[json.loads(l) for l in open(SP+"/results.jsonl")]
print(f"items={len(recs)}  generations={len(recs)*3}")

# ---- exact-match scoring; anything not exactly matching escalates ----
esc=[]
for r in recs:
    for o in ORD:
        raw=r["arms"][o]["output"]
        k=raw.strip().lower()
        if k in CLEAN: r["arms"][o]["label"]=CLEAN[k]
        else: r["arms"][o]["label"]=None; esc.append((r["id"],o,raw))
print(f"exact-matched={len(recs)*3-len(esc)}  ESCALATED={len(esc)}")
if esc:
    from collections import Counter
    print("escalation raw outputs:",Counter(x[2] for x in esc).most_common(20))
json.dump([{"id":i,"arm":o,"raw":raw} for i,o,raw in esc],open(SP+"/escalations.json","w"),indent=1)

# ---- per-item correctness, paired ----
def corr(r,o):
    l=r["arms"][o]["label"]
    return None if l is None else int(l==r["gold"])
C={o:[corr(r,o) for r in recs] for o in ORD}
n=len(recs)

def acc(v): 
    ok=[x for x in v if x is not None]; return sum(ok)/len(v)   # unparseable counts wrong
def prf(o):
    tp=sum(1 for r in recs if r["arms"][o]["label"]=="yes" and r["gold"]=="yes")
    fp=sum(1 for r in recs if r["arms"][o]["label"]=="yes" and r["gold"]=="no")
    fn=sum(1 for r in recs if r["arms"][o]["label"]!="yes" and r["gold"]=="yes")
    p=tp/(tp+fp) if tp+fp else 0; rc=tp/(tp+fn) if tp+fn else 0
    return p,rc,(2*p*rc/(p+rc) if p+rc else 0)
def yesrate(o): return sum(1 for r in recs if r["arms"][o]["label"]=="yes")/n

print("\n"+"="*72)
print(f"{'ordering':<8}{'accuracy':>10}{'precision':>11}{'recall':>9}{'F1':>9}{'yes-rate':>10}{'unparse':>9}")
print("="*72)
for o in ORD:
    p,rc,f1=prf(o); u=sum(1 for r in recs if r["arms"][o]["label"] is None)
    print(f"{o:<8}{acc(C[o]):>10.4f}{p:>11.4f}{rc:>9.4f}{f1:>9.4f}{yesrate(o):>10.4f}{u:>9}")
print("="*72)
print(f"gold yes-rate = {sum(1 for r in recs if r['gold']=='yes')/n:.4f}")

def mcnemar(a,b):
    n01=sum(1 for x,y in zip(a,b) if x==1 and y==0)
    n10=sum(1 for x,y in zip(a,b) if x==0 and y==1)
    if n01+n10==0: return n01,n10,1.0
    return n01,n10,binomtest(n01,n01+n10,0.5,alternative='two-sided').pvalue
def boot(a,b,B=5000,seed=0):
    rnd=random.Random(seed); idx=range(len(a)); d=[]
    for _ in range(B):
        s=[rnd.randrange(len(a)) for _ in idx]
        d.append(sum(b[i] for i in s)/len(s)-sum(a[i] for i in s)/len(s))
    d.sort(); return d[int(.025*B)], d[int(.975*B)]
print("\nPAIRED COMPARISONS  (delta = second minus first)")
for x,y in [("STI","SIT"),("SIT","STIT")]:
    a=[0 if v is None else v for v in C[x]]; b=[0 if v is None else v for v in C[y]]
    d=acc(C[y])-acc(C[x]); n01,n10,p=mcnemar(a,b); lo,hi=boot(a,b)
    print(f"\n  {x} -> {y}")
    print(f"    delta accuracy      = {d:+.4f}")
    print(f"    discordant pairs    = {n01+n10}  ({x}-only-correct={n01}, {y}-only-correct={n10})")
    print(f"    McNemar exact 2side = p = {p:.4f}")
    print(f"    bootstrap 95% CI    = [{lo:+.4f}, {hi:+.4f}]  (5000 resamples, paired by item)")
    print(f"    verdict             = {'SIGNIFICANT' if p<0.05 else 'NULL (no detectable effect)'}")
# integrity
mm=[r for r in recs if not r.get("anagram_ok")]
print(f"\nINTEGRITY: token-count STI==SIT on {len(recs)-len(mm)}/{len(recs)} items; mismatches={len(mm)}")
it=set(tuple(r["arms"][o]["img_tokens"]) for r in recs for o in ORD)
print(f"  distinct image-token counts across all arms: {sorted(x[0] for x in it)}")
json.dump({"per_item":[{"id":r["id"],"question":r["question"],"gold":r["gold"],
    "image_source":r["image_source"],
    "arms":{o:{"output":r["arms"][o]["output"],"label":r["arms"][o]["label"],
               "correct":corr(r,o),"total_tokens":r["arms"][o]["total_tokens"]} for o in ORD}}
    for r in recs]}, open(SP+"/per_item.json","w"), indent=1)
print("\nwrote per_item.json, escalations.json")
