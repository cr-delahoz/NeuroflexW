"""One-time migration: read sklearn StandardScaler pickle → plain .npz.

Run ONCE after checkout:
    python scripts/generate_scaler_npz.py

Requirements: joblib + scikit-learn (already in dev env, not needed at runtime).
"""

import warnings

import joblib
import numpy as np
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "ml" / "model_artifacts"
PKL_PATH = HERE / "scaler_neuroflex.pkl"
NPZ_PATH = HERE / "scaler_neuroflex.npz"


def main():
    if NPZ_PATH.exists():
        print(f"[skip] {NPZ_PATH} already exists.")
        return

    scaler = joblib.load(PKL_PATH)

    keys = ["mean_", "scale_", "var_", "feature_names_in_"]
    kwargs = {k: getattr(scaler, k) for k in keys}

    kwargs["with_mean"] = scaler.with_mean
    kwargs["with_std"] = scaler.with_std
    kwargs["n_features_in_"] = scaler.n_features_in_
    n_samples_seen = getattr(scaler, "n_samples_seen_", None)
    if n_samples_seen is not None:
        kwargs["n_samples_seen_"] = n_samples_seen
    else:
        warnings.warn("scaler has no n_samples_seen_ attribute; omitting from npz")

    np.savez(NPZ_PATH, **kwargs)

    print(f"Created {NPZ_PATH}")
    print(f"  mean_             shape {scaler.mean_.shape}")
    print(f"  scale_            shape {scaler.scale_.shape}")
    print(f"  var_              shape {scaler.var_.shape}")
    print(f"  feature_names_in_ shape {scaler.feature_names_in_.shape}")
    print(f"  n_features_in_    = {scaler.n_features_in_}")
    print(f"  with_mean         = {scaler.with_mean}")
    print(f"  with_std          = {scaler.with_std}")


if __name__ == "__main__":
    main()
