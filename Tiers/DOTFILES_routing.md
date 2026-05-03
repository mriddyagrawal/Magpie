# Dotfiles routing (`.bashrc`, `.zshrc`, `.vimrc`, `.gitconfig`, …)

Useful extensionless dotfiles are routed by **filename**, not extension. The
router has an allowlist (`USEFUL_DOTFILE_NAMES`) of ~25 names — shell rcs,
editor configs, terminal multiplexer configs, tool configs. Files in the
allowlist bypass the considered-extension check and are treated as text.

The walker has a **separate** prune pass: dot-folders (`.config/`, `.cache/`)
are pruned in-place during traversal unless `.nasconfig.yaml` says
`include_dotfiles: true`. Leaf-name dotfiles outside the allowlist are skipped.

Sensitive dotfiles deliberately **NOT** in the allowlist: `.env`, `.npmrc`,
`.netrc`, `.pgpass`, `.git-credentials` (secrets), `.gitignore` (meta-only),
`.DS_Store`, `.ipynb_checkpoints` (cruft).

## Path summary

| Stage | What runs |
|---|---|
| Walker filter | Allowlisted dotfile names bypass the considered-ext check ([src/ingest/walker.py:300](../src/ingest/walker.py#L300)). Dot-folders pruned during traversal. |
| peek function | `_peek_text_file` (extensionless but treated as text) ([src/router.py:213](../src/router.py#L213)) |
| decide branch | `path.name in USEFUL_DOTFILE_NAMES` short-circuit ([src/router.py:867](../src/router.py#L867)) |
| Threshold | `TEXT_SIZE_T0_THRESHOLD = 100 KB` (same as `.txt`) |
| Tier worker(s) | `tier1.run` (small) or `tier0.run` (large) |
| Stage 2 downstream | parse → embed → upsert into `summaries` collection (1 point per file). |

## Allowlisted names

```
Shell / login:    .bashrc .bash_profile .bash_aliases .bash_logout
                  .zshrc .zprofile .zshenv .zlogin .zlogout
                  .profile .kshrc .cshrc .tcshrc
                  .inputrc .dircolors
Editors:          .vimrc .nvimrc .gvimrc
Multiplexers:     .tmux.conf .screenrc
Tool config:      .gitconfig .gitattributes .editorconfig
                  .condarc
```

(See [src/router.py:48](../src/router.py#L48) for the canonical list.)

## Flowchart

```mermaid
flowchart TD
    A["File: .bashrc / .zshrc / etc."] --> B{"Walker dot-folder prune?<br/>(parent starts with .)<br/>unless include_dotfiles=true"}
    B -- "pruned" --> Z0["never enters candidate list"]
    B -- "kept" --> C{"Leaf dotfile filter:<br/>name in USEFUL_DOTFILE_NAMES?"}
    C -- "no (and not include_dotfiles)" --> Z1["filtered out"]
    C -- "yes" --> D{"Manifest unchanged?"}
    D -- "yes" --> Z2["SKIP: unchanged"]
    D -- "no" --> E["router.peek →<br/>_peek_text_file<br/>(USEFUL_DOTFILE_NAMES short-circuit)"]
    E --> F["Read first 10 KB<br/>UTF-8 decode<br/>5 KB peek_text"]
    F --> G["scores + criticality"]
    G --> H["router.decide:<br/>USEFUL_DOTFILE_NAMES branch<br/>(BEFORE extension dispatch)"]
    H --> I{"size_bytes ≥ 100 KB?"}
    I -- "yes (large)" --> T0["Route: T0"]
    I -- "no (small)" --> T1["Route: T1"]
    T0 --> W0["tier0.run<br/>head 2 KB preview<br/>title: filename + KB"]
    T1 --> W1["tier1.run<br/>full body, 8000-char cap<br/>content_type: text<br/>(extension is empty,<br/>so falls through to default)"]
    W0 --> M["render_summary_markdown"]
    W1 --> M
    M --> P["Write SUMMARIES_DIR/<br/>&lt;sha256[:16]&gt;_t0.md<br/>or _t1.md"]
    P --> Q["manifest.mark_summarized<br/>+ mark_routed"]
    Q --> R["End of walk → Stage 2 push"]
    R --> S["parse_summary_file"]
    S --> T["embed_dense + embed_sparse"]
    T --> U["Qdrant upsert into<br/>'summaries' collection<br/>1 point per file"]
    U --> V["manifest.mark_ingested"]

    classDef skip fill:#ffcccc,stroke:#990000,color:#000
    class Z0,Z1,Z2 skip
```

## Code references

- Allowlist: [src/router.py:48](../src/router.py#L48) (`USEFUL_DOTFILE_NAMES`)
- Walker leaf-dotfile filter: [src/ingest/walker.py:300](../src/ingest/walker.py#L300)
- Walker dot-folder prune: [src/ingest/walker.py:286](../src/ingest/walker.py#L286)
- peek dispatch: [src/router.py:621](../src/router.py#L621)
- decide short-circuit: [src/router.py:867](../src/router.py#L867)
- T0 worker: [src/ingest/tier0.py](../src/ingest/tier0.py)
- T1 worker: [src/ingest/tier1.py](../src/ingest/tier1.py)
