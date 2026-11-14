import importlib.util

import pytest

from .conftest import ROOT


def renderer():
    spec = importlib.util.spec_from_file_location(
        "render_release", ROOT / "scripts/render_release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render


def test_release_requires_an_immutable_image_and_has_production_guards():
    render = renderer()
    for invalid in ["repo:latest", "repo:v1", "repo@sha256:wrong"]:
        with pytest.raises(ValueError):
            render(invalid)
    doc = render("registry.example/bot@sha256:" + "a" * 64)
    spec = doc["spec"]["template"]["spec"]
    container = spec["containers"][0]
    assert doc["spec"]["replicas"] == 1
    assert doc["spec"]["strategy"]["type"] == "Recreate"
    assert not spec["automountServiceAccountToken"]
    assert spec["securityContext"]["runAsNonRoot"]
    assert container["securityContext"]["readOnlyRootFilesystem"]
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["startupProbe"]["httpGet"]["path"] == "/health/ready"
    assert container["livenessProbe"]["httpGet"]["path"] == "/health/live"
    assert container["readinessProbe"]["httpGet"]["path"] == "/health/ready"
    assert container["resources"]["limits"]["memory"]
    assert any("persistentVolumeClaim" in volume for volume in spec["volumes"])


def test_ci_uses_pinned_actions_and_enforces_model_and_image_acceptance():
    text = (ROOT / ".github/workflows/verify.yml").read_text()
    assert "verify_release.py --full" in text
    assert "--require-hashes" in text and "pip_audit" in text
    assert "--read-only --network none" in text
    import re

    refs = re.findall(r"uses: [^@\s]+@([^\s]+)", text)
    assert refs and all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in refs)
