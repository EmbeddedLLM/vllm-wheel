#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
"""
Script to download Python package wheels
from PyPI with version range support.
This script handles loose version specifications
by downloading multiple compatible versions.
"""

import argparse
import subprocess
import sys
import tempfile
import os
from pathlib import Path

import requests
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version


def parse_requirements_file(filepath: Path) -> list[str]:
    """Parse a requirements file and return list of requirement strings."""
    requirements = []

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue
            # Handle -r includes recursively
            if line.startswith("-r "):
                included_file = filepath.parent / line[3:].strip()
                requirements.extend(parse_requirements_file(included_file))
            else:
                # Strip inline comments (everything after # that's not in quotes)
                # Simple approach: split on # and take first part
                if '#' in line:
                    line = line.split('#')[0].strip()
                if line:  # Only add if something remains after stripping
                    requirements.append(line)

    return requirements


def get_pypi_package_versions(package_name: str, specifier: SpecifierSet) -> list[str]:
    """Get all versions of a package from PyPI that match the specifier."""
    try:
        url = f"https://pypi.org/pypi/{package_name}/json"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()

        # Get all available versions
        all_versions = list(data["releases"].keys())

        # Filter versions that match the specifier
        matching_versions = []
        for ver_str in all_versions:
            try:
                version = Version(ver_str)
                if version in specifier:
                    matching_versions.append(ver_str)
            except InvalidVersion:
                continue

        # Sort versions (newest first) and limit to avoid too many downloads
        matching_versions.sort(key=lambda v: Version(v), reverse=True)

        return matching_versions
    except Exception as e:
        print(
            f"Warning: Could not fetch versions for {package_name}: {e}",
            file=sys.stderr,
        )
        return []


def select_versions_to_download(
    versions: list[str], max_versions: int = 5
) -> list[str]:
    """
    Select a subset of versions to download.
    Strategy: Download latest version +
        a few older versions to satisfy loose requirements.
    """
    if not versions:
        return []

    if len(versions) <= max_versions:
        return versions

    # Take the latest version, some middle versions, and oldest in the range
    selected = [versions[0]]  # Latest

    # Sample from the middle
    step = len(versions) // (max_versions - 1)
    for i in range(1, max_versions - 1):
        idx = min(i * step, len(versions) - 1)
        selected.append(versions[idx])

    # Add oldest in range
    if versions[-1] not in selected:
        selected.append(versions[-1])

    return selected


def download_wheels(
    package_name: str,
    versions: list[str],
    output_dir: Path,
    python_version: str,
    extras: list[str] = None,
) -> None:
    """Download wheels for specified versions of a package."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for version in versions:
        # Construct package spec
        if extras:
            package_spec = f"{package_name}[{','.join(extras)}]=={version}"
        else:
            package_spec = f"{package_name}=={version}"

        print(f"  Downloading {package_spec}...")

        try:
            # Use pip download for current platform
            # NOTE: Not using --no-deps to include all transitive dependencies
            # NOTE: Not using --python-version or --platform because pip doesn't allow them
            #       with dependency downloads. Instead, pip uses the current environment's
            #       Python version and platform (which is correct for GitHub Actions runner)
            cmd = [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--prefer-binary",
                "--dest",
                str(output_dir),
                package_spec,
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                print(
                    f"    Warning: Failed to download {package_spec}", file=sys.stderr
                )
                print(f"    Error: {result.stderr}", file=sys.stderr)
        except subprocess.TimeoutExpired:
            print(f"    Warning: Timeout downloading {package_spec}", file=sys.stderr)
        except Exception as e:
            print(
                f"    Warning: Error downloading {package_spec}: {e}", file=sys.stderr
            )


def process_requirement(
    req_string: str, output_dir: Path, python_version: str, max_versions: int = 5
) -> None:
    """Process a single requirement and download appropriate wheels."""
    try:
        req = Requirement(req_string)
        package_name = req.name
        specifier = req.specifier if req.specifier else SpecifierSet()
        extras = list(req.extras) if req.extras else []

        print(f"\nProcessing: {package_name} {specifier}")
        if extras:
            print(f"  Extras: {extras}")

        # Skip certain packages that should be built from source
        skip_packages = {
            "torch",
            "torchvision",
            "torchaudio",
            "triton",
            "amdsmi",
            "vllm",
        }
        if package_name.lower() in skip_packages:
            print("  Skipping (built from source)")
            return

        # Handle packages with markers (platform-specific)
        if req.marker:
            print(f"  Marker: {req.marker}")

        # Get matching versions from PyPI
        if specifier:
            versions = get_pypi_package_versions(package_name, specifier)
            selected_versions = select_versions_to_download(versions, max_versions)

            if selected_versions:
                print(
                    f"  Found {len(versions)} matching versions, "
                    f"downloading {len(selected_versions)}"
                )
                download_wheels(
                    package_name, selected_versions, output_dir, python_version, extras
                )
            else:
                print("  No matching versions found, downloading latest...")
                download_wheels(
                    package_name, ["latest"], output_dir, python_version, extras
                )
        else:
            # No version specified, download latest
            print("  No version specifier, downloading latest...")
            versions = get_pypi_package_versions(package_name, SpecifierSet())
            if versions:
                download_wheels(
                    package_name, [versions[0]], output_dir, python_version, extras
                )
            else:
                download_wheels(
                    package_name, ["latest"], output_dir, python_version, extras
                )

    except Exception as e:
        print(f"Error processing requirement '{req_string}': {e}", file=sys.stderr)


def download_with_base_wheels(
    requirements_file: Path,
    base_wheels_dir: Path,
    output_dir: Path,
    python_version: str,
) -> None:
    """
    Download dependencies after installing base wheels to ensure correct resolution.

    This is critical because:
    1. Base wheels (torch, triton, etc.) are ROCm builds, not from PyPI
    2. When pip resolves dependencies, it needs the actual torch installed
    3. Otherwise pip might try to install CUDA-compatible versions from PyPI

    Strategy:
    1. Create a temporary virtual environment
    2. Install base wheels (torch, triton, torchvision, amdsmi) into it
    3. Run pip download from within that environment
    4. pip will now resolve dependencies compatible with YOUR torch version

    Args:
        requirements_file: Path to requirements.txt
        base_wheels_dir: Directory containing pre-built base wheels
        output_dir: Where to save downloaded wheels
        python_version: Python version string (for logging)
    """
    print("=" * 70)
    print("DOWNLOADING DEPENDENCIES WITH BASE WHEELS INSTALLED")
    print("=" * 70)
    print(f"Strategy: Install base wheels first, then download dependencies")
    print(f"This ensures all dependencies are compatible with ROCm torch")
    print()

    # Find base wheels
    base_wheels = list(base_wheels_dir.glob("*.whl"))
    if not base_wheels:
        print(f"ERROR: No wheels found in {base_wheels_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(base_wheels)} base wheel(s):")
    for wheel in base_wheels:
        size_mb = wheel.stat().st_size / (1024 * 1024)
        print(f"  - {wheel.name} ({size_mb:.1f} MB)")
    print()

    # Create temporary venv
    print("Creating temporary virtual environment...")
    with tempfile.TemporaryDirectory() as tmpdir:
        venv_dir = Path(tmpdir) / "venv"

        # Create venv using current Python
        print(f"  venv location: {venv_dir}")
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"ERROR: Failed to create venv", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            sys.exit(1)

        print("  ✓ Virtual environment created")

        # Determine pip path in venv
        if os.name == 'nt':  # Windows
            pip_path = venv_dir / "Scripts" / "pip"
        else:  # Unix/Linux
            pip_path = venv_dir / "bin" / "pip"

        # Upgrade pip in venv
        print("  Upgrading pip in venv...")
        subprocess.run(
            [str(pip_path), "install", "--upgrade", "pip"],
            capture_output=True,
            check=True,
        )
        print("  ✓ pip upgraded")

        # Install base wheels into venv (without dependencies)
        print()
        print("Installing base wheels into venv (this may take a few minutes)...")
        for wheel in base_wheels:
            print(f"  Installing {wheel.name}...")
            result = subprocess.run(
                [str(pip_path), "install", "--no-deps", str(wheel)],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                print(f"  WARNING: Failed to install {wheel.name}", file=sys.stderr)
                print(result.stderr, file=sys.stderr)
            else:
                print(f"  ✓ {wheel.name} installed")

        print()
        print("Base wheels installed successfully!")
        print()

        # Now download dependencies using the venv's pip
        # This ensures pip resolves against the installed ROCm torch
        print("Downloading dependencies (this will take several minutes)...")
        print(f"  Requirements: {requirements_file}")
        print(f"  Output: {output_dir}")
        print()

        output_dir.mkdir(parents=True, exist_ok=True)

        # Run pip download from venv
        # This will resolve dependencies based on the installed torch
        cmd = [
            str(pip_path),
            "download",
            "-r", str(requirements_file),
            "--dest", str(output_dir),
            "--prefer-binary",
        ]

        print(f"Running: {' '.join(str(c) for c in cmd)}")
        print()

        result = subprocess.run(
            cmd,
            capture_output=False,  # Show output in real-time
            text=True,
        )

        if result.returncode != 0:
            print(f"\nERROR: Dependency download failed!", file=sys.stderr)
            sys.exit(1)

        print()
        print("✓ Dependencies downloaded successfully!")

    # venv is automatically cleaned up when exiting the context manager
    print("✓ Temporary venv cleaned up")
    print()


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Download Python dependency wheels from PyPI with version range support"
        ),
    )
    parser.add_argument(
        "--requirements", type=Path, required=True, help="Path to requirements.txt file"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to store downloaded wheels",
    )
    parser.add_argument(
        "--python-version", default="3.12", help="Python version (default: 3.12)"
    )
    parser.add_argument(
        "--max-versions",
        type=int,
        default=3,
        help="Maximum versions to download per package (default: 3)",
    )
    parser.add_argument(
        "--base-wheels-dir",
        type=Path,
        required=False,
        help="Directory containing pre-built base wheels (torch, triton, etc.). "
             "If provided, these will be installed first to ensure correct dependency resolution.",
    )

    args = parser.parse_args()

    # Parse requirements file
    print(f"Parsing requirements from: {args.requirements}")
    requirements = parse_requirements_file(args.requirements)
    print(f"Found {len(requirements)} requirements")

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Check if base-wheels-dir was provided
    if args.base_wheels_dir:
        # NEW APPROACH: Install base wheels first, then download dependencies
        # This ensures correct dependency resolution for ROCm builds
        print()
        print("=" * 70)
        print("Using BASE WHEELS strategy for dependency resolution")
        print("=" * 70)
        print()

        if not args.base_wheels_dir.exists():
            print(f"ERROR: Base wheels directory not found: {args.base_wheels_dir}", file=sys.stderr)
            sys.exit(1)

        download_with_base_wheels(
            args.requirements,
            args.base_wheels_dir,
            args.output_dir,
            args.python_version,
        )
    else:
        # OLD APPROACH: Download dependencies without base wheels
        # This may result in incomplete transitive dependency resolution
        print()
        print("=" * 70)
        print("Using STANDARD strategy (no base wheels)")
        print("=" * 70)
        print("NOTE: This may result in incomplete transitive dependencies.")
        print("For best results, use --base-wheels-dir option.")
        print("=" * 70)
        print()

        # Process each requirement
        for req_string in requirements:
            process_requirement(
                req_string, args.output_dir, args.python_version, args.max_versions
            )

    # Summary
    wheels = list(args.output_dir.glob("*.whl"))
    print(f"\n{'=' * 60}")
    print(f"Downloaded {len(wheels)} wheels to {args.output_dir}")
    print(f"{'=' * 60}")

    # Validate critical packages were downloaded (including key transitive dependencies)
    CRITICAL_PACKAGES = {
        'regex', 'numpy', 'transformers', 'tokenizers', 'protobuf',
        'pydantic', 'aiohttp', 'requests', 'tqdm', 'fastapi',
        'typing-extensions', 'packaging', 'pyyaml', 'anyio'
    }

    # Get set of downloaded package names (normalized)
    downloaded_packages = set()
    for wheel in wheels:
        # Extract package name from wheel filename (before first hyphen or underscore followed by version)
        name = wheel.stem.split('-')[0].lower().replace('_', '-')
        downloaded_packages.add(name)

    # Check for missing critical packages
    missing_critical = CRITICAL_PACKAGES - downloaded_packages

    if missing_critical:
        print(f"\n{'=' * 60}")
        print("ERROR: Missing critical packages!")
        print(f"{'=' * 60}")
        for pkg in sorted(missing_critical):
            print(f"  - {pkg}")
        print(f"\nDownloaded packages: {sorted(downloaded_packages)}")
        print("\nPlease check the download logs above for errors.")
        print("These packages are required for vllm to function properly.")
        sys.exit(1)

    print(f"\n✅ All critical packages downloaded successfully!")


if __name__ == "__main__":
    main()
