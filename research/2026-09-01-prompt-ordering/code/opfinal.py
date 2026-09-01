import json, glob, collections, random, os
from scipy.stats import binomtest
SP = os.path.dirname(os.path.abspath(__file__))
pool = {p["uid"]: p for p in json.load(open(SP+"/pool_all.json"))}
V = {}
for f in glob.glob(SP+"/opjudge/verdict*.json"):
    for v in json.load(open(f)):
        V[v["uid"]] = (v["correct"], v.get("code","?").strip("[]"))
print(f"verdicts={len(V)}  pool={len(pool)}  all covered={set(V)==set(pool)}")
for u,(c,code) in V.items():
    pool[u]["correct"]=c; pool[u]["code"]=code

M = {"gemma":collections.defaultdict(dict), "lfm":collections.defaultdict(dict)}
for p in pool.values(): M[p["model"]][p["id"]][p["ordering"]] = p
ids = sorted(M["gemma"])
def acc(m,o): return sum(M[m][i][o]["correct"] for i in ids)/len(ids)
def mc(m,A,B):
    n01=sum(1 for i in ids if M[m][i][A]["correct"]==1 and M[m][i][B]["correct"]==0)
    n10=sum(1 for i in ids if M[m][i][A]["correct"]==0 and M[m][i][B]["correct"]==1)
    return n01,n10,(binomtest(n01,n01+n10,0.5).pvalue if n01+n10 else 1.0)
def boot(m,A,B,N=5000,seed=0):
    rnd=random.Random(seed); a=[M[m][i][A]["correct"] for i in ids]; b=[M[m][i][B]["correct"] for i in ids]
    n=len(ids); d=[]
    for _ in range(N):
        s=[rnd.randrange(n) for _ in range(n)]
        d.append(sum(b[j] for j in s)/n-sum(a[j] for j in s)/n)
    d.sort(); return d[int(.025*N)],d[int(.975*N)]

print("\n"+"="*70)
print(f"{'ordering':<26}{'Gemma 4 26B':>14}{'LFM2.5-VL-3B':>16}{'gap':>12}")
print("="*70)
for o,lab in (("STD","STD  question first"),("SDT","SDT  document first"),("STDT","STDT question both")):
    g,l=acc("gemma",o),acc("lfm",o)
    print(f"{lab:<26}{g:>14.4f}{l:>16.4f}{g-l:>+12.4f}")
print("="*70)

print("\nORDERING EFFECTS (uniform Opus judging)")
for m in ("gemma","lfm"):
    print(f"\n  {m.upper()}")
    for A,B in (("STD","SDT"),("SDT","STDT"),("STD","STDT")):
        d=acc(m,B)-acc(m,A); n01,n10,p=mc(m,A,B); lo,hi=boot(m,A,B)
        print(f"    {A:>4} -> {B:<5} {d:+.4f}  disc={n01+n10:>3} ({n01}/{n10})  p={p:.2e}  CI=[{lo:+.4f},{hi:+.4f}]  {'SIG' if p<0.05 else 'null'}")

print("\nFAILURE MODES by model (all 1500 each)")
codes=sorted({p["code"] for p in pool.values()})
print(f"{'code':<18}{'Gemma':>8}{'LFM':>8}")
for c in codes:
    g=sum(1 for p in pool.values() if p["model"]=="gemma" and p["code"]==c)
    l=sum(1 for p in pool.values() if p["model"]=="lfm" and p["code"]==c)
    if g+l>0: print(f"{c:<18}{g:>8}{l:>8}")

print("\nSTYLE-BIAS CHECK (were verbose answers over-credited?)")
for m in ("gemma","lfm"):
    tv=sum(1 for p in pool.values() if p["model"]==m and p["code"]=="CORRECT_VERBOSE")
    tt=sum(1 for p in pool.values() if p["model"]==m and p["code"]=="CORRECT_TERSE")
    print(f"  {m:<6} correct-verbose={tv:>4}  correct-terse={tt:>4}")

print("\nBY LENGTH (each model, best ordering)")
for b in ("0-4k","4-8k","8k+"):
    sub=[i for i in ids if M["gemma"][i]["STD"]["bin"]==b]
    row=[]
    for m in ("gemma","lfm"):
        v=[sum(M[m][i][o]["correct"] for i in sub)/len(sub) for o in ("STD","SDT","STDT")]
        row.append(v)
    print(f"  {b:<6} n={len(sub):>3}  Gemma STD/SDT/STDT={row[0][0]:.3f}/{row[0][1]:.3f}/{row[0][2]:.3f}   LFM={row[1][0]:.3f}/{row[1][1]:.3f}/{row[1][2]:.3f}")
json.dump(list(pool.values()), open(SP+"/opus_final.json","w"))
