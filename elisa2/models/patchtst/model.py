# model.py
"""
models/patchtst/model.py
─────────────────────────
PatchTST architecture for 7-day soil moisture forecasting.

Reference: Nie et al. 2023, "A Time Series is Worth 64 Words"
           NeurIPS 2023 (https://arxiv.org/abs/2211.14730)

Design choices:
    - seq_len=30, patch_size=5  → 6 patch tokens per input
    - d_model=64, 2 layers, 4 heads → ~70k parameters (fits on CPU/T4)
    - Pre-norm (norm_first=True)   → more stable training
    - Time embedding (DOY + season) → helps capture seasonality
    - Output: 7 scalar SM predictions (one per day)

Parameter budget: < 600k (verified by assertion in build())
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn

from config.settings import settings

_log = settings.get_logger(__name__)


class PatchEmbedding(nn.Module):
    """
    Splits the time dimension into non-overlapping patches and
    projects each patch to d_model dimensions.

    Also adds a learnable time embedding (DOY + season) to inject
    seasonal context into every token.
    """

    def __init__(self, n_features: int, patch_size: int, d_model: int):
        super().__init__()
        self.patch_size   = patch_size
        self.proj         = nn.Linear(patch_size * n_features, d_model)
        # Time embeddings — added once per sequence (not per patch)
        self.doy_embed    = nn.Embedding(367, d_model // 4)    # day of year
        self.season_embed = nn.Embedding(2,   d_model // 4)    # 0=Rabi, 1=Kharif
        self.time_proj    = nn.Linear(d_model // 2, d_model)

    def forward(
        self,
        x:      torch.Tensor,          # [B, seq_len, n_features]
        doy:    torch.Tensor,          # [B] int
        season: torch.Tensor,          # [B] int
    ) -> torch.Tensor:                 # [B, n_patches, d_model]
        B, T, F = x.shape
        n_patches = T // self.patch_size
        assert T % self.patch_size == 0, (
            f"seq_len ({T}) must be divisible by patch_size ({self.patch_size})"
        )
        # Reshape to patches: [B, n_patches, patch_size × F]
        x_patches = x.reshape(B, n_patches, self.patch_size * F)
        tokens    = self.proj(x_patches)    # [B, n_patches, d_model]

        # Inject time context
        t_emb  = torch.cat([self.doy_embed(doy), self.season_embed(season)], dim=-1)
        t_emb  = self.time_proj(t_emb).unsqueeze(1)   # [B, 1, d_model]
        tokens = tokens + t_emb                         # broadcast over patches
        return tokens


class PatchTST(nn.Module):
    """
    Full PatchTST model.

        Input  : [B, seq_len, n_features]
        Encode : 6 patch tokens → Transformer encoder → [B, 6, d_model]
        Decode : Flatten → Linear head → [B, forecast_horizon]
    """

    def __init__(
        self,
        n_features:      int,
        seq_len:         int,
        patch_size:      int,
        d_model:         int,
        n_heads:         int,
        n_layers:        int,
        d_ff:            int,
        dropout:         float,
        forecast_horizon: int,
    ):
        super().__init__()
        n_patches = seq_len // patch_size

        self.patch_embed = PatchEmbedding(n_features, patch_size, d_model)

        enc_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=d_ff,
            dropout=dropout,
            batch_first=True,
            norm_first=True,   # Pre-norm for stability
        )
        self.encoder = nn.TransformerEncoder(enc_layer, num_layers=n_layers)

        self.head = nn.Sequential(
            nn.Linear(n_patches * d_model, 128),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(128, forecast_horizon),
        )

    def forward(
        self,
        x:      torch.Tensor,   # [B, seq_len, n_features]
        doy:    torch.Tensor,   # [B]
        season: torch.Tensor,   # [B]
    ) -> torch.Tensor:          # [B, forecast_horizon]
        tokens  = self.patch_embed(x, doy, season)    # [B, n_patches, d_model]
        encoded = self.encoder(tokens)                  # [B, n_patches, d_model]
        flat    = encoded.reshape(encoded.size(0), -1)  # [B, n_patches * d_model]
        return self.head(flat)                          # [B, forecast_horizon]


def build(n_features: int) -> PatchTST:
    """
    Constructs PatchTST from settings.

    Args:
        n_features: Number of input features per timestep.

    Returns:
        Initialised PatchTST model.
    """
    cfg   = settings
    model = PatchTST(
        n_features       = n_features,
        seq_len          = cfg.seq_len,
        patch_size       = cfg.patch_size,
        d_model          = cfg.d_model,
        n_heads          = cfg.n_heads,
        n_layers         = cfg.n_layers,
        d_ff             = cfg.d_ff,
        dropout          = cfg.dropout,
        forecast_horizon = cfg.forecast_horizon,
    )
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    _log.info("PatchTST built: %d parameters.", n_params)
    assert n_params < 600_000, f"Model has {n_params} params — exceeds budget."
    return model
