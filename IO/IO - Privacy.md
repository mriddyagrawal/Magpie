# Privacy — what each party actually sees

> **What this doc is.** The honest privacy story for Magpie. NOT
> marketing copy — that gets derived from this doc. Written 2026-04-27
> while building the cloud server (Phase 2.5) so the privacy claims
> we make later are grounded in what the architecture actually does,
> not aspirational.
>
> Read this when: writing the user-facing privacy page, deciding
> whether a feature is OK to ship, answering a beta tester's
> *"so what do you do with my data?"* question, or designing a new
> endpoint that touches user content.

---

## The one-line truth

> **Your full files stay on your device. The questions you ask, and
> the small relevant parts needed to answer them, go to a third-party
> LLM through our server for that single query — not stored, not
> trained on, not retained.**

This is the same trade Notion AI / Cursor / Perplexity / Apple
Intelligence make. Worse than "everything runs locally" (which is
the v1.1 local-mode option). Better than "upload your whole drive."

Honest middle.

---

## What the user has to trust

There are exactly **three** parties in the data flow when the user asks
a question in cloud mode:

```
┌─────────────────────┐    Q + snippets   ┌──────────────────┐    Q + snippets    ┌────────────────┐
│  User's machine     │ ─────────────────► │  Magpie Cloud    │ ─────────────────► │  LLM provider  │
│  (Tauri + sidecar)  │ ◄────────────────  │  (your server)   │ ◄────────────────  │  (e.g. Kimi)   │
│                     │       answer       │                  │       answer       │                │
└─────────────────────┘                    └──────────────────┘                    └────────────────┘
```

Each box has a different privacy posture:

| Party | What they see | Trust required |
|---|---|---|
| **User's device** | Everything (their own files) | Zero — it's their machine |
| **Magpie Cloud** (you) | Question + snippet text + filenames + invite code | High — they trust your privacy policy |
| **LLM provider** (Kimi / Claude / OpenAI / etc.) | Question + snippet text | Medium — covered by provider's TOS |

The user has to trust YOU not to log/retain/train, and they implicitly
inherit the LLM provider's TOS (which they accept by signing up for
Magpie). You can pick a privacy-respecting provider; you can't make
the LLM provider invisible.

---

## What stays on the user's device — unambiguous

These never leave the machine:

- **The actual files** (PDFs, DOCXs, CSVs, etc. — every byte)
- **The Qdrant index** (vector embeddings of summaries)
- **The summary markdowns** in `<APP_DATA_DIR>/summaries/`
- **The manifest** (file paths, sizes, indexing state)
- **The MiniLM embedding model** runtime
- **The user's settings, history, preferences**
- **File previews** (rendered locally in the Tauri window)

Even if our cloud server is compromised, attackers do not get any
user's full corpus. They might get logs of recent queries (if we
retain logs at all — see retention section below), but never the full
files.

---

## What goes to the cloud — and exactly when

Three cases. In each, only the minimum needed.

### Case 1 — User asks a question

```
User types:    "how much did I spend on flights to Boston?"

Desktop does:  1. Embeds the question (LOCAL, MiniLM)
               2. Searches local Qdrant (LOCAL)
               3. Reads top-5 retrieved files (LOCAL)
               4. Extracts ~8 KB snippets per file (LOCAL)

Then sends to cloud:
               • Question text: "how much did I spend on flights to Boston?"
               • Snippets (5 × ~8 KB): pre-extracted text from the relevant files
               • Filenames: cite key for the answer
               • Invite code: in Authorization header

Cloud forwards to LLM:
               • System prompt + question + snippets

LLM returns:    structured answer, sources

Cloud forwards to desktop:
               • Answer text
               • List of source paths cited
```

The user's other 19,000 files? **Never sent.** Only the handful
retrieval found relevant for *this question.*

### Case 2 — User indexes a critical file (T3 cloud summarization)

```
Desktop extracts:  text from receipt.pdf

Sends to cloud:    • Filename: "receipt.pdf"
                   • Text: extracted content (~5 KB typical)

Cloud forwards to LLM:
                   • System prompt + the file text

LLM returns:       structured summary (title, keywords, identifiers, etc.)

Cloud forwards to desktop:
                   • Summary

Desktop:           stores summary locally → embeds → indexes in local Qdrant.
```

Cloud sees the file content **once during ingest**, never again. The
result lives on the user's device. Re-asking *"what was on that
receipt?"* hits Case 1 and may resend related snippets, but the file
isn't re-uploaded.

### Case 3 — User issues a query rewrite

```
Desktop sends:     question text + (optional) prior conversation turns

Cloud forwards to LLM:
                   • System prompt + question

LLM returns:       expanded query + keywords

Desktop:           uses that to search local Qdrant.
```

**No file content** in this case — just the question. Used to make
retrieval better.

---

## What we DON'T do (commit publicly)

The privacy policy will state:

1. **No retention of query content** — questions, snippets, and
   answers are processed for the single request and not stored beyond
   the request lifetime. Server logs may include metadata (timestamp,
   invite code, latency, success/failure) but **not** the question
   text or snippet content.
2. **No training on user data** — we do not use any user's content
   to fine-tune any model.
3. **No sharing with anyone except the LLM provider** for the
   one-time purpose of answering that query.
4. **No analytics that include content** — we may log that a user
   asked a question (count, latency), never *what* they asked.
5. **No selling or sharing data with third parties** other than the
   LLM provider, even in aggregate.
6. **No tracking across sessions for advertising** — we are not an
   ad-supported product.

If any of those change, the privacy policy version bumps and users get
notified before the change takes effect.

---

## What we CANNOT promise (be honest)

These are real and worth flagging:

1. **The LLM provider sees the snippets.** OpenRouter / Kimi / Anthropic
   / OpenAI process the request. They have their own privacy
   policies; we route only through providers whose TOS we've reviewed
   and find acceptable. If the LLM provider gets compromised or
   subpoenaed, that data is at risk in their hands, not ours.
2. **Network-layer interception.** HTTPS prevents passive sniffing,
   but state-level adversaries with TLS-MITM capability could
   theoretically intercept. Same risk profile as every other web
   service.
3. **Side-channel leaks via metadata.** A list of "what filenames
   were cited" is itself information. We can't fully hide that we
   were asked about a file.
4. **A future malicious operator.** The user trusts whoever runs the
   Magpie Cloud servers. If the company gets sold or compromised, the
   privacy policy must travel with the company; the user has to
   trust that.
5. **Bugs.** Any program can have a logging-too-much bug. We try
   hard, but absolute claims are dishonest.

The local-mode (v1.1) escape hatch is the answer to all of these for
users who can't accept any of them.

---

## What "privacy" actually means here

Three concrete claims, in plain language. These are the things we
*can* defend:

### Claim 1 — *"Your full files don't go to our server."*

Pretty sturdy. The architecture genuinely doesn't upload the full
corpus. Only the snippets needed for the current question. Verifiable
by network inspection (Wireshark on a beta tester's machine; they will
see only the cloud server URL, with bodies containing question + a few
KB of snippets).

### Claim 2 — *"We don't store what you ask after answering."*

Policy claim. Not technically enforceable from the user's side, but
auditable by us via log retention rules (e.g. logs purged after 7
days, no message body in logs). We commit in writing.

### Claim 3 — *"You can opt for fully local mode."*

Architectural claim. Once v1.1 ships, the user can flip a toggle in
settings; from that moment on **no data of any kind leaves their
device** for LLM purposes. Search and answer both run locally, slower
but truly private.

These three are the entire privacy story we should make. Don't make
broader claims. Don't say "your data is private" without qualification.

---

## How privacy maps to the architecture decisions

| Architecture decision | Privacy consequence |
|---|---|
| MiniLM embedding model bundled with desktop | Embeddings are local — no "we know what you searched for" |
| Qdrant runs locally (or on user's local server) | Vector index is private; nobody sees what semantic neighborhoods the user explores |
| Files extracted on-device, only snippets sent | Cloud sees only what's needed for the current answer |
| Cloud server proxies to LLM provider | Cloud is auditable to YOU; raw LLM provider auditing is harder |
| Invite code per beta tester | Per-user logging granularity without storing PII |
| Local mode v1.1 ships | Users with truly sensitive content get a fully-private path |

If you're tempted to ship a feature that breaks one of those rows,
flag it explicitly in the privacy policy — *"as of v1.X we now upload
the full corpus to enable feature Z"* — and let the user opt in. Don't
silently change the trust model.

---

## Comparison to alternatives

To calibrate: how does Magpie's privacy compare to existing products?

| Product | Where files live | What goes to cloud | Privacy posture |
|---|---|---|---|
| **Magpie cloud mode** | local | question + ~8 KB snippets per query | mid |
| **Magpie local mode** (v1.1+) | local | nothing | high — same as Apple Spotlight |
| **ChatGPT** (via website) | nowhere — user pastes manually | everything they paste | low control |
| **Notion AI** | uploaded to Notion already | full doc context | low — full corpus is in Notion's hands |
| **Cursor AI** | local, but full file context goes up | active file + repo context | mid |
| **Perplexity** | nothing — purely web search | the question only | high (no user files) |
| **Apple Spotlight** | local | nothing | very high (purely local) |
| **Apple Intelligence** | local | "private cloud compute" — encrypted | high (Apple has strong guarantees) |
| **Dropbox / Google Drive** | uploaded to cloud | everything always | low |

Magpie cloud mode sits at the *upper-mid* range — better than every
product that requires you to upload your corpus, slightly worse than
Apple Intelligence (which does private cloud compute), much better
than ChatGPT (where everything is in Sam Altman's hands).

Magpie local mode (v1.1) matches Apple Spotlight.

---

## What this means for engineering decisions

Three rules to keep the architecture honest:

### Rule 1 — No new code path that uploads more data than the user expects

If a new feature requires sending more than "question + retrieval
snippets" to the cloud, it's a privacy-policy change. Examples:

- ✅ OK without policy change: a new endpoint that takes a question
  and returns a summary
- ❌ Requires policy change: a "scheduled background sync" that
  uploads new files automatically
- ❌ Requires policy change: any "personalization" feature that
  retains query history server-side

### Rule 2 — Every endpoint must have a stated retention rule

Each endpoint specifies: *"this endpoint retains nothing after the
response,"* or *"this endpoint logs metadata only (no content) for N
days,"* or *"this endpoint requires explicit opt-in retention."*

Document this in the endpoint's docstring + the privacy policy.

### Rule 3 — Local mode is the escape hatch

If a user can't accept the cloud-mode privacy posture, they have an
alternative. We commit to maintaining local mode for as long as the
product exists. We don't ship a cloud-only product.

---

## Open privacy questions (decide before public launch)

These are unresolved as of 2026-04-27. Decide before publishing the
privacy policy:

1. **Logging retention.** Default to 7 days for ops debugging? 30
   days? Zero (no logs at all)? Industry standard is 7-30 days
   metadata only.
2. **Subpoena response policy.** What do we hand over if served? At
   minimum: query metadata (timestamp, invite code) — never content,
   because content isn't stored.
3. **EU/GDPR users.** If we have EU users, we need a DPO contact, a
   data-export endpoint, and a deletion endpoint. Probably out of
   scope for beta but pencil it in.
4. **Provider switching.** If we change LLM providers, do we
   announce it before? Industry standard: yes, with N days notice.
5. **Fine-tuning offer.** Do we ever offer "fine-tune on your data
   for better answers"? If yes, requires explicit opt-in and a fully
   isolated training corpus. Defer the decision.
6. **Encryption at rest.** When data is in flight through your cloud
   server's RAM, it's plaintext. Should we encrypt the snippet payload
   client-side and decrypt only inside the LLM call? Probably overkill
   for beta; consider for v2.

Track these as they come up. Don't commit to anything in writing until
you've decided.

---

## Privacy-page draft (for the eventual website)

Plain-language copy ready to put on a `magpie.app/privacy` page when
you launch. This is the user-facing version of everything above:

```
What we do with your data

When you ask Magpie a question, we send your question and the small
parts of files needed to answer it to our LLM provider. Your full
files stay on your computer — we never receive a copy.

We process your question for that one query and don't keep it
afterward. We don't train any model on your data. We don't share it
with anyone except the LLM provider (currently Moonshot Kimi /
Anthropic Claude — see model list) for the one-time purpose of
answering you.

What we don't see

• Your full document collection — only the snippets relevant to a
  question you ask
• Files you never search — they never touch our server
• Your search history — we don't keep it after answering

What the LLM provider sees

The LLM provider processes your question and the snippets needed to
answer. They have their own privacy policies. We use providers whose
terms we've reviewed; we'll list current providers and link to their
policies on this page.

The local mode escape hatch

If even that's too much, Magpie's local mode (toggle in settings)
runs everything on your computer. Slower, slightly less accurate, but
nothing leaves your device. No internet required after the initial
download.
```

This is the content. Style/branding gets layered on top, but the
substance must not be diluted into "your data is private!" — that
overpromises.

---

## Cross-references

- [IO - Phase 2.5.md](IO%20-%20Phase%202.5.md) — the cloud server
  this whole privacy story is built on
- [IO - Phase 2.5 Step 4.md](IO%20-%20Phase%202.5%20Step%204.md) —
  the three LLM endpoints that touch user content
- [IO - Repo Structure.md](IO%20-%20Repo%20Structure.md) — why the
  prompts (which see the data) live server-side
- [server/magpie_server/llm_routes.py](../server/magpie_server/llm_routes.py) —
  every place user content is processed
- [Plans/](../Plans/) — local-mode (v1.1) plan when written
