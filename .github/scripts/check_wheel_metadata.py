#!/usr/bin/env python3
"""
Check vLLM wheel metadata to verify dependency pinning.

Usage:
    python check_wheel_metadata.py <path_to_vllm_wheel.whl>

    Or to download from S3 first:
    wget http://your-s3-url/packages/vllm-*.whl
    python check_wheel_metadata.py vllm-*.whl
"""

import sys
import zipfile
from pathlib import Path
import re

def extract_metadata(wheel_path: str):
    """Extract and parse METADATA from wheel."""
    wheel = Path(wheel_path)

    if not wheel.exists():
        print(f"ERROR: Wheel not found: {wheel_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing wheel: {wheel.name}\n")

    with zipfile.ZipFile(wheel, 'r') as zf:
        # Find METADATA file (usually in vllm-*.dist-info/METADATA)
        metadata_files = [f for f in zf.namelist() if f.endswith('/METADATA')]

        if not metadata_files:
            print("ERROR: No METADATA file found in wheel!", file=sys.stderr)
            sys.exit(1)

        metadata_content = zf.read(metadata_files[0]).decode('utf-8')

    return metadata_content


def analyze_dependencies(metadata: str):
    """Parse and display dependency information."""
    lines = metadata.split('\n')

    # Extract basic info
    name = None
    version = None

    for line in lines:
        if line.startswith('Name: '):
            name = line.split('Name: ', 1)[1].strip()
        elif line.startswith('Version: '):
            version = line.split('Version: ', 1)[1].strip()

    print(f"Package: {name}")
    print(f"Version: {version}")
    print("\n" + "=" * 80)

    # Extract all Requires-Dist entries
    requires = []
    for line in lines:
        if line.startswith('Requires-Dist: '):
            dep = line.split('Requires-Dist: ', 1)[1].strip()
            requires.append(dep)

    print(f"\nTotal dependencies: {len(requires)}\n")

    # Highlight critical packages
    critical_packages = ['torch', 'triton', 'torchvision', 'amdsmi']

    print("=" * 80)
    print("CRITICAL ROCM DEPENDENCIES (should be pinned to exact versions):")
    print("=" * 80)

    found_critical = []
    for dep in requires:
        pkg_name = re.match(r'^([a-zA-Z0-9_-]+)', dep)
        if pkg_name:
            pkg = pkg_name.group(1).lower()
            if any(critical in pkg for critical in critical_packages):
                found_critical.append(dep)

                # Check if it's an exact pin (==)
                if '==' in dep and not '>=' in dep and not '<=' in dep:
                    print(f"✓ {dep}")
                else:
                    print(f"✗ {dep}  <-- NOT PINNED!")

    if not found_critical:
        print("WARNING: No torch/triton/torchvision/amdsmi found in dependencies!")
        print("This means the pinning did NOT work!\n")

    print("\n" + "=" * 80)
    print("OTHER DEPENDENCIES WITH LOOSE CONSTRAINTS:")
    print("=" * 80)

    # Show dependencies with >= or > constraints that might cause issues
    loose_deps = []
    for dep in requires:
        if dep not in found_critical:
            # Check if it has torch/triton in its own dependencies
            if any(pkg in dep.lower() for pkg in critical_packages):
                continue

            # Check for loose constraints
            if '>=' in dep or '>' in dep or '<' in dep:
                loose_deps.append(dep)

    # Show first 10 loose dependencies
    for dep in loose_deps[:10]:
        print(f"  {dep}")

    if len(loose_deps) > 10:
        print(f"  ... and {len(loose_deps) - 10} more")

    print("\n" + "=" * 80)
    print("DIAGNOSIS:")
    print("=" * 80)

    if found_critical:
        all_pinned = all('==' in dep for dep in found_critical)
        if all_pinned:
            print("✓ All critical ROCm packages are pinned to exact versions")
            print("\nIf pip is still installing wrong versions, the issue is:")
            print("  1. S3 index contains wrong wheel versions")
            print("  2. Transitive dependencies (other packages) have loose constraints")
            print("\nSolution:")
            print("  - Rebuild and re-upload to clean S3")
            print("  - Ensure only custom wheels are in S3 (latest Dockerfile.rocm fixes this)")
        else:
            print("✗ Some critical packages are NOT pinned to exact versions!")
            print("\nThis means pin_rocm_dependencies.py didn't work correctly.")
            print("\nCheck:")
            print("  1. Does /install contain custom wheels during build?")
            print("  2. Did pin_rocm_dependencies.py successfully modify requirements/rocm.txt?")
            print("  3. Did setup.py read the modified requirements file?")
    else:
        print("✗ Critical ROCm packages NOT FOUND in dependencies!")
        print("\nThis means vLLM wheel has no torch/triton dependencies at all,")
        print("which is incorrect. Check:")
        print("  1. Was VLLM_TARGET_DEVICE=rocm during build?")
        print("  2. Did setup.py read requirements/rocm.txt?")


def main():
    if len(sys.argv) != 2:
        print("Usage: python check_wheel_metadata.py <path_to_vllm_wheel.whl>", file=sys.stderr)
        sys.exit(1)

    wheel_path = sys.argv[1]

    metadata = extract_metadata(wheel_path)
    analyze_dependencies(metadata)


if __name__ == '__main__':
    main()
