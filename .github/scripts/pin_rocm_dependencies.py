#!/usr/bin/env python3
"""
Pin vLLM dependencies to exact versions of custom ROCm wheels.

This script modifies vLLM's pyproject.toml to replace loose version constraints
with exact versions of custom-built ROCm wheels (torch, triton, torchvision, amdsmi).

This ensures that 'pip install vllm' automatically installs the correct custom wheels
instead of allowing pip to download different versions from PyPI.
"""

import re
import sys
from pathlib import Path
from typing import Dict

def extract_version_from_wheel(wheel_name: str) -> str:
    """
    Extract version from wheel filename.

    Example:
        torch-2.9.0a0+git1c57644-cp312-cp312-linux_x86_64.whl -> 2.9.0a0+git1c57644
        triton-3.4.0-cp312-cp312-linux_x86_64.whl -> 3.4.0
    """
    # Wheel format: {distribution}-{version}(-{build tag})?-{python}-{abi}-{platform}.whl
    parts = wheel_name.replace('.whl', '').split('-')

    if len(parts) < 5:
        raise ValueError(f"Invalid wheel filename format: {wheel_name}")

    # Version is the second part
    version = parts[1]
    return version


def get_custom_wheel_versions(install_dir: str) -> Dict[str, str]:
    """
    Read /install directory and extract versions of custom wheels.

    Returns:
        Dict mapping package names to exact versions
    """
    install_path = Path(install_dir)
    if not install_path.exists():
        print(f"ERROR: Install directory not found: {install_dir}", file=sys.stderr)
        sys.exit(1)

    versions = {}

    # Map wheel prefixes to package names (handle triton_kernels separately)
    package_mapping = {
        'torch': 'torch',
        'triton-': 'triton',  # Use dash to avoid matching triton_kernels
        'triton_kernels': 'triton-kernels',
        'torchvision': 'torchvision',
        'amdsmi': 'amdsmi',
    }

    for wheel_file in install_path.glob('*.whl'):
        wheel_name = wheel_file.name

        for prefix, package_name in package_mapping.items():
            if wheel_name.startswith(prefix):
                try:
                    version = extract_version_from_wheel(wheel_name)
                    versions[package_name] = version
                    print(f"Found {package_name}=={version}", file=sys.stderr)
                except Exception as e:
                    print(f"WARNING: Could not extract version from {wheel_name}: {e}", file=sys.stderr)
                break

    return versions


def pin_dependencies_in_pyproject(pyproject_path: str, versions: Dict[str, str]):
    """
    Modify pyproject.toml to pin exact versions of custom wheels.

    Replaces loose constraints like:
        torch >= 2.9.0
    With exact pins:
        torch == 2.9.0a0+git1c57644
    """
    pyproject_file = Path(pyproject_path)

    if not pyproject_file.exists():
        print(f"ERROR: pyproject.toml not found: {pyproject_path}", file=sys.stderr)
        sys.exit(1)

    # Backup original file
    backup_file = pyproject_file.with_suffix('.toml.bak')
    pyproject_file.rename(backup_file)

    with open(backup_file, 'r') as f:
        content = f.read()

    # Track modifications
    modifications = []

    # Pattern to match dependency specifications
    # Matches: torch >= 2.9.0, torch>=2.9.0, "torch >= 2.9.0", 'torch >= 2.9.0'
    for package_name, exact_version in versions.items():
        # Handle both torch and triton-kernels (with hyphen)
        pattern_name = package_name.replace('-', '[-_]')  # Match both - and _

        # Patterns to match various dependency formats
        patterns = [
            # Match: torch >= 2.9.0 or torch>=2.9.0 (without quotes)
            (rf'(\s+){pattern_name}\s*>=\s*[\d.]+\s*(?:,|$|\n)',
             rf'\1{package_name} == {exact_version}\n'),

            # Match: "torch >= 2.9.0" or 'torch >= 2.9.0' (with quotes)
            (rf'(["\']){pattern_name}\s*>=\s*[\d.]+\s*(?:,.*?)?(["\'])',
             rf'\1{package_name} == {exact_version}\2'),

            # Match: torch = ">= 2.9.0" (TOML format)
            (rf'{pattern_name}\s*=\s*">=\s*[\d.]+"',
             f'{package_name} = "== {exact_version}"'),
        ]

        for pattern, replacement in patterns:
            if re.search(pattern, content):
                content = re.sub(pattern, replacement, content)
                modifications.append(f"{package_name} pinned to {exact_version}")

    # Write modified content
    with open(pyproject_file, 'w') as f:
        f.write(content)

    # Print summary
    if modifications:
        print("\n✓ Modified vLLM dependencies:", file=sys.stderr)
        for mod in modifications:
            print(f"  - {mod}", file=sys.stderr)
    else:
        print("\n⚠ WARNING: No dependencies were modified. Check patterns!", file=sys.stderr)

    print(f"\n✓ Patched pyproject.toml: {pyproject_path}", file=sys.stderr)
    print(f"  Backup saved: {backup_file}", file=sys.stderr)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <install_dir> <pyproject.toml>", file=sys.stderr)
        print(f"Example: {sys.argv[0]} /install /app/vllm/pyproject.toml", file=sys.stderr)
        sys.exit(1)

    install_dir = sys.argv[1]
    pyproject_path = sys.argv[2]

    print("=" * 70, file=sys.stderr)
    print("Pinning vLLM dependencies to custom ROCm wheel versions", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # Get versions from custom wheels
    print(f"\nScanning {install_dir} for custom wheels...", file=sys.stderr)
    versions = get_custom_wheel_versions(install_dir)

    if not versions:
        print("\nERROR: No custom wheels found in /install!", file=sys.stderr)
        sys.exit(1)

    # Pin dependencies in pyproject.toml
    print(f"\nPatching {pyproject_path}...", file=sys.stderr)
    pin_dependencies_in_pyproject(pyproject_path, versions)

    print("\n" + "=" * 70, file=sys.stderr)
    print("✓ Dependency pinning complete!", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    sys.exit(0)


if __name__ == '__main__':
    main()
