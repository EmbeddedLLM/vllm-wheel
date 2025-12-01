#!/bin/bash
set -e

#############################################################################
# cleanup_pypi_duplicates.sh
#
# Removes PyPI versions of custom ROCm packages from the wheel collection.
# Dynamically identifies custom wheel versions (no hardcoding).
#
# Usage: cleanup_pypi_duplicates.sh <base-wheels-dir> <all-wheels-dir>
#############################################################################

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <base-wheels-dir> <all-wheels-dir>"
    exit 1
fi

BASE_WHEELS_DIR="$1"
ALL_WHEELS_DIR="$2"

echo "========================================="
echo "PyPI Duplicate Cleanup"
echo "========================================="
echo "Base wheels: $BASE_WHEELS_DIR"
echo "All wheels:  $ALL_WHEELS_DIR"
echo ""

# Verify directories exist
if [ ! -d "$BASE_WHEELS_DIR" ]; then
    echo "✗ FATAL ERROR: Base wheels directory not found!"
    echo "   Directory: $BASE_WHEELS_DIR"
    echo ""
    echo "Available directories:"
    ls -la "$(dirname "$BASE_WHEELS_DIR")" 2>/dev/null || echo "Parent directory not found!"
    echo ""
    echo "Cannot proceed without custom wheel reference!"
    exit 1
fi

if [ ! -d "$ALL_WHEELS_DIR" ]; then
    echo "✗ FATAL ERROR: All wheels directory not found!"
    echo "   Directory: $ALL_WHEELS_DIR"
    exit 1
fi

echo "✓ Directories verified"
echo ""

# Count before cleanup
BEFORE_COUNT=$(ls "$ALL_WHEELS_DIR"/*.whl 2>/dev/null | wc -l)
echo "Total wheels before cleanup: $BEFORE_COUNT"
echo ""

#############################################################################
# Function: Extract version from wheel filename
# Example: torch-2.9.0a0+git1c57644-cp312-cp312-linux_x86_64.whl -> 2.9.0a0+git1c57644
#############################################################################
extract_version() {
    local wheel_name="$1"
    # Wheel format: {name}-{version}-{python}-{abi}-{platform}.whl
    # Extract the second field (version)
    basename "$wheel_name" | sed 's/\.whl$//' | cut -d'-' -f2
}

#############################################################################
# Function: Extract package name from wheel filename
# Example: torch-2.9.0a0+git1c57644-cp312-cp312-linux_x86_64.whl -> torch
#############################################################################
extract_package_name() {
    local wheel_name="$1"
    basename "$wheel_name" | cut -d'-' -f1
}

#############################################################################
# Function: Check if vLLM wheel has correct torch/triton pinning
# Uses expected versions from base wheels directory
# Returns: 0 if correct pinning found, 1 otherwise
#############################################################################
check_vllm_metadata() {
    local wheel_path="$1"
    local expected_torch_version="$2"
    local expected_triton_version="$3"
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local check_script="$script_dir/check_wheel_metadata.py"

    if [ ! -f "$check_script" ]; then
        echo "  ⚠️  WARNING: check_wheel_metadata.py not found at $check_script"
        return 1
    fi

    # Run check_wheel_metadata.py and capture output
    local output=$(python3 "$check_script" "$wheel_path" 2>&1)

    # Check for torch and triton pinning with expected versions
    local has_torch=false
    local has_triton=false

    if [ -n "$expected_torch_version" ]; then
        if echo "$output" | grep -q "torch==$expected_torch_version"; then
            has_torch=true
        fi
    else
        # If no expected version, just check if torch is pinned
        if echo "$output" | grep -q "✓.*torch=="; then
            has_torch=true
        fi
    fi

    if [ -n "$expected_triton_version" ]; then
        if echo "$output" | grep -q "triton==$expected_triton_version"; then
            has_triton=true
        fi
    else
        # If no expected version, just check if triton is pinned
        if echo "$output" | grep -q "✓.*triton=="; then
            has_triton=true
        fi
    fi

    if [ "$has_torch" = true ] && [ "$has_triton" = true ]; then
        return 0  # Correct pinning found
    fi

    return 1  # Pinning missing or incorrect
}

#############################################################################
# Process each package type
#############################################################################

PACKAGES_TO_CHECK=("torch" "triton" "torchvision" "amdsmi" "flash_attn" "aiter")
REMOVED_COUNT=0
MISSING_CUSTOM_WHEELS=()

for pkg in "${PACKAGES_TO_CHECK[@]}"; do
    echo "========================================="
    echo "Processing: $pkg"
    echo "========================================="

    # Find custom wheel in base-wheels directory
    CUSTOM_WHEEL=$(ls "$BASE_WHEELS_DIR"/${pkg}-*.whl 2>/dev/null | head -1)

    if [ -z "$CUSTOM_WHEEL" ]; then
        echo "✗ ERROR: No custom $pkg wheel found in $BASE_WHEELS_DIR"
        echo "   This is CRITICAL - cannot determine which version to keep!"
        MISSING_CUSTOM_WHEELS+=("$pkg")
        echo ""
        continue
    fi

    # Extract custom version
    CUSTOM_VERSION=$(extract_version "$CUSTOM_WHEEL")
    CUSTOM_WHEEL_NAME=$(basename "$CUSTOM_WHEEL")

    echo "✓ Found custom wheel: $CUSTOM_WHEEL_NAME"
    echo "  Custom version: $CUSTOM_VERSION"
    echo ""

    # Check all wheels in all-wheels directory
    echo "Checking all $pkg wheels in $ALL_WHEELS_DIR:"

    FOUND_CUSTOM=false
    for wheel in "$ALL_WHEELS_DIR"/${pkg}-*.whl; do
        if [ ! -f "$wheel" ]; then
            continue
        fi

        wheel_name=$(basename "$wheel")
        wheel_version=$(extract_version "$wheel")

        if [ "$wheel_version" = "$CUSTOM_VERSION" ]; then
            echo "  ✓ KEEP: $wheel_name (matches custom version)"
            FOUND_CUSTOM=true
        else
            echo "  ✗ REMOVE: $wheel_name (version: $wheel_version, expected: $CUSTOM_VERSION)"
            rm -f "$wheel"
            REMOVED_COUNT=$((REMOVED_COUNT + 1))
        fi
    done

    if [ "$FOUND_CUSTOM" = false ]; then
        echo "  ⚠️  WARNING: Custom $pkg wheel (v$CUSTOM_VERSION) not found in all-wheels!"
        echo "     This might indicate a problem with wheel collection."
    fi

    echo ""
done

#############################################################################
# Handle vLLM wheels (keep only the one with correct metadata pinning)
#############################################################################

echo "========================================="
echo "Processing: vllm (checking metadata)"
echo "========================================="

# Get expected torch/triton versions from base wheels
TORCH_WHEEL=$(ls "$BASE_WHEELS_DIR"/torch-*.whl 2>/dev/null | head -1)
TRITON_WHEEL=$(ls "$BASE_WHEELS_DIR"/triton-*.whl 2>/dev/null | head -1)

EXPECTED_TORCH_VERSION=""
EXPECTED_TRITON_VERSION=""

if [ -n "$TORCH_WHEEL" ]; then
    EXPECTED_TORCH_VERSION=$(extract_version "$TORCH_WHEEL")
    echo "Expected torch version: $EXPECTED_TORCH_VERSION"
fi

if [ -n "$TRITON_WHEEL" ]; then
    EXPECTED_TRITON_VERSION=$(extract_version "$TRITON_WHEEL")
    echo "Expected triton version: $EXPECTED_TRITON_VERSION"
fi

echo ""

VLLM_WHEELS=("$ALL_WHEELS_DIR"/vllm-*.whl)
VLLM_COUNT=${#VLLM_WHEELS[@]}

if [ -f "${VLLM_WHEELS[0]}" ]; then
    echo "Found $VLLM_COUNT vllm wheel(s):"
    for wheel in "${VLLM_WHEELS[@]}"; do
        wheel_name=$(basename "$wheel")
        wheel_version=$(extract_version "$wheel")
        echo "  - $wheel_name (version: $wheel_version)"
    done
    echo ""

    if [ $VLLM_COUNT -gt 1 ]; then
        echo "⚠️  WARNING: Multiple vllm wheels detected!"
        echo "   Checking metadata to find the correctly pinned one..."
        echo ""

        # Check each wheel's metadata
        CORRECT_WHEEL=""
        for wheel in "${VLLM_WHEELS[@]}"; do
            wheel_name=$(basename "$wheel")
            echo "Checking metadata: $wheel_name"

            if check_vllm_metadata "$wheel" "$EXPECTED_TORCH_VERSION" "$EXPECTED_TRITON_VERSION"; then
                echo "  ✓ CORRECT: Has torch==$EXPECTED_TORCH_VERSION and triton==$EXPECTED_TRITON_VERSION pinning"
                if [ -z "$CORRECT_WHEEL" ]; then
                    CORRECT_WHEEL="$wheel"
                else
                    echo "  ⚠️  WARNING: Multiple wheels with correct pinning found!"
                fi
            else
                echo "  ✗ INCORRECT: Missing or wrong torch/triton pinning"
            fi
            echo ""
        done

        # Keep correct wheel, remove others
        if [ -n "$CORRECT_WHEEL" ]; then
            CORRECT_NAME=$(basename "$CORRECT_WHEEL")
            echo "Decision: Keeping $CORRECT_NAME (has correct metadata)"
            echo ""

            for wheel in "${VLLM_WHEELS[@]}"; do
                wheel_name=$(basename "$wheel")
                if [ "$wheel" = "$CORRECT_WHEEL" ]; then
                    echo "  ✓ KEEP: $wheel_name (correctly pinned)"
                else
                    echo "  ✗ REMOVE: $wheel_name (incorrect/missing pinning)"
                    rm -f "$wheel"
                    REMOVED_COUNT=$((REMOVED_COUNT + 1))
                fi
            done
        else
            echo "⚠️  ERROR: No vllm wheel with correct metadata found!"
            echo "   Falling back to keeping first wheel..."
            FIRST_VLLM="${VLLM_WHEELS[0]}"
            FIRST_NAME=$(basename "$FIRST_VLLM")
            echo "  ✓ KEEP: $FIRST_NAME (fallback)"

            for ((i=1; i<$VLLM_COUNT; i++)); do
                wheel="${VLLM_WHEELS[$i]}"
                wheel_name=$(basename "$wheel")
                echo "  ✗ REMOVE: $wheel_name (duplicate)"
                rm -f "$wheel"
                REMOVED_COUNT=$((REMOVED_COUNT + 1))
            done
        fi
        echo ""
    else
        VLLM_NAME=$(basename "${VLLM_WHEELS[0]}")
        echo "✓ Single vllm wheel found: $VLLM_NAME"
        echo "  Checking metadata to verify correctness..."
        echo ""

        if check_vllm_metadata "${VLLM_WHEELS[0]}" "$EXPECTED_TORCH_VERSION" "$EXPECTED_TRITON_VERSION"; then
            echo "  ✓ Metadata is correct (has torch==$EXPECTED_TORCH_VERSION and triton==$EXPECTED_TRITON_VERSION pinning)"
        else
            echo "  ⚠️  WARNING: Metadata may be incorrect (missing or wrong torch/triton pinning)"
            echo "     Expected: torch==$EXPECTED_TORCH_VERSION, triton==$EXPECTED_TRITON_VERSION"
        fi
        echo ""
    fi
else
    echo "⚠️  WARNING: No vllm wheels found in $ALL_WHEELS_DIR"
    echo "   This might indicate a build problem."
    echo ""
fi

#############################################################################
# Summary
#############################################################################

AFTER_COUNT=$(ls "$ALL_WHEELS_DIR"/*.whl 2>/dev/null | wc -l)

echo "========================================="
echo "Cleanup Summary"
echo "========================================="
echo "Before:  $BEFORE_COUNT wheels"
echo "After:   $AFTER_COUNT wheels"
echo "Removed: $REMOVED_COUNT wheels"
echo ""

if [ $REMOVED_COUNT -eq 0 ]; then
    echo "✓ No PyPI duplicates found - all wheels are correct!"
else
    echo "✓ Successfully removed $REMOVED_COUNT duplicate/PyPI wheels"
fi

echo "========================================="
echo ""

# Final verification - show remaining custom wheels
echo "Final verification - Custom ROCm wheels present:"
for pkg in "${PACKAGES_TO_CHECK[@]}"; do
    wheel=$(ls "$ALL_WHEELS_DIR"/${pkg}-*.whl 2>/dev/null | head -1)
    if [ -n "$wheel" ]; then
        echo "  ✓ $(basename "$wheel")"
    else
        echo "  ✗ $pkg wheel MISSING!"
    fi
done

vllm_wheel=$(ls "$ALL_WHEELS_DIR"/vllm-*.whl 2>/dev/null | head -1)
if [ -n "$vllm_wheel" ]; then
    echo "  ✓ $(basename "$vllm_wheel")"
else
    echo "  ✗ vllm wheel MISSING!"
fi

echo ""
echo "========================================="

# Check if any custom wheels were missing
if [ ${#MISSING_CUSTOM_WHEELS[@]} -gt 0 ]; then
    echo ""
    echo "========================================="
    echo "FATAL ERROR: Missing Custom Wheels"
    echo "========================================="
    echo ""
    echo "The following custom wheels were NOT FOUND in $BASE_WHEELS_DIR:"
    for pkg in "${MISSING_CUSTOM_WHEELS[@]}"; do
        echo "  ✗ $pkg"
    done
    echo ""
    echo "This means PyPI duplicates may NOT have been removed properly!"
    echo ""
    echo "Possible causes:"
    echo "  1. artifacts/rocm-base-wheels directory doesn't exist"
    echo "  2. Base wheels weren't uploaded in Job 1"
    echo "  3. Wrong directory path specified"
    echo ""
    echo "CANNOT PROCEED - Fix the build process first!"
    echo "========================================="
    exit 1
fi

exit 0
