"""Verify that the installed BS-RoFormer runner can construct Mega53 correctly."""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import textwrap
from importlib import metadata
from pathlib import Path


MODEL_SLUG = "roformer-model-bs-roformer-mvsep-mega-53-stems"
PINNED_SOURCE_COMMIT = "b0f1386fcced25f559f3e61c9f08a73cd9bddf80"
MARKER_NAME = "bs-roformer-mega53-runner-ready.json"


def verify() -> dict:
    from bs_roformer import BSRoformer, MODEL_REGISTRY, get_model_from_config
    from bs_roformer.bs_roformer import MaskEstimator

    model_meta = MODEL_REGISTRY.get(MODEL_SLUG)
    if model_meta.category != "mega-stem":
        raise RuntimeError(f"Mega53 registry category mismatch: {model_meta.category}")
    required_outputs = {"acoustic-guitar", "electric-guitar"}
    if not required_outputs.issubset(set(model_meta.default_sources)):
        raise RuntimeError("Mega53 registry does not declare both dedicated guitar outputs")
    if "mlp_expansion_factor" not in inspect.signature(BSRoformer).parameters:
        raise RuntimeError("Installed BS-RoFormer is too old: missing mlp_expansion_factor")

    # Verify the config-construction allowlist directly.  This is the exact bug
    # in 0.1.5: the YAML value existed but get_model_from_config filtered it out.
    function_tree = ast.parse(textwrap.dedent(inspect.getsource(get_model_from_config)))
    string_constants = {
        node.value for node in ast.walk(function_tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    if "mlp_expansion_factor" not in string_constants:
        raise RuntimeError(
            "Installed BS-RoFormer still filters mlp_expansion_factor from model configs"
        )

    # Probe only the affected component.  It avoids constructing an STFT or a
    # complete audio model while proving factor 2 makes an 8-wide hidden layer.
    probe = MaskEstimator(
        dim=4, dim_inputs=(2, 4), depth=2, mlp_expansion_factor=2
    )
    first_weight = next(
        value for key, value in probe.state_dict().items()
        if key.startswith("to_freqs.0") and key.endswith("weight")
    )
    probe_shape = list(first_weight.shape)
    if probe_shape != [8, 4]:
        raise RuntimeError(
            "Installed BS-RoFormer still ignores mlp_expansion_factor=2: "
            f"probe shape is {probe_shape}, expected [8, 4]"
        )

    return {
        "verified": True,
        "model": MODEL_SLUG,
        "package_version": metadata.version("bs-roformer-infer"),
        "pinned_source_commit": PINNED_SOURCE_COMMIT,
        "registry_category": model_meta.category,
        "outputs": sorted(required_outputs),
        "mlp_expansion_factor_probe": probe_shape,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--write-marker", action="store_true")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    result = verify()
    marker = args.model_dir.resolve() / MARKER_NAME
    if args.quick:
        try:
            saved = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Missing compatible runner marker; run Install-BS-RoFormer-Mega53-v336.cmd: {marker}"
            ) from exc
        if saved != result:
            raise RuntimeError(
                "BS-RoFormer runner changed or is incompatible; run "
                "Install-BS-RoFormer-Mega53-v336.cmd again"
            )
    if args.write_marker:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"READY: {marker}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
