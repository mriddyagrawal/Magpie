"""HotpotQA prompt-ordering x grammar. Text-only: no mtmd, direct token control.

Components are tokenized INDEPENDENTLY and concatenated, so STD and SDT are
exact anagrams by construction (identical token-ID multisets), not merely
equal-length. Same reason mtmd's image sentinels gave clean boundaries in the
POPE run - here we make that guarantee explicit.
"""
import os, sys, json, time, ctypes as C
sys.path.insert(0, "/root/bench")
from lfm import (llama, c_i32, c_u32, c_vp, llama_token, llama_pos,
                 llama_model_params, llama_context_params)

GGUF = os.environ.get("GGUF_PATH", "/root/models/LFM2.5-VL-3B-Q6_K.gguf")
GRAMMAR = open("/root/bench/magpie_answer.gbnf").read()

# Identical across all six conditions. States the JSON contract so the
# grammar-off arm has a fair chance of producing the same shape; says nothing
# about a document, a question, or their order.
SYSTEM = ('Answer using only the provided material. Reply with a single JSON object: '
          '{"answer": string, "sources_used": [string], "not_found": boolean, '
          '"not_found_topic": string}. Keep "answer" short and factual.')

class llama_sampler_chain_params(C.Structure):
    _fields_ = [("no_perf", C.c_bool)]

llama.llama_sampler_chain_default_params.restype = llama_sampler_chain_params
llama.llama_sampler_chain_init.argtypes = [llama_sampler_chain_params]
llama.llama_sampler_chain_init.restype = c_vp
llama.llama_sampler_chain_add.argtypes = [c_vp, c_vp]
llama.llama_sampler_init_grammar.argtypes = [c_vp, C.c_char_p, C.c_char_p]
llama.llama_sampler_init_grammar.restype = c_vp
llama.llama_tokenize.argtypes = [c_vp, C.c_char_p, c_i32, C.POINTER(llama_token), c_i32, C.c_bool, C.c_bool]
llama.llama_tokenize.restype = c_i32
llama.llama_sampler_free.argtypes = [c_vp]

class TextRunner:
    def __init__(self, n_ctx=24576, n_threads=8):
        llama.llama_backend_init()
        mp = llama.llama_model_default_params(); mp.n_gpu_layers = -1
        self.model = llama.llama_model_load_from_file(GGUF.encode(), mp)
        if not self.model: raise RuntimeError("model load failed")
        cp = llama.llama_context_default_params()
        cp.n_ctx, cp.n_batch, cp.n_ubatch, cp.n_seq_max = n_ctx, 2048, 512, 1
        cp.n_threads = cp.n_threads_batch = n_threads
        self.ctx = llama.llama_init_from_model(self.model, cp)
        if not self.ctx: raise RuntimeError("ctx init failed")
        self.vocab = llama.llama_model_get_vocab(self.model)
        self.mem = llama.llama_get_memory(self.ctx)

    def tok(self, s, special=True):
        b = s.encode(); cap = len(b) + 64
        buf = (llama_token * cap)()
        n = llama.llama_tokenize(self.vocab, b, len(b), buf, cap, False, special)
        if n < 0: raise RuntimeError(f"tokenize overflow {n}")
        return [buf[i] for i in range(n)]

    def piece(self, t):
        buf = C.create_string_buffer(256)
        n = llama.llama_token_to_piece(self.vocab, t, buf, 256, 0, True)
        return buf.raw[:n].decode("utf-8", "replace") if n > 0 else ""

    def build(self, question, doc, ordering):
        P0 = self.tok("<|startoftext|><|im_start|>system\n" + SYSTEM + "<|im_end|>\n<|im_start|>user\n")
        Q  = self.tok(question.strip() + "\n\n", special=False)
        D  = self.tok(doc.strip() + "\n\n", special=False)
        P1 = self.tok("<|im_end|>\n<|im_start|>assistant\n")
        if   ordering == "STD":  mid = Q + D
        elif ordering == "SDT":  mid = D + Q
        elif ordering == "STDT": mid = Q + D + Q
        else: raise ValueError(ordering)
        return P0 + mid + P1, {"P0": len(P0), "Q": len(Q), "D": len(D), "P1": len(P1)}

    def gen(self, tokens, grammar_on, max_new=128):
        llama.llama_memory_clear(self.mem, True)
        arr = (llama_token * len(tokens))(*tokens)
        n = len(tokens)
        # prefill in n_batch chunks
        i = 0
        while i < n:
            k = min(2048, n - i)
            sub = (llama_token * k)(*tokens[i:i+k])
            if llama.llama_decode(self.ctx, llama.llama_batch_get_one(sub, k)) != 0:
                raise RuntimeError("decode failed during prefill")
            i += k
        chain = llama.llama_sampler_chain_init(llama.llama_sampler_chain_default_params())
        gsmpl = None
        if grammar_on:
            gsmpl = llama.llama_sampler_init_grammar(self.vocab, GRAMMAR.encode(), b"root")
            if not gsmpl: raise RuntimeError("grammar init failed")
            llama.llama_sampler_chain_add(chain, gsmpl)
        llama.llama_sampler_chain_add(chain, llama.llama_sampler_init_greedy())
        out, ids = "", []
        for _ in range(max_new):
            t = llama.llama_sampler_sample(chain, self.ctx, -1)
            if llama.llama_vocab_is_eog(self.vocab, t): break
            # NOTE: llama_sampler_sample() already calls llama_sampler_accept()
            # internally (llama-sampler.cpp). Calling it again double-advances
            # stateful samplers and empties the grammar stack.
            out += self.piece(t); ids.append(t)
            one = (llama_token * 1)(t)
            if llama.llama_decode(self.ctx, llama.llama_batch_get_one(one, 1)) != 0: break
        llama.llama_sampler_free(chain)
        return out, ids

    def close(self):
        for fn, h in ((llama.llama_free, "ctx"), (llama.llama_model_free, "model")):
            p = getattr(self, h, None)
            if p:
                try: fn(p)
                except Exception: pass
                setattr(self, h, None)
        try: llama.llama_backend_free()
        except Exception: pass

if __name__ == "__main__":
    WID, NW = int(os.environ["WID"]), int(os.environ["NW"])
    items = json.load(open("/root/bench/hotpot_500.json"))["items"]
    LIMIT = int(os.environ.get("LIMIT", "0"))
    if LIMIT: items = items[:LIMIT]
    CONDS = [(o, g) for o in ("STD", "SDT", "STDT") for g in (False, True)]
    jobs = [(n, it, o, g) for n, it in enumerate(items) for (o, g) in CONDS]
    mine = [j for k, j in enumerate(jobs) if k % NW == WID]
    r = TextRunner(n_ctx=24576)
    outp = open(f"/root/bench/out/results_w{WID}.jsonl", "a")
    stat = f"/root/bench/out/status_w{WID}.json"
    t0 = time.time()
    for k, (n, it, o, g) in enumerate(mine):
        toks, parts = r.build(it["question"], it["context"], o)
        try:
            text, ids = r.gen(toks, g)
            err = None
        except Exception as e:
            text, ids, err = "", [], f"{type(e).__name__}: {e}"
        outp.write(json.dumps({"id": it["id"], "ordering": o, "grammar": g,
                               "bin": it["bin"], "ctx_words": it["ctx_words"],
                               "question": it["question"], "answers": it["answers"],
                               "n_tokens": len(toks), "parts": parts,
                               "output": text, "n_out": len(ids), "error": err}) + "\n")
        outp.flush()
        el = time.time() - t0
        json.dump({"wid": WID, "done": k + 1, "total": len(mine), "elapsed": el,
                   "rate": (k + 1) / el, "eta": (len(mine) - k - 1) / ((k + 1) / el),
                   "current": f"{o}/{'gram' if g else 'nogram'} {it['bin']}"}, open(stat, "w"))
    outp.close(); r.close(); sys.stdout.flush(); os._exit(0)
