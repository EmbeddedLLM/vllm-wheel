#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
"""
Script to normalize wheel filenames by removing local version identifiers.

This strips +git{commit} and similar suffixes to make versions appear as stable releases.
Example: torch-2.9.0+git1c57644d-cp312-linux_x86_64.whl
      -> torch-2.9.0-cp312-linux_x86_64.whl

This is necessary because local version identifiers:
1. Make packages look unofficial/developmental
2. May cause pip resolution issues
3. Are not allowed on PyPI.org

The transformation is done via simple file renaming, which is safe because:
- The wheel's internal metadata is not checked during installation from a custom index
- pip only cares about the filename when resolving from a simple repository
"""

import argparse
import re
import sys
from pathlib import Path


def normalize_wheel_filename(wheel_path: Path) -> Path:
    """
    Remove local version identifier from wheel filename.

    Wheel filename format (PEP 427):
    {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl

    We need to remove the local version identifier (the +local part) from the version.

    Args:
        wheel_path: Path to the wheel file

    Returns:
        Path: New path with normalized version, or original path if no change needed
    """
    filename = wheel_path.name

    # Check if this is actually a wheel file
    if not filename.endswith('.whl'):
        return wheel_path

    # Pattern to match and remove local version identifiers
    # Matches: +git{hash}, +rocm{version}, or any other +{localversion}
    # We want to remove everything from + until the next - or .whl

    # Split on the first '-' to get distribution name
    parts = filename.split('-')
    if len(parts) < 3:
        # Invalid wheel name, skip
        return wheel_path

    distribution = parts[0]
    version = parts[1]
    rest = '-'.join(parts[2:])  # python tag, abi, platform

    # Check if version has local identifier (contains +)
    if '+' not in version:
        # No local version, nothing to normalize
        return wheel_path

    # Remove the local version identifier
    base_version = version.split('+')[0]

    # Construct new filename
    new_filename = f"{distribution}-{base_version}-{rest}"
    new_path = wheel_path.parent / new_filename

    return new_path


def normalize_wheels_in_directory(directory: Path, dry_run: bool = False) -> dict:
    """
    Normalize all wheel filenames in a directory.

    Args:
        directory: Directory containing wheel files
        dry_run: If True, only print what would be done without actually renaming

    Returns:
        dict: Statistics about the normalization process
    """
    wheels = list(directory.glob("*.whl"))

    if not wheels:
        print(f"No wheel files found in {directory}")
        return {"total": 0, "normalized": 0, "unchanged": 0, "errors": 0}

    stats = {
        "total": len(wheels),
        "normalized": 0,
        "unchanged": 0,
        "errors": 0
    }

    print(f"Found {len(wheels)} wheel(s) in {directory}")
    print()

    for wheel_path in wheels:
        try:
            new_path = normalize_wheel_filename(wheel_path)

            if new_path == wheel_path:
                # No change needed
                stats["unchanged"] += 1
                print(f"  ✓ {wheel_path.name} (already normalized)")
            else:
                # Need to rename
                if dry_run:
                    print(f"  [DRY RUN] Would rename:")
                    print(f"    FROM: {wheel_path.name}")
                    print(f"    TO:   {new_path.name}")
                    stats["normalized"] += 1
                else:
                    # Check if target already exists
                    if new_path.exists():
                        print(f"  ✗ {wheel_path.name}")
                        print(f"    ERROR: Target {new_path.name} already exists!")
                        stats["errors"] += 1
                        continue

                    # Rename the file
                    wheel_path.rename(new_path)
                    print(f"  ✓ Normalized: {wheel_path.name}")
                    print(f"    -> {new_path.name}")
                    stats["normalized"] += 1

        except Exception as e:
            print(f"  ✗ {wheel_path.name}")
            print(f"    ERROR: {e}")
            stats["errors"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Normalize wheel filenames by removing local version identifiers"
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory containing wheel files to normalize"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually renaming files"
    )
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Recursively process subdirectories"
    )

    args = parser.parse_args()

    # Validate directory exists
    if not args.directory.exists():
        print(f"ERROR: Directory not found: {args.directory}", file=sys.stderr)
        sys.exit(1)

    if not args.directory.is_dir():
        print(f"ERROR: Not a directory: {args.directory}", file=sys.stderr)
        sys.exit(1)

    print("=" * 70)
    print("Wheel Version Normalization")
    print("=" * 70)
    if args.dry_run:
        print("DRY RUN MODE: No files will be modified")
        print("=" * 70)
    print()

    # Process directories
    if args.recursive:
        # Find all subdirectories containing wheels
        directories = set()
        for wheel in args.directory.rglob("*.whl"):
            directories.add(wheel.parent)

        if not directories:
            print(f"No wheels found in {args.directory} or its subdirectories")
            sys.exit(0)

        print(f"Found wheels in {len(directories)} directory(ies)\n")

        total_stats = {
            "total": 0,
            "normalized": 0,
            "unchanged": 0,
            "errors": 0
        }

        for directory in sorted(directories):
            print(f"Processing {directory.relative_to(args.directory) if directory != args.directory else directory}...")
            stats = normalize_wheels_in_directory(directory, args.dry_run)

            # Aggregate stats
            for key in total_stats:
                total_stats[key] += stats[key]
            print()

        stats = total_stats
    else:
        # Process single directory
        stats = normalize_wheels_in_directory(args.directory, args.dry_run)

    # Summary
    print()
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Total wheels processed: {stats['total']}")
    print(f"  Normalized: {stats['normalized']}")
    print(f"  Already normalized: {stats['unchanged']}")
    print(f"  Errors: {stats['errors']}")
    print("=" * 70)

    # Exit with error if there were any errors
    if stats['errors'] > 0:
        print(f"\n⚠️  Completed with {stats['errors']} error(s)", file=sys.stderr)
        sys.exit(1)

    if stats['normalized'] > 0:
        if args.dry_run:
            print(f"\n✅ Dry run complete: {stats['normalized']} wheel(s) would be normalized")
        else:
            print(f"\n✅ Successfully normalized {stats['normalized']} wheel(s)")
    else:
        print("\n✅ All wheels already have normalized versions")


if __name__ == "__main__":
    main()
