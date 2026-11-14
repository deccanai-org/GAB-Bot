"""Render a deployable manifest only when supplied an immutable built image digest."""

import argparse
import copy
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def render(image: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}", image):
        raise ValueError(
            "Use the registry digest of an image that passed CI: repository@sha256:..."
        )
    deployment = yaml.safe_load((ROOT / "k8s-manifests/dev/deployment.yaml").read_text())
    deployment = copy.deepcopy(deployment)
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    container["image"] = image
    return deployment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = render(args.image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    print("Release manifest rendered; no cluster changes made")


if __name__ == "__main__":
    main()
