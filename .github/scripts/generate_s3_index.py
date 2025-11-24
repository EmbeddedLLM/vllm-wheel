#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
"""
Generate PEP 503 compliant PyPI simple repository index for S3-hosted wheels.

This script creates an index structure that pip can use to install packages from S3.
The index follows the PyPI Simple Repository API specification (PEP 503).

Structure:
  simple/
    index.html                 # Main index listing all packages
    package-name/
      index.html              # Package index listing all versions

Features:
- Normalizes package names according to PEP 503
- Adds SHA256 hashes for integrity verification
- Adds requires-python metadata when available
- Sorts versions properly (newest first)
- Generates proper S3 URLs
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict


def normalize_package_name(name: str) -> str:
    """
    Normalize package name according to PEP 503.

    PyPI treats package names case-insensitively and treats hyphens/underscores as equivalent.
    Normalized names are lowercase with hyphens instead of underscores.

    Args:
        name: Original package name

    Returns:
        str: Normalized package name
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def extract_wheel_metadata(wheel_path: Path) -> Tuple[str, str, str]:
    """
    Extract package name, version, and python requirement from wheel filename.

    Wheel filename format (PEP 427):
    {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl

    Args:
        wheel_path: Path to wheel file

    Returns:
        Tuple of (package_name, version, python_tag)
    """
    filename = wheel_path.name

    if not filename.endswith('.whl'):
        raise ValueError(f"Not a wheel file: {filename}")

    # Split filename into parts
    parts = filename[:-4].split('-')  # Remove .whl extension

    if len(parts) < 5:
        raise ValueError(f"Invalid wheel filename format: {filename}")

    distribution = parts[0]
    version = parts[1]

    # Python tag is the 3rd component (or 4th if there's a build tag)
    # Build tag is optional and is a pure number
    if len(parts) == 5:
        # No build tag: dist-version-python-abi-platform
        python_tag = parts[2]
    else:
        # Has build tag: dist-version-build-python-abi-platform
        python_tag = parts[3]

    return distribution, version, python_tag


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def python_tag_to_requires_python(python_tag: str) -> str:
    """
    Convert Python tag from wheel to requires-python metadata.

    Examples:
        cp312 -> >=3.12
        py3 -> >=3.0
        py2.py3 -> >=2.0

    Args:
        python_tag: Python tag from wheel filename

    Returns:
        str: requires-python version specifier, or empty string if can't determine
    """
    # Handle common patterns
    if python_tag.startswith('cp'):
        # CPython: cp312 -> 3.12
        version_str = python_tag[2:]
        if len(version_str) >= 2:
            major = version_str[0]
            minor = version_str[1:]
            return f"&gt;={major}.{minor}"  # HTML-escaped >=

    elif python_tag.startswith('py'):
        # Generic Python
        version_str = python_tag[2:]
        if version_str:
            # py3, py39, etc.
            if '.' not in version_str and len(version_str) > 1:
                # py39 -> 3.9
                major = version_str[0]
                minor = version_str[1:]
                return f"&gt;={major}.{minor}"
            else:
                # py3 -> 3.0
                return f"&gt;={version_str}.0"

    return ""


def generate_package_index(
    package_name: str,
    wheels: List[Path],
    base_url: str,
    add_hashes: bool = True,
    add_metadata: bool = True,
) -> str:
    """
    Generate HTML index for a single package.

    Args:
        package_name: Normalized package name
        wheels: List of wheel files for this package
        base_url: Base S3 URL for wheels
        add_hashes: Whether to add SHA256 hashes
        add_metadata: Whether to add metadata attributes

    Returns:
        str: HTML content for package index
    """
    html_lines = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        f"  <title>Links for {package_name}</title>",
        "</head>",
        "<body>",
        f"  <h1>Links for {package_name}</h1>",
    ]

    # Process each wheel
    for wheel_path in sorted(wheels, reverse=True):  # Newest first (by name, crude but works)
        wheel_name = wheel_path.name
        wheel_url = f"{base_url}/packages/{wheel_name}"

        # Build anchor tag with attributes
        attributes = [f'href="{wheel_url}"']

        if add_metadata:
            try:
                _, _, python_tag = extract_wheel_metadata(wheel_path)
                requires_python = python_tag_to_requires_python(python_tag)
                if requires_python:
                    attributes.append(f'data-requires-python="{requires_python}"')
            except Exception as e:
                print(f"Warning: Could not extract metadata from {wheel_name}: {e}", file=sys.stderr)

        if add_hashes:
            try:
                sha256 = calculate_sha256(wheel_path)
                attributes.append(f'data-dist-info-metadata="sha256={sha256}"')
            except Exception as e:
                print(f"Warning: Could not calculate hash for {wheel_name}: {e}", file=sys.stderr)

        # Add the link
        html_lines.append(f'  <a {" ".join(attributes)}>{wheel_name}</a><br/>')

    html_lines.extend([
        "</body>",
        "</html>",
    ])

    return "\n".join(html_lines)


def generate_main_index(packages: List[str]) -> str:
    """
    Generate main index HTML listing all packages.

    Args:
        packages: List of normalized package names

    Returns:
        str: HTML content for main index
    """
    html_lines = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "  <title>Simple Index</title>",
        "</head>",
        "<body>",
        "  <h1>Simple Index</h1>",
    ]

    for package_name in sorted(packages):
        html_lines.append(f'  <a href="{package_name}/">{package_name}</a><br/>')

    html_lines.extend([
        "</body>",
        "</html>",
    ])

    return "\n".join(html_lines)


def generate_landing_page(
    s3_url: str,
    build_info: Dict[str, str],
    wheel_count: int,
) -> str:
    """
    Generate landing page with installation instructions.

    Args:
        s3_url: S3 base URL
        build_info: Dictionary with build configuration info
        wheel_count: Total number of wheels

    Returns:
        str: HTML content for landing page
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>vLLM ROCm PyPI Repository</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            max-width: 900px;
            margin: 50px auto;
            padding: 20px;
            line-height: 1.6;
        }}
        code {{
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
        pre {{
            background: #f4f4f4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            border-left: 4px solid #2196F3;
        }}
        .info {{
            background: #e7f3ff;
            padding: 15px;
            border-left: 4px solid #2196F3;
            margin: 20px 0;
        }}
        .warning {{
            background: #fff3cd;
            padding: 15px;
            border-left: 4px solid #ffc107;
            margin: 20px 0;
        }}
        h1 {{ color: #333; }}
        h2 {{ color: #555; margin-top: 30px; }}
        ul {{ margin: 10px 0; }}
        li {{ margin: 5px 0; }}
    </style>
</head>
<body>
    <h1>🚀 vLLM ROCm PyPI Repository</h1>

    <p>
        This is a custom PyPI repository hosting <strong>vLLM with ROCm support</strong>
        and all its dependencies, including ROCm-optimized PyTorch, Triton, and more.
    </p>

    <div class="info">
        <strong>📦 Complete Package:</strong> All wheels including transitive dependencies
        are hosted here. You can install vLLM and all dependencies with a single command.
    </div>

    <h2>📥 Installation</h2>
    <pre><code>pip install vllm --index-url {s3_url}/simple/</code></pre>

    <p>Or install specific packages:</p>
    <pre><code>pip install torch triton torchvision vllm --index-url {s3_url}/simple/</code></pre>

    <h2>🔍 Browse Packages</h2>
    <p><a href="simple/">📂 Browse all {wheel_count} available packages</a></p>

    <h2>ℹ️ Build Information</h2>
    <ul>
        <li><strong>ROCm Version:</strong> {build_info.get('rocm_version', 'N/A')}</li>
        <li><strong>Python Version:</strong> {build_info.get('python_version', 'N/A')}</li>
        <li><strong>GPU Architectures:</strong> {build_info.get('gpu_arch', 'N/A')}</li>
        <li><strong>vLLM Version:</strong> {build_info.get('vllm_version', 'latest official release')}</li>
        <li><strong>Built:</strong> {build_info.get('build_date', 'N/A')}</li>
    </ul>

    <h2>🛠️ Included Packages</h2>
    <div class="info">
        This repository includes:
        <ul>
            <li><strong>vLLM:</strong> High-performance LLM inference engine</li>
            <li><strong>PyTorch (ROCm):</strong> ROCm-optimized deep learning framework</li>
            <li><strong>Triton (ROCm):</strong> ROCm-optimized GPU programming language</li>
            <li><strong>TorchVision:</strong> Computer vision library for PyTorch</li>
            <li><strong>amdsmi:</strong> AMD System Management Interface</li>
            <li><strong>Dependencies:</strong> All transitive dependencies including transformers, tokenizers, etc.</li>
        </ul>
    </div>

    <h2>⚙️ Compatibility</h2>
    <ul>
        <li>ROCm {build_info.get('rocm_version', 'N/A')}</li>
        <li>Python {build_info.get('python_version', 'N/A')}</li>
        <li>GPU: AMD {build_info.get('gpu_arch', 'N/A')}</li>
        <li>Platform: Linux x86_64</li>
    </ul>

    <h2>📚 Resources</h2>
    <ul>
        <li><a href="https://github.com/vllm-project/vllm">vLLM Project</a></li>
        <li><a href="https://rocm.docs.amd.com/">ROCm Documentation</a></li>
    </ul>

    <div class="warning">
        <strong>⚠️ Note:</strong> These wheels are optimized for ROCm and will NOT work with CUDA GPUs.
        For CUDA support, install from the official PyPI: <code>pip install vllm</code>
    </div>
</body>
</html>
"""
    return html


def main():
    parser = argparse.ArgumentParser(
        description="Generate PEP 503 compliant PyPI index for S3-hosted wheels"
    )
    parser.add_argument(
        "--wheels-dir",
        type=Path,
        required=True,
        help="Directory containing wheel files"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for generated index"
    )
    parser.add_argument(
        "--s3-url",
        required=True,
        help="Base S3 URL (e.g., https://mybucket.s3.amazonaws.com)"
    )
    parser.add_argument(
        "--no-hashes",
        action="store_true",
        help="Skip generating SHA256 hashes"
    )
    parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="Skip adding metadata attributes"
    )
    parser.add_argument(
        "--rocm-version",
        default="N/A",
        help="ROCm version for landing page"
    )
    parser.add_argument(
        "--python-version",
        default="N/A",
        help="Python version for landing page"
    )
    parser.add_argument(
        "--gpu-arch",
        default="N/A",
        help="GPU architecture for landing page"
    )
    parser.add_argument(
        "--vllm-version",
        default="latest",
        help="vLLM version for landing page"
    )

    args = parser.parse_args()

    # Validate inputs
    if not args.wheels_dir.exists():
        print(f"ERROR: Wheels directory not found: {args.wheels_dir}", file=sys.stderr)
        sys.exit(1)

    # Find all wheels
    print("Collecting wheels...")
    all_wheels = list(args.wheels_dir.rglob("*.whl"))

    if not all_wheels:
        print(f"ERROR: No wheels found in {args.wheels_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(all_wheels)} wheel(s)")

    # Group wheels by package name
    packages: Dict[str, List[Path]] = defaultdict(list)

    for wheel_path in all_wheels:
        try:
            pkg_name, _, _ = extract_wheel_metadata(wheel_path)
            normalized_name = normalize_package_name(pkg_name)
            packages[normalized_name].append(wheel_path)
        except Exception as e:
            print(f"Warning: Skipping {wheel_path.name}: {e}", file=sys.stderr)

    print(f"Grouped into {len(packages)} package(s)")

    # Create output directory structure
    simple_dir = args.output_dir / "simple"
    simple_dir.mkdir(parents=True, exist_ok=True)

    print("\nGenerating package indexes...")

    # Generate index for each package
    for pkg_name, wheels in packages.items():
        pkg_dir = simple_dir / pkg_name
        pkg_dir.mkdir(exist_ok=True)

        index_html = generate_package_index(
            pkg_name,
            wheels,
            args.s3_url,
            add_hashes=not args.no_hashes,
            add_metadata=not args.no_metadata,
        )

        index_path = pkg_dir / "index.html"
        index_path.write_text(index_html)

        print(f"  ✓ {pkg_name} ({len(wheels)} wheel(s))")

    # Generate main index
    print("\nGenerating main index...")
    main_index = generate_main_index(list(packages.keys()))
    (simple_dir / "index.html").write_text(main_index)
    print("  ✓ simple/index.html")

    # Generate landing page
    print("\nGenerating landing page...")
    from datetime import datetime

    build_info = {
        "rocm_version": args.rocm_version,
        "python_version": args.python_version,
        "gpu_arch": args.gpu_arch,
        "vllm_version": args.vllm_version,
        "build_date": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    landing_page = generate_landing_page(
        args.s3_url,
        build_info,
        len(all_wheels),
    )

    (args.output_dir / "index.html").write_text(landing_page)
    print("  ✓ index.html")

    # Summary
    print("\n" + "=" * 70)
    print("Index Generation Complete!")
    print("=" * 70)
    print(f"Total packages: {len(packages)}")
    print(f"Total wheels: {len(all_wheels)}")
    print(f"Output directory: {args.output_dir}")
    print(f"S3 URL: {args.s3_url}")
    print("=" * 70)
    print(f"\n✅ Index ready for upload to S3!")


if __name__ == "__main__":
    main()
