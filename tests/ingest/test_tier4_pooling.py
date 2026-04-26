"""Tests for tier4's pool_factor gating — the PPTX carve-out per backlog G4.

We can't run real ColPali in a unit test (needs torch + model + GPU), so we
mock the encode_images / upsert stack and assert:
  * For `.pptx`, pool_factor=2 flows through to HierarchicalTokenPooler.pool_embeddings
  * For anything else (PDF, image), pool_factor=1 and the pooler is never called
  * The policy's ext whitelist is exactly what we documented
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ingest.tier4 import POOL_FACTOR, POOL_SAFE_EXTS, _pool_factor_for


# ---------------------------------------------------------------------------
# Ext-whitelist policy
# ---------------------------------------------------------------------------

def test_pool_safe_exts_is_just_pptx_today():
    """Keep the whitelist small. Expanding it requires a recall benchmark."""
    assert POOL_SAFE_EXTS == {".pptx"}


def test_pool_factor_of_two_for_pptx():
    assert _pool_factor_for(Path("deck.pptx")) == POOL_FACTOR
    assert _pool_factor_for(Path("deck.pptx")) == 2


def test_pool_factor_one_for_everything_else():
    """FIQA reject: financial / visual files must NEVER be pooled."""
    for name in ("receipt.pdf", "statement.pdf", "scan.png", "photo.jpg",
                 "diagram.webp", "figure.docx"):
        assert _pool_factor_for(Path(name)) == 1, f"{name} leaked into pool!"


def test_pool_factor_case_insensitive():
    """Path.suffix is case-sensitive; our gate must lowercase."""
    assert _pool_factor_for(Path("DECK.PPTX")) == POOL_FACTOR
    assert _pool_factor_for(Path("Deck.Pptx")) == POOL_FACTOR


# ---------------------------------------------------------------------------
# End-to-end flow: index_file honors pool_factor
# ---------------------------------------------------------------------------

@patch("src.stage2.fast_db.upsert_pages_batch")
@patch("src.stage1_fast.model.get_model")
@patch("src.stage1_fast.model.encode_images")
@patch("src.stage1_fast.index._render_pages")
def test_index_file_invokes_pooler_when_pool_factor_gt_1(
    mock_render, mock_encode, mock_get_model, mock_upsert, tmp_path
):
    """With pool_factor=2, HierarchicalTokenPooler must be called."""
    import torch

    from src.stage1_fast.index import index_file
    from src.manifest import Manifest, DEFAULT_MANIFEST_PATH

    # Redirect manifest to tmp so test is hermetic
    mpath = tmp_path / "_manifest.json"
    original_default = DEFAULT_MANIFEST_PATH
    try:
        Manifest.__init__.__defaults__ = (mpath,)  # type: ignore[attr-defined]
        m = Manifest()

        # Fake: 2 pages, each encoded as a (100, 128) tensor
        mock_render.return_value = [MagicMock(), MagicMock()]
        mock_encode.return_value = torch.randn(2, 100, 128)
        cfg = MagicMock()
        cfg.batch_size = 4
        mock_get_model.return_value = (None, None, cfg)

        p = tmp_path / "deck.pptx"
        p.write_bytes(b"fake")

        with patch(
            "colpali_engine.compression.token_pooling.HierarchicalTokenPooler"
        ) as MockPooler:
            instance = MagicMock()
            # Pretend the pooler halves token count
            instance.pool_embeddings.return_value = torch.randn(2, 50, 128)
            MockPooler.return_value = instance

            index_file(p, m, pool_factor=2)

            # Pooler instantiated (no-arg constructor) + called with pool_factor=2
            MockPooler.assert_called_once_with()
            instance.pool_embeddings.assert_called_once()
            call_kwargs = instance.pool_embeddings.call_args.kwargs
            assert call_kwargs.get("pool_factor") == 2
    finally:
        Manifest.__init__.__defaults__ = (original_default,)  # type: ignore[attr-defined]


@patch("src.stage2.fast_db.upsert_pages_batch")
@patch("src.stage1_fast.model.get_model")
@patch("src.stage1_fast.model.encode_images")
@patch("src.stage1_fast.index._render_pages")
def test_index_file_does_not_invoke_pooler_when_pool_factor_1(
    mock_render, mock_encode, mock_get_model, mock_upsert, tmp_path
):
    """Default path: no pooler imported, no pooler called. Financial safety."""
    import torch

    from src.stage1_fast.index import index_file
    from src.manifest import Manifest, DEFAULT_MANIFEST_PATH

    mpath = tmp_path / "_manifest.json"
    original_default = DEFAULT_MANIFEST_PATH
    try:
        Manifest.__init__.__defaults__ = (mpath,)  # type: ignore[attr-defined]
        m = Manifest()

        mock_render.return_value = [MagicMock()]
        mock_encode.return_value = torch.randn(1, 100, 128)
        cfg = MagicMock()
        cfg.batch_size = 4
        mock_get_model.return_value = (None, None, cfg)

        p = tmp_path / "receipt.pdf"
        p.write_bytes(b"fake")

        with patch(
            "colpali_engine.compression.token_pooling.HierarchicalTokenPooler"
        ) as MockPooler:
            index_file(p, m, pool_factor=1)
            # Pooler was never instantiated because pool_factor==1
            MockPooler.assert_not_called()
    finally:
        Manifest.__init__.__defaults__ = (original_default,)  # type: ignore[attr-defined]
