#!/usr/bin/env python3
"""
Filter out system packages from pipdeptree output.

Removes packages that:
1. Are in a known blacklist of system packages
2. Are installed in system directories (/dist-packages)

This prevents trying to download packages from PyPI that:
- Don't have wheels available
- Are pre-installed in target environments
- Have incompatible versions
"""

import subprocess
import re
import sys
from pathlib import Path

# Known system packages to exclude (pre-installed in base ROCm image)
SYSTEM_PACKAGES = {
    'dbus-python', 'pygobject', 'pycairo',
    'distro', 'secretstorage', 'jeepney'
}

def filter_system_packages(input_file: str, output_file: str):
    """Filter system packages from dependency list."""
    with open(input_file) as f:
        deps = f.readlines()

    filtered = []
    excluded = []

    for line in deps:
        # Extract package name from dependency line
        match = re.match(r'^([a-zA-Z0-9_-]+)', line)
        if not match:
            continue
        pkg = match.group(1).lower()

        # Check 1: Exclude blacklisted packages
        if pkg in SYSTEM_PACKAGES:
            print(f"Excluding blacklisted: {line.strip()}", file=sys.stderr)
            excluded.append(line.strip())
            continue

        # Check 2: Check installation location to exclude system-installed packages
        try:
            result = subprocess.run(
                ['pip', 'show', pkg],
                capture_output=True,
                text=True,
                timeout=2
            )
            if '/dist-packages' in result.stdout:
                print(f"Excluding system location: {line.strip()}", file=sys.stderr)
                excluded.append(line.strip())
                continue
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            pass

        filtered.append(line)

    # Write filtered dependencies
    with open(output_file, 'w') as f:
        f.writelines(filtered)

    # Print summary
    print(f"\nFiltering summary:", file=sys.stderr)
    print(f"  Total dependencies: {len(deps)}", file=sys.stderr)
    print(f"  Excluded: {len(excluded)}", file=sys.stderr)
    print(f"  Remaining: {len(filtered)}", file=sys.stderr)

    return len(filtered)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_file> <output_file>", file=sys.stderr)
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    if not Path(input_file).exists():
        print(f"ERROR: Input file not found: {input_file}", file=sys.stderr)
        sys.exit(1)

    count = filter_system_packages(input_file, output_file)
    print(f"\n✓ Filtered dependencies written to: {output_file}", file=sys.stderr)
    sys.exit(0)
