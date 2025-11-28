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
# Process each package type
#############################################################################

PACKAGES_TO_CHECK=("torch" "triton" "torchvision" "amdsmi")
REMOVED_COUNT=0

for pkg in "${PACKAGES_TO_CHECK[@]}"; do
    echo "========================================="
    echo "Processing: $pkg"
    echo "========================================="

    # Find custom wheel in base-wheels directory
    CUSTOM_WHEEL=$(ls "$BASE_WHEELS_DIR"/${pkg}-*.whl 2>/dev/null | head -1)

    if [ -z "$CUSTOM_WHEEL" ]; then
        echo "⚠️  WARNING: No custom $pkg wheel found in $BASE_WHEELS_DIR"
        echo "   Skipping $pkg cleanup..."
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
# Handle vLLM wheels (keep only one - the one we built)
#############################################################################

echo "========================================="
echo "Processing: vllm (removing duplicates)"
echo "========================================="

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
        echo "   Keeping the FIRST one, removing others..."
        echo ""

        # Keep first, remove rest
        FIRST_VLLM="${VLLM_WHEELS[0]}"
        FIRST_NAME=$(basename "$FIRST_VLLM")
        echo "  ✓ KEEP: $FIRST_NAME"

        for ((i=1; i<$VLLM_COUNT; i++)); do
            wheel="${VLLM_WHEELS[$i]}"
            wheel_name=$(basename "$wheel")
            echo "  ✗ REMOVE: $wheel_name (duplicate)"
            rm -f "$wheel"
            REMOVED_COUNT=$((REMOVED_COUNT + 1))
        done
        echo ""
    else
        VLLM_NAME=$(basename "${VLLM_WHEELS[0]}")
        echo "✓ Single vllm wheel found: $VLLM_NAME"
        echo "  No duplicates to remove."
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

exit 0
