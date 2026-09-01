"""ctypes binding to llama.cpp b10502 / 0adcc3bb5. Portable: macOS (Metal) + Linux (CUDA).
Struct layouts transcribed from headers at that exact commit, so the same
definitions are valid on both platforms - which is why the build is pinned."""
import ctypes as C, os, sys, platform

_MAC = platform.system() == "Darwin"
EXT  = ".dylib" if _MAC else ".so"
BIN  = os.environ.get("LLAMA_BIN") or (
    "/Users/mriddy/Library/Application Support/Magpie/bin" if _MAC
    else "/root/llama.cpp/build/bin")
os.environ["DYLD_LIBRARY_PATH"] = BIN + ":" + os.environ.get("DYLD_LIBRARY_PATH","")
os.environ["LD_LIBRARY_PATH"]   = BIN + ":" + os.environ.get("LD_LIBRARY_PATH","")

for _n in ["libggml-base","libggml-cpu","libggml-metal","libggml-cuda","libggml-blas","libggml"]:
    _p = os.path.join(BIN, _n + EXT)
    if os.path.exists(_p):
        try: C.CDLL(_p, mode=C.RTLD_GLOBAL)
        except OSError as e: print(f"  warn: {_n}: {e}", file=sys.stderr)
llama = C.CDLL(os.path.join(BIN, "libllama" + EXT), mode=C.RTLD_GLOBAL)
mtmd  = C.CDLL(os.path.join(BIN, "libmtmd"  + EXT), mode=C.RTLD_GLOBAL)

c_i32, c_u32, c_f, c_vp, c_cp = C.c_int32, C.c_uint32, C.c_float, C.c_void_p, C.c_char_p
llama_token = c_i32; llama_pos = c_i32; llama_seq_id = c_i32

class llama_model_params(C.Structure):
    _fields_ = [("devices",c_vp),("tensor_buft_overrides",c_vp),("n_gpu_layers",c_i32),
        ("split_mode",C.c_int),("load_mode",C.c_int),("main_gpu",c_i32),("tensor_split",C.POINTER(c_f)),
        ("progress_callback",c_vp),("progress_callback_user_data",c_vp),("kv_overrides",c_vp),
        ("vocab_only",C.c_bool),("check_tensors",C.c_bool),("use_extra_bufts",C.c_bool),
        ("no_host",C.c_bool),("no_alloc",C.c_bool),("load_mtp",C.c_bool)]

class llama_context_params(C.Structure):
    _fields_ = [("n_ctx",c_u32),("n_batch",c_u32),("n_ubatch",c_u32),("n_seq_max",c_u32),
        ("n_rs_seq",c_u32),("n_outputs_max",c_u32),("n_outputs_max_per_seq",c_u32),
        ("n_threads",c_i32),("n_threads_batch",c_i32),
        ("ctx_type",C.c_int),("rope_scaling_type",C.c_int),("pooling_type",C.c_int),
        ("attention_type",C.c_int),("flash_attn_type",C.c_int),
        ("rope_freq_base",c_f),("rope_freq_scale",c_f),("yarn_ext_factor",c_f),
        ("yarn_attn_factor",c_f),("yarn_beta_fast",c_f),("yarn_beta_slow",c_f),
        ("yarn_orig_ctx",c_u32),("defrag_thold",c_f),
        ("cb_eval",c_vp),("cb_eval_user_data",c_vp),("type_k",C.c_int),("type_v",C.c_int),
        ("abort_callback",c_vp),("abort_callback_data",c_vp),
        ("embeddings",C.c_bool),("offload_kqv",C.c_bool),("no_perf",C.c_bool),("op_offload",C.c_bool),
        ("swa_full",C.c_bool),("kv_unified",C.c_bool),
        ("samplers",c_vp),("n_samplers",C.c_size_t),("ctx_other",c_vp)]

class mtmd_context_params(C.Structure):
    _fields_ = [("use_gpu",C.c_bool),("print_timings",C.c_bool),("n_threads",C.c_int),
        ("image_marker",c_cp),("media_marker",c_cp),("flash_attn_type",C.c_int),("warmup",C.c_bool),
        ("image_min_tokens",C.c_int),("image_max_tokens",C.c_int),
        ("cb_eval",c_vp),("cb_eval_user_data",c_vp),("batch_max_tokens",c_i32),
        ("progress_callback",c_vp),("progress_callback_user_data",c_vp)]

class mtmd_input_text(C.Structure):
    _fields_ = [("text",c_cp),("text_len",C.c_size_t),("add_special",C.c_bool),("parse_special",C.c_bool)]

llama.llama_model_default_params.restype   = llama_model_params
llama.llama_context_default_params.restype = llama_context_params
mtmd.mtmd_context_params_default.restype   = mtmd_context_params
mtmd.mtmd_default_marker.restype           = c_cp

CHUNK_TEXT, CHUNK_IMAGE, CHUNK_AUDIO = 0, 1, 2

# ---------------- function signatures ----------------
llama.llama_backend_init.restype = None
llama.llama_model_load_from_file.argtypes = [c_cp, llama_model_params]; llama.llama_model_load_from_file.restype = c_vp
llama.llama_init_from_model.argtypes = [c_vp, llama_context_params];    llama.llama_init_from_model.restype = c_vp
llama.llama_model_get_vocab.argtypes = [c_vp]; llama.llama_model_get_vocab.restype = c_vp
llama.llama_vocab_bos.argtypes=[c_vp]; llama.llama_vocab_bos.restype=llama_token
llama.llama_vocab_eos.argtypes=[c_vp]; llama.llama_vocab_eos.restype=llama_token
llama.llama_vocab_is_eog.argtypes=[c_vp, llama_token]; llama.llama_vocab_is_eog.restype=C.c_bool
llama.llama_vocab_n_tokens.argtypes=[c_vp]; llama.llama_vocab_n_tokens.restype=c_i32
llama.llama_token_to_piece.argtypes=[c_vp, llama_token, c_cp, c_i32, c_i32, C.c_bool]
llama.llama_token_to_piece.restype=c_i32
llama.llama_get_memory.argtypes=[c_vp]; llama.llama_get_memory.restype=c_vp
llama.llama_memory_clear.argtypes=[c_vp, C.c_bool]; llama.llama_memory_clear.restype=None
llama.llama_sampler_init_greedy.restype = c_vp
llama.llama_sampler_sample.argtypes=[c_vp, c_vp, c_i32]; llama.llama_sampler_sample.restype=llama_token
llama.llama_sampler_accept.argtypes=[c_vp, llama_token]; llama.llama_sampler_accept.restype=None

class llama_batch(C.Structure):
    _fields_=[("n_tokens",c_i32),("token",C.POINTER(llama_token)),("embd",C.POINTER(c_f)),
              ("pos",C.POINTER(llama_pos)),("n_seq_id",C.POINTER(c_i32)),
              ("seq_id",C.POINTER(C.POINTER(llama_seq_id))),("logits",C.POINTER(C.c_int8))]
llama.llama_batch_get_one.argtypes=[C.POINTER(llama_token), c_i32]; llama.llama_batch_get_one.restype=llama_batch
llama.llama_decode.argtypes=[c_vp, llama_batch]; llama.llama_decode.restype=c_i32

mtmd.mtmd_init_from_file.argtypes=[c_cp, c_vp, mtmd_context_params]; mtmd.mtmd_init_from_file.restype=c_vp
mtmd.mtmd_free.argtypes=[c_vp]
mtmd.mtmd_bitmap_init.argtypes=[c_u32,c_u32,C.POINTER(C.c_ubyte)]; mtmd.mtmd_bitmap_init.restype=c_vp
mtmd.mtmd_bitmap_free.argtypes=[c_vp]
mtmd.mtmd_input_chunks_init.restype=c_vp
mtmd.mtmd_input_chunks_size.argtypes=[c_vp]; mtmd.mtmd_input_chunks_size.restype=C.c_size_t
mtmd.mtmd_input_chunks_get.argtypes=[c_vp,C.c_size_t]; mtmd.mtmd_input_chunks_get.restype=c_vp
mtmd.mtmd_input_chunks_free.argtypes=[c_vp]
mtmd.mtmd_input_chunk_get_type.argtypes=[c_vp]; mtmd.mtmd_input_chunk_get_type.restype=C.c_int
mtmd.mtmd_input_chunk_get_n_tokens.argtypes=[c_vp]; mtmd.mtmd_input_chunk_get_n_tokens.restype=C.c_size_t
mtmd.mtmd_input_chunk_get_n_pos.argtypes=[c_vp]; mtmd.mtmd_input_chunk_get_n_pos.restype=llama_pos
mtmd.mtmd_input_chunk_get_tokens_text.argtypes=[c_vp,C.POINTER(C.c_size_t)]
mtmd.mtmd_input_chunk_get_tokens_text.restype=C.POINTER(llama_token)
mtmd.mtmd_tokenize.argtypes=[c_vp,c_vp,C.POINTER(mtmd_input_text),C.POINTER(c_vp),C.c_size_t]
mtmd.mtmd_tokenize.restype=c_i32
mtmd.mtmd_helper_eval_chunks.argtypes=[c_vp,c_vp,c_vp,llama_pos,llama_seq_id,c_i32,C.c_bool,C.POINTER(llama_pos)]
mtmd.mtmd_helper_eval_chunks.restype=c_i32

llama.llama_free.argtypes=[c_vp]; llama.llama_free.restype=None
llama.llama_model_free.argtypes=[c_vp]; llama.llama_model_free.restype=None
llama.llama_backend_free.restype=None

llama.llama_n_ctx_train.argtypes=[c_vp]; llama.llama_n_ctx_train.restype=c_i32
llama.llama_n_ctx.argtypes=[c_vp];       llama.llama_n_ctx.restype=c_u32
mtmd.mtmd_support_vision.argtypes=[c_vp]; mtmd.mtmd_support_vision.restype=C.c_bool
mtmd.mtmd_support_audio.argtypes=[c_vp];  mtmd.mtmd_support_audio.restype=C.c_bool
