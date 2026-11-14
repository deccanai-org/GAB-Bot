"""Lock Linux/Python 3.11 wheels from pip reports and verified PyPI SHA-256 metadata.

Run with Python 3.11. Requirements are checked against Linux markers, including
requested extras. Any missing or incompatible dependency fails the lock operation.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent


def roots(path):
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("-r "):
            result.extend(roots(path.parent / line[3:].strip()))
        elif line and not line.startswith("-"):
            result.append(Requirement(line))
    return result


def closure(report, requested):
    packages = {canonicalize_name(item["metadata"]["name"]): item for item in report["install"]}
    environment = default_environment()
    environment.update(
        sys_platform="linux",
        platform_system="Linux",
        os_name="posix",
        python_version="3.11",
        python_full_version="3.11.18",
        implementation_version="3.11.18",
        platform_machine="x86_64",
        extra="",
    )
    required = {}
    queue = list(requested)
    visited = set()
    while queue:
        dependency = queue.pop()
        name = canonicalize_name(dependency.name)
        if name not in packages:
            raise ValueError(f"Linux dependency missing from resolver report: {dependency}")
        package = packages[name]
        if dependency.specifier and not dependency.specifier.contains(
            package["metadata"]["version"]
        ):
            raise ValueError(f"Incompatible locked dependency: {dependency}")
        extras = required.setdefault(name, set())
        extras.update(dependency.extras)
        state = (name, frozenset(extras))
        if state in visited:
            continue
        visited.add(state)
        for text in package["metadata"].get("requires_dist", []):
            child = Requirement(text)
            if child.marker is None or any(
                child.marker.evaluate({**environment, "extra": extra}) for extra in {"", *extras}
            ):
                queue.append(child)
    return [packages[name] for name in sorted(required)]


def hashed_line(package):
    metadata = package["metadata"]
    name, version = canonicalize_name(metadata["name"]), metadata["version"]
    with urllib.request.urlopen(
        f"https://pypi.org/pypi/{name}/{version}/json", timeout=45
    ) as response:
        data = json.load(response)
    hashes = sorted(
        {file["digests"]["sha256"] for file in data["urls"] if file["packagetype"] == "bdist_wheel"}
    )
    selected = package["download_info"]["archive_info"]["hashes"]["sha256"]
    if not hashes or selected not in hashes:
        raise ValueError(f"Resolver artifact does not match verified wheel hashes: {name}")
    return f"{name}=={version} \\\n" + " \\\n".join(
        f"    --hash=sha256:{value}" for value in hashes
    )


def main():
    if sys.version_info[:2] != (3, 11):
        raise SystemExit("Generate production locks with Python 3.11")
    with tempfile.TemporaryDirectory(prefix="gab-lock-") as directory:
        directory = Path(directory)
        constraints = directory / "runtime-constraints.txt"
        for source, target in [
            ("requirements.txt", "requirements.lock"),
            ("requirements-dev.txt", "requirements-dev.lock"),
        ]:
            report = directory / "report.json"
            command = [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--dry-run",
                "--ignore-installed",
                "--only-binary=:all:",
                "--python-version",
                "3.11",
                "--platform",
                "manylinux_2_28_x86_64",
                "--platform",
                "manylinux2014_x86_64",
                "--platform",
                "manylinux_2_27_x86_64",
                "--implementation",
                "cp",
                "--abi",
                "cp311",
                "--abi",
                "abi3",
                "--abi",
                "none",
                "--report",
                str(report),
                "--quiet",
                "-r",
                source,
            ]
            if constraints.exists():
                command.extend(["-c", str(constraints)])
            subprocess.run(command, cwd=ROOT, check=True)
            packages = closure(json.loads(report.read_text(encoding="utf-8")), roots(ROOT / source))
            with ThreadPoolExecutor(max_workers=6) as pool:
                lines = list(pool.map(hashed_line, packages))
            (ROOT / target).write_text(
                "# Linux x86_64 / Python 3.11. Regenerate: python scripts/lock_requirements.py\n"
                + "\n".join(lines)
                + "\n",
                encoding="utf-8",
            )
            if source == "requirements.txt":
                constraints.write_text(
                    "\n".join(
                        f"{p['metadata']['name']}=={p['metadata']['version']}" for p in packages
                    ),
                    encoding="utf-8",
                )
            print(f"{target}: {len(packages)} verified packages", flush=True)


if __name__ == "__main__":
    main()
