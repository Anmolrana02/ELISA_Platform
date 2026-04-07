# model.py
"""
models/patchtst/model.py
─────────────────────────
PatchTST for 7-day soil moisture forecasting — v2.

Changes from v1:
    seq_len=60, patch_size=6  → 10 patches of 6 days
    d_model=128, n_layers=3   → ~300k params
    d_ff=256
    season_embed: 3-class (0=Rabi, 1=Kharif, 2=Sugarcane)
    crop_embed: 3-class (0=Wheat, 1=Rice, 2=Sugarcane) — NEW
    month_sin/cos are already part of X features, not embedded separately

Parameter budget: < 600k (verified by assertion in build())
"""

from __future__ import annotations

import torch
import torch.nn as nn

from config.settings import settings

_log = settings.get_logger(__name__)


class PatchEmbedding(nn.Module):
    """
    Splits time dimension into non-overlapping patches and projects
    each patch to d_model. Adds DOY, season, and crop embeddings.
    """

    def __init__(self, n_features: int, patch_size: int, d_model: int):
        super().__init__()
        self.patch_size = patch_size
        self.proj       = nn.Linear(patch_size * n_features, d_model)

        # Time / crop embeddings — combined and projected to d_model
        # DOY: 1-366, season: 0-2 (Rabi/Kharif/Sugarcane), crop: 0-2
        self.doy_embed    = nn.Embedding(367, d_model // 4)
        self.season_embed = nn.Embedding(3,   d_model // 4)   # 3-class
        self.crop_embed   = nn.Embedding(4,   d_model // 4)   # 3 crops + unknown(-1→3)
        self.time_proj    = nn.Linear(3 * (d_model // 4), d_model)

    def forward(
        self,
        x:      torch.Tensor,   # [B, seq_len, n_features]
        doy:    torch.Tensor,   # [B] int
        season: torch.Tensor,   # [B] int  0=Rabi 1=Kharif 2=Sugarcane
        crop:   torch.Tensor,   # [B] int  0=Wheat 1=Rice 2=Sugarcane 3=unknown
    ) -> torch.Tensor:          # [B, n_patches, d_model]
        B, T, F = x.shape
        n_patches = T // self.patch_size
        assert T % self.patch_size == 0, (
            f"seq_len ({T}) must be divisible by patch_size ({self.patch_size})"
        )

        x_patches = x.reshape(B, n_patches, self.patch_size * F)
        tokens    = self.proj(x_patches)   # [B, n_patches, d_model]

        # Clamp crop to valid range [0, 3]
        crop_clamped = crop.clamp(0, 3)

        t_emb = torch.cat([
            self.doy_embed(doy),
            self.season_embed(season),
            self.crop_embed(crop_clamped),
        ], dim=-1)                              # [B, 3*(d_model//4)]
        t_emb  = self.time_proj(t_emb).unsqueeze(1)  # [B, 1, d_model]
        tokens = tokens + t_emb                        # broadcast over patches
        return tokens


class PatchTST(nn.Module):
    """
    Full PatchTST model v2.

        Input  : [B, seq_len=60, n_features]
        Patches: 10 × 6-day patches
        Encode : Transformer encoder [B, 10, d_model=128]
        Head   : Flatten → Linear(256) → GELU → Linear(7)
        Output : [B, 7]  (7-day SM forecast)
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
            nn.Linear(n_patches * d_model, 256),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(256, forecast_horizon),
        )

    def forward(
        self,
        x:      torch.Tensor,   # [B, seq_len, n_features]
        doy:    torch.Tensor,   # [B]
        season: torch.Tensor,   # [B]
        crop:   torch.Tensor,   # [B]   ← NEW
    ) -> torch.Tensor:          # [B, forecast_horizon]
        tokens  = self.patch_embed(x, doy, season, crop)
        encoded = self.encoder(tokens)
        flat    = encoded.reshape(encoded.size(0), -1)
        return self.head(flat)


def build(n_features: int) -> PatchTST:
    """Constructs PatchTST v2 from settings."""
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
    _log.info(
        "PatchTST v2 built: %d parameters | seq=%d patch=%d d_model=%d layers=%d",
        n_params, cfg.seq_len, cfg.patch_size, cfg.d_model, cfg.n_layers,
    )
    assert n_params < 600_000, f"Model has {n_params} params — exceeds budget."
    return model