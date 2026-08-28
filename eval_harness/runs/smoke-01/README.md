smoke-01 predates commit 74e813c (offline-invariant swap): its env_snapshot
correctly shows HF_HUB_OFFLINE=1 for its time. The run failed in the index
phase (transformers offline mode vs the config-less colqwen2.5-v0.2 adapter
repo) — that failure is what motivated the swap. Kept as evidence.
