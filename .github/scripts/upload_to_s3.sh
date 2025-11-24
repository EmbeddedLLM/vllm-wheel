#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
#
# Script to upload wheels and PyPI index to AWS S3
#
# Usage:
#   ./upload_to_s3.sh <wheels-dir> <index-dir> <s3-bucket> <aws-region>
#
# Requirements:
#   - AWS CLI installed and configured
#   - AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables set
#   - S3 bucket must exist and be configured for public read access

set -euo pipefail  # Exit on error, undefined variables, and pipe failures

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check arguments
if [ $# -ne 4 ]; then
    log_error "Usage: $0 <wheels-dir> <index-dir> <s3-bucket> <aws-region>"
    exit 1
fi

WHEELS_DIR="$1"
INDEX_DIR="$2"
S3_BUCKET="$3"
AWS_REGION="$4"

# Validate inputs
if [ ! -d "$WHEELS_DIR" ]; then
    log_error "Wheels directory not found: $WHEELS_DIR"
    exit 1
fi

if [ ! -d "$INDEX_DIR" ]; then
    log_error "Index directory not found: $INDEX_DIR"
    exit 1
fi

log_info "Starting S3 upload process..."
echo "  Wheels directory: $WHEELS_DIR"
echo "  Index directory: $INDEX_DIR"
echo "  S3 bucket: $S3_BUCKET"
echo "  AWS region: $AWS_REGION"
echo ""

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    log_error "AWS CLI is not installed. Please install it first:"
    echo "  curl \"https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip\" -o \"awscliv2.zip\""
    echo "  unzip awscliv2.zip"
    echo "  sudo ./aws/install"
    exit 1
fi

log_success "AWS CLI found: $(aws --version)"

# Check AWS credentials
if [ -z "${AWS_ACCESS_KEY_ID:-}" ] || [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    log_error "AWS credentials not found in environment variables"
    echo "  Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY"
    exit 1
fi

log_success "AWS credentials found in environment"

# Verify S3 bucket exists and is accessible
log_info "Verifying S3 bucket access..."
if aws s3 ls "s3://$S3_BUCKET" --region "$AWS_REGION" &> /dev/null; then
    log_success "S3 bucket is accessible: $S3_BUCKET"
else
    log_error "Cannot access S3 bucket: $S3_BUCKET"
    echo "  Please check:"
    echo "    1. Bucket exists"
    echo "    2. AWS credentials have permission to access it"
    echo "    3. Bucket is in the correct region: $AWS_REGION"
    exit 1
fi

# Count files to upload
WHEEL_COUNT=$(find "$WHEELS_DIR" -name "*.whl" -type f | wc -l)
INDEX_FILE_COUNT=$(find "$INDEX_DIR" -type f | wc -l)

log_info "Found $WHEEL_COUNT wheel(s) and $INDEX_FILE_COUNT index file(s) to upload"
echo ""

# Calculate total size
TOTAL_SIZE=$(du -sb "$WHEELS_DIR" "$INDEX_DIR" | awk '{sum += $1} END {print sum}')
TOTAL_SIZE_GB=$(echo "scale=2; $TOTAL_SIZE / 1024 / 1024 / 1024" | bc)

log_info "Total upload size: ${TOTAL_SIZE_GB} GB"
log_warning "This upload may take several minutes depending on your connection speed"
echo ""

# Upload wheels to S3
log_info "Uploading wheels to S3..."
echo "  Destination: s3://$S3_BUCKET/packages/"
echo "  Content-Type: application/octet-stream"
echo "  Cache-Control: public, max-age=31536000 (1 year)"
echo ""

# Use AWS CLI sync for efficient upload with progress
# --size-only: Only upload if size differs (faster than checking modification time)
# --acl public-read: Make files publicly readable
# --cache-control: Set cache headers (wheels are immutable)

aws s3 sync "$WHEELS_DIR/" "s3://$S3_BUCKET/packages/" \
    --region "$AWS_REGION" \
    --content-type "application/octet-stream" \
    --cache-control "public, max-age=31536000" \
    --size-only \
    --exclude "*" \
    --include "*.whl" \
    --no-progress

if [ $? -eq 0 ]; then
    log_success "Wheels uploaded successfully"
else
    log_error "Wheel upload failed"
    exit 1
fi

echo ""

# Upload index files to S3
log_info "Uploading PyPI index to S3..."
echo "  Destination: s3://$S3_BUCKET/"
echo "  Content-Type: text/html"
echo "  Cache-Control: no-cache (index should always be fresh)"
echo ""

# Upload index with different cache settings
# Index files should not be cached aggressively as they may update
aws s3 sync "$INDEX_DIR/" "s3://$S3_BUCKET/" \
    --region "$AWS_REGION" \
    --content-type "text/html" \
    --cache-control "no-cache, no-store, must-revalidate" \
    --size-only \
    --delete

if [ $? -eq 0 ]; then
    log_success "Index uploaded successfully"
else
    log_error "Index upload failed"
    exit 1
fi

echo ""

# Verify uploads
log_info "Verifying uploads..."

# Check a sample wheel
SAMPLE_WHEEL=$(find "$WHEELS_DIR" -name "*.whl" -type f -print -quit)
if [ -n "$SAMPLE_WHEEL" ]; then
    WHEEL_NAME=$(basename "$SAMPLE_WHEEL")
    if aws s3 ls "s3://$S3_BUCKET/packages/$WHEEL_NAME" &> /dev/null; then
        log_success "Sample wheel verified: $WHEEL_NAME"
    else
        log_warning "Could not verify sample wheel: $WHEEL_NAME"
    fi
fi

# Check index
if aws s3 ls "s3://$S3_BUCKET/simple/index.html" &> /dev/null; then
    log_success "Index verified: simple/index.html"
else
    log_warning "Could not verify index: simple/index.html"
fi

echo ""

# Calculate S3 URL
S3_URL="https://$S3_BUCKET.s3.$AWS_REGION.amazonaws.com"
INSTALL_URL="$S3_URL/simple/"

# Final summary
echo "============================================================================"
log_success "Upload Complete!"
echo "============================================================================"
echo ""
echo "📦 Uploaded:"
echo "  - $WHEEL_COUNT wheel(s) to s3://$S3_BUCKET/packages/"
echo "  - $INDEX_FILE_COUNT index file(s) to s3://$S3_BUCKET/"
echo ""
echo "🌐 URLs:"
echo "  - Repository Home: $S3_URL/"
echo "  - PyPI Index: $INSTALL_URL"
echo ""
echo "📥 Installation Command:"
echo "  pip install vllm --index-url $INSTALL_URL"
echo ""
echo "💡 Test installation with:"
echo "  docker run -it python:3.12-slim bash -c 'pip install vllm --index-url $INSTALL_URL && python -c \"import vllm; print(vllm.__version__)\""'"
echo ""
echo "============================================================================"
