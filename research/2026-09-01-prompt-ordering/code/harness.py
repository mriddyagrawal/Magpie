"""LFM2.5-VL-3B Q6_K prompt-ordering harness. Greedy, single-stream, mtmd chunk-level control."""
import ctypes as C, os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lfm import (llama, mtmd, llama_model_params, llama_context_params, mtmd_context_params,
                 mtmd_input_text, llama_token, llama_pos, CHUNK_TEXT, CHUNK_IMAGE)
from PIL import Image

GGUF   = os.environ.get("GGUF_PATH", "/root/models/LFM2.5-VL-3B-Q6_K.gguf")
MMPROJ = os.environ.get("MMPROJ_PATH", "/root/models/mmproj-LFM2.5-VL-3B-Q8_0.gguf")
MARKER = "<__media__>"

# ONE fixed system prompt, byte-identical across every run and every ordering.
# Deliberately neutral: says nothing about an image, a question, or their order.
SYSTEM = "Answer the user with a single word: yes or no."

def build_prompt(question: str, ordering: str) -> str:
    """ChatML scaffolding per LFM2.5-VL chat template. Only CONTENT arrangement varies."""
    if   ordering == "STI":  content = question + MARKER
    elif ordering == "SIT":  content = MARKER + question
    elif ordering == "STIT": content = question + MARKER + question
    else: raise ValueError(ordering)
    return ("<|startoftext|><|im_start|>system\n" + SYSTEM + "<|im_end|>\n"
            "<|im_start|>user\n" + content + "<|im_end|>\n<|im_start|>assistant\n")

class Runner:
    def __init__(self, n_ctx=4096, n_threads=8, verbose=False):
        if not verbose:
            os.close(2) if False else None
        llama.llama_backend_init()
        mp = llama.llama_model_default_params(); mp.n_gpu_layers = -1
        self.model = llama.llama_model_load_from_file(GGUF.encode(), mp)
        if not self.model: raise RuntimeError("model load failed")
        cp = llama.llama_context_default_params()
        cp.n_ctx, cp.n_batch, cp.n_ubatch, cp.n_seq_max = n_ctx, 2048, 512, 1
        cp.n_threads = cp.n_threads_batch = n_threads
        self.n_batch = 2048
        self.ctx = llama.llama_init_from_model(self.model, cp)
        if not self.ctx: raise RuntimeError("context init failed")
        self.vocab = llama.llama_model_get_vocab(self.model)
        self.mem = llama.llama_get_memory(self.ctx)
        tp = mtmd.mtmd_context_params_default(); tp.use_gpu = True; tp.n_threads = n_threads
        tp.print_timings = False
        self.mctx = mtmd.mtmd_init_from_file(MMPROJ.encode(), self.model, tp)
        if not self.mctx: raise RuntimeError("mtmd init failed")
        self.smpl = llama.llama_sampler_init_greedy()   # pure argmax, no other samplers

    def piece(self, tok):
        buf = C.create_string_buffer(256)
        n = llama.llama_token_to_piece(self.vocab, tok, buf, 256, 0, True)
        return buf.raw[:n].decode("utf-8", "replace") if n > 0 else ""

    def bitmap(self, img: Image.Image):
        img = img.convert("RGB"); a = np.asarray(img, dtype=np.uint8)
        buf = (C.c_ubyte * a.size).from_buffer_copy(a.tobytes())
        return mtmd.mtmd_bitmap_init(img.width, img.height, buf)

    def tokenize(self, prompt: str, img: Image.Image):
        chunks = mtmd.mtmd_input_chunks_init()
        it = mtmd_input_text(prompt.encode(), len(prompt.encode()), False, True)  # add_special=F, parse_special=T
        bm = self.bitmap(img)
        arr = (C.c_void_p * 1)(bm)
        rc = mtmd.mtmd_tokenize(self.mctx, chunks, C.byref(it), arr, 1)
        mtmd.mtmd_bitmap_free(bm)
        if rc != 0:
            mtmd.mtmd_input_chunks_free(chunks)
            raise RuntimeError(f"mtmd_tokenize rc={rc} (1=marker/bitmap mismatch, 2=image preproc error)")
        return chunks

    def inspect(self, chunks):
        out = []
        for i in range(mtmd.mtmd_input_chunks_size(chunks)):
            ch = mtmd.mtmd_input_chunks_get(chunks, i)
            t  = mtmd.mtmd_input_chunk_get_type(ch)
            n  = mtmd.mtmd_input_chunk_get_n_tokens(ch)
            rec = {"idx": i, "type": {0:"TEXT",1:"IMAGE",2:"AUDIO"}[t], "n_tokens": n,
                   "n_pos": mtmd.mtmd_input_chunk_get_n_pos(ch)}
            if t == CHUNK_TEXT:
                cnt = C.c_size_t()
                p = mtmd.mtmd_input_chunk_get_tokens_text(ch, C.byref(cnt))
                ids = [p[j] for j in range(cnt.value)]
                rec["token_ids"] = ids
                rec["pieces"] = [self.piece(x) for x in ids]
            out.append(rec)
        return out

    def generate(self, chunks, max_new=16):
        llama.llama_memory_clear(self.mem, True)
        n_past = llama_pos(0)
        rc = mtmd.mtmd_helper_eval_chunks(self.mctx, self.ctx, chunks, 0, 0,
                                          self.n_batch, True, C.byref(n_past))
        if rc != 0: raise RuntimeError(f"eval_chunks rc={rc}")
        toks, text = [], ""
        for _ in range(max_new):
            tok = llama.llama_sampler_sample(self.smpl, self.ctx, -1)
            if llama.llama_vocab_is_eog(self.vocab, tok): break
            toks.append(tok); text += self.piece(tok)
            llama.llama_sampler_accept(self.smpl, tok)
            one = (llama_token * 1)(tok)
            if llama.llama_decode(self.ctx, llama.llama_batch_get_one(one, 1)) != 0:
                raise RuntimeError("decode failed")
            n_past.value += 1
        return text, toks

    def close(self):
        """Explicit teardown in reverse construction order. Without this, ggml's Metal
        device destructor runs at interpreter exit with live resource sets still
        outstanding and calls ggml_abort() -> SIGABRT. Data is already flushed by then,
        but it leaves a spurious crash report. Pair with os._exit(0) to skip finalizers."""
        for fn, h in ((mtmd.mtmd_free, "mctx"), (llama.llama_free, "ctx"),
                      (llama.llama_model_free, "model")):
            p = getattr(self, h, None)
            if p:
                try: fn(p)
                except Exception: pass
                setattr(self, h, None)
        try: llama.llama_backend_free()
        except Exception: pass

    def run(self, question, img, ordering, max_new=16):
        prompt = build_prompt(question, ordering)
        chunks = self.tokenize(prompt, img)
        try:
            info = self.inspect(chunks)
            text, toks = self.generate(chunks, max_new)
        finally:
            mtmd.mtmd_input_chunks_free(chunks)
        return {"ordering": ordering, "prompt": prompt, "chunks": info,
                "total_tokens": sum(c["n_tokens"] for c in info),
                "output": text, "out_token_ids": toks}
