import json, time, os, sys, threading, queue
import requests
SP = os.path.dirname(os.path.abspath(__file__))
KEY = open(os.path.expanduser("~/.openrouter_key")).read().strip()
MODEL, PROVIDER, NWORK = "google/gemma-4-26b-a4b-it", "DeepInfra", 12
SYSTEM = ('Answer using only the provided material. Reply with a single JSON object: '
          '{"answer": string, "sources_used": [string], "not_found": boolean, '
          '"not_found_topic": string}. Keep "answer" short and factual.')

def build(q, d, o):
    q = q.strip() + "\n\n"; d = d.strip() + "\n\n"
    return {"STD": q + d, "SDT": d + q, "STDT": q + d + q}[o]

def call(content, tries=4):
    for a in range(tries):
        try:
            r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
                json={"model": MODEL, "provider": {"order":[PROVIDER], "allow_fallbacks": False},
                      "messages":[{"role":"system","content":SYSTEM},
                                  {"role":"user","content":content}],
                      "temperature": 0, "seed": 0, "max_tokens": 128}, timeout=300)
            if r.status_code == 200:
                j = r.json()
                if "error" not in j:
                    ch = j["choices"][0]; u = j.get("usage") or {}
                    return {"text": ch["message"]["content"], "in": u.get("prompt_tokens"),
                            "out": u.get("completion_tokens"), "finish": ch.get("finish_reason"),
                            "by": j.get("provider"), "err": None}
                last = str(j["error"])[:200]
            else:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"[:200]
        time.sleep(2 ** a)
    return {"text": "", "in": None, "out": None, "finish": None, "by": None, "err": last}

items = json.load(open(SP + "/hotpot_500.json"))["items"]
jobs = [(it, o) for it in items for o in ("STD", "SDT", "STDT")]
q = queue.Queue(); [q.put(j) for j in jobs]
out = open(SP + "/or_results.jsonl", "w"); lock = threading.Lock()
t0 = time.time(); done = [0]; errs = [0]

def worker():
    while True:
        try: it, o = q.get_nowait()
        except queue.Empty: return
        r = call(build(it["question"], it["context"], o))
        with lock:
            out.write(json.dumps({"id": it["id"], "ordering": o, "bin": it["bin"],
                "ctx_words": it["ctx_words"], "question": it["question"],
                "answers": it["answers"], "output": r["text"], "n_in": r["in"],
                "n_out": r["out"], "finish": r["finish"], "by": r["by"],
                "error": r["err"]}) + "\n"); out.flush()
            done[0] += 1
            if r["err"]: errs[0] += 1
            if done[0] % 50 == 0:
                el = time.time() - t0
                json.dump({"done": done[0], "total": len(jobs), "elapsed": el,
                           "rate": done[0]/el, "eta": (len(jobs)-done[0])/(done[0]/el),
                           "errors": errs[0]}, open(SP + "/or_status.json", "w"))
                print(f"{done[0]}/{len(jobs)}  {done[0]/el:.2f}/s  eta={(len(jobs)-done[0])/(done[0]/el)/60:.1f}m  err={errs[0]}", flush=True)
        q.task_done()

ts = [threading.Thread(target=worker, daemon=True) for _ in range(NWORK)]
[t.start() for t in ts]; [t.join() for t in ts]
out.close()
print(f"\nDONE {done[0]} requests in {(time.time()-t0)/60:.1f} min, errors={errs[0]}")
