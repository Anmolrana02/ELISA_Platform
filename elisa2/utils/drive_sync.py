# drive_sync.py
"""
utils/drive_sync.py
────────────────────
Syncs ML models, datasets, and farm state files between
Hugging Face Hub (persistent) and the Render ephemeral filesystem.

Replaces the original Google Drive version — service accounts
cannot own Drive files (storageQuotaExceeded error).

HF Hub is free, designed for ML files, and works with a single token
for both laptop uploads and Render downloads.

Setup:
    1. Create account at huggingface.co
    2. Create a PRIVATE dataset repo called 'elisa-models-data'
    3. Generate a Write token at huggingface.co/settings/tokens
    4. Add to .env:
         HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx
         HF_REPO_ID=yourname/elisa-models-data

CLI usage (run once from your laptop after training):
    cd ELISA_Platform
    python -m elisa2.utils.drive_sync --upload
    python -m elisa2.utils.drive_sync --check
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)


# ── Config ─────────────────────────────────────────────────────────────────────

def _get_hf_config() -> tuple[str, str]:
    """Returns (token, repo_id) from environment / .env file."""
    # Try loading .env if running standalone
    try:
        from config.settings import settings as _s
        # settings loads .env automatically via pydantic-settings
        # but HF vars may not be declared there — fall through to os.environ
    except Exception:
        pass

    token   = os.environ.get("HF_TOKEN", "")
    repo_id = os.environ.get("HF_REPO_ID", "")

    if not token:
        raise EnvironmentError(
            "HF_TOKEN not set. Add to your .env file:\n"
            "  HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx\n"
            "  HF_REPO_ID=yourname/elisa-models-data"
        )
    if not repo_id:
        raise EnvironmentError(
            "HF_REPO_ID not set. Add to your .env file:\n"
            "  HF_REPO_ID=yourname/elisa-models-data"
        )
    return token, repo_id


def _get_api():
    """Returns an authenticated HfApi instance."""
    from huggingface_hub import HfApi
    token, _ = _get_hf_config()
    return HfApi(token=token)


# ── Manifest — which files to sync ─────────────────────────────────────────────

def _sync_manifest() -> list[tuple[str, Path]]:
    """
    Returns list of (path_in_repo, local_path) pairs.
    path_in_repo is the filename as stored in the HF dataset repo.
    """
    from config.settings import settings
    return [
        ("models/patchtst.pt",            settings.patchtst_checkpoint),
        ("models/downscaler_rf.joblib",   settings.downscaler_checkpoint),
        ("data/dataset_real_soil.csv",    settings.real_soil_dataset),
        ("data/dataset_simulated.csv",    settings.simulated_dataset),
    ]


# ── Upload ──────────────────────────────────────────────────────────────────────

def upload_file(local_path: Path, path_in_repo: str) -> bool:
    """
    Uploads one file to the HF repo.
    Skips if local file doesn't exist.
    Returns True on success.
    """
    if not local_path.exists():
        _log.warning("Skipping — local file not found: %s", local_path)
        return False

    try:
        api      = _get_api()
        _, repo_id = _get_hf_config()

        _log.info("Uploading '%s' → hf://%s/%s ...",
                  local_path.name, repo_id, path_in_repo)

        api.upload_file(
            path_or_fileobj=str(local_path),
            path_in_repo=path_in_repo,
            repo_id=repo_id,
            repo_type="dataset",
        )
        size_mb = local_path.stat().st_size / 1_000_000
        _log.info("  Uploaded %.1f MB — done.", size_mb)
        return True

    except Exception as exc:
        _log.error("Upload failed for '%s': %s", local_path.name, exc)
        return False


def upload_models_and_data() -> None:
    """
    Uploads all manifest files + farm state files to HF Hub.
    Call from laptop after training, and nightly from scheduler
    to back up farm states.
    """
    _, repo_id = _get_hf_config()
    _log.info("Uploading ELISA files to hf://%s ...", repo_id)

    # Models and datasets
    for path_in_repo, local_path in _sync_manifest():
        upload_file(local_path, path_in_repo)

    # Farm state JSONs and event CSVs (tiny per-farmer files)
    try:
        from config.settings import settings
        states_dir = settings.data_dir / "farm_states"
        if states_dir.exists():
            state_files = (
                list(states_dir.glob("*.json")) +
                list(states_dir.glob("*_events.csv"))
            )
            if state_files:
                api      = _get_api()
                _log.info("Uploading %d farm state files...", len(state_files))
                for f in state_files:
                    upload_file(f, f"farm_states/{f.name}")
                _log.info("Farm states synced.")
    except Exception as exc:
        _log.warning("Farm state upload failed (non-fatal): %s", exc)


# ── Download ────────────────────────────────────────────────────────────────────

def download_file(path_in_repo: str, local_path: Path) -> bool:
    """
    Downloads one file from HF Hub to local_path.
    Returns True on success, False if file not found in repo.
    """
    try:
        from huggingface_hub import hf_hub_download
        token, repo_id = _get_hf_config()

        _log.info("Downloading hf://%s/%s ...", repo_id, path_in_repo)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        downloaded = hf_hub_download(
            repo_id=repo_id,
            filename=path_in_repo,
            repo_type="dataset",
            token=token,
            local_dir=str(local_path.parent),
            local_dir_use_symlinks=False,
        )

        # hf_hub_download may save to a cache path — move to exact location
        downloaded_path = Path(downloaded)
        if downloaded_path != local_path:
            import shutil
            shutil.move(str(downloaded_path), str(local_path))

        size_mb = local_path.stat().st_size / 1_000_000
        _log.info("  Downloaded %.1f MB → %s", size_mb, local_path)
        return True

    except Exception as exc:
        err_str = str(exc)
        if "404" in err_str or "not found" in err_str.lower() or "Entry Not Found" in err_str:
            _log.warning("'%s' not in repo yet — skipping.", path_in_repo)
        else:
            _log.error("Download failed for '%s': %s", path_in_repo, exc)
        return False


def ensure_files() -> None:
    """
    Called on Render startup.
    Downloads any manifest file that is missing from the ephemeral disk.
    Skips files that already exist (warm instance cache).
    """
    try:
        _, repo_id = _get_hf_config()
    except EnvironmentError as exc:
        _log.error("HF config missing — Drive sync skipped. %s", exc)
        return

    _log.info("Checking files against hf://%s ...", repo_id)

    for path_in_repo, local_path in _sync_manifest():
        if local_path.exists():
            size_mb = local_path.stat().st_size / 1_000_000
            _log.info("  '%s' on disk (%.1f MB) — skipping.", local_path.name, size_mb)
            continue
        _log.info("  '%s' missing — downloading...", local_path.name)
        download_file(path_in_repo, local_path)


def download_farm_states() -> None:
    """
    Downloads all farm state files from HF Hub.
    Called on startup after ensure_files().
    """
    try:
        from huggingface_hub import list_repo_files
        token, repo_id = _get_hf_config()
        from config.settings import settings
        states_dir = settings.data_dir / "farm_states"
    except Exception as exc:
        _log.warning("Farm state download skipped: %s", exc)
        return

    try:
        # List all files in farm_states/ subfolder of the repo
        all_files = list(list_repo_files(
            repo_id=repo_id,
            repo_type="dataset",
            token=token,
        ))
        state_files = [f for f in all_files if f.startswith("farm_states/")]

        if not state_files:
            _log.info("No farm state files in repo yet.")
            return

        _log.info("Downloading %d farm state files...", len(state_files))
        for path_in_repo in state_files:
            filename   = Path(path_in_repo).name
            local_path = states_dir / filename
            if not local_path.exists():
                download_file(path_in_repo, local_path)

    except Exception as exc:
        _log.warning("Farm state download failed (non-fatal): %s", exc)


# ── CLI ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    # Load .env so HF_TOKEN and HF_REPO_ID are available
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s | %(message)s",
    )

    parser = argparse.ArgumentParser(description="ELISA Hugging Face sync tool")
    parser.add_argument("--upload",   action="store_true", help="Upload all files to HF Hub")
    parser.add_argument("--download", action="store_true", help="Download all files from HF Hub")
    parser.add_argument("--check",    action="store_true", help="List files in HF repo")
    args = parser.parse_args()

    if args.upload:
        print("Uploading ELISA files to Hugging Face Hub...")
        upload_models_and_data()
        print("\nDone. Run --check to verify.")

    elif args.download:
        print("Downloading from Hugging Face Hub...")
        ensure_files()
        download_farm_states()
        print("Done.")

    elif args.check:
        from huggingface_hub import list_repo_files
        token, repo_id = _get_hf_config()
        from huggingface_hub import HfApi
        api = HfApi(token=token)

        print(f"\nFiles in hf://{repo_id}/")
        print(f"{'Path in repo':<50} {'Size':>10}")
        print("-" * 65)

        try:
            # Get file info with sizes
            repo_info = api.repo_info(
                repo_id=repo_id,
                repo_type="dataset",
                files_metadata=True,
            )
            if hasattr(repo_info, 'siblings') and repo_info.siblings:
                for sib in sorted(repo_info.siblings, key=lambda x: x.rfilename):
                    size_mb = (sib.size or 0) / 1_000_000
                    print(f"  {sib.rfilename:<48} {size_mb:>8.1f} MB")
            else:
                # Fallback: just list filenames
                for f in sorted(list_repo_files(repo_id=repo_id,
                                                repo_type="dataset", token=token)):
                    print(f"  {f}")
        except Exception as exc:
            print(f"Error: {exc}")

    else:
        parser.print_help()