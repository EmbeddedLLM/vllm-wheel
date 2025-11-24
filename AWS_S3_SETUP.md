# AWS S3 Setup Guide for vLLM ROCm Wheel Repository

This guide will walk you through setting up AWS S3 storage for hosting your vLLM ROCm wheels. No prior AWS experience required!

## Overview

We'll be setting up:
- **AWS Account** (if you don't have one)
- **S3 Bucket** for storing wheels and PyPI index
- **IAM User** with appropriate permissions for GitHub Actions
- **GitHub Secrets** for secure credential storage

**Estimated Cost**: ~$1-5/month for storing and serving ~10GB of wheels

---

## Step 1: Create AWS Account

If you already have an AWS account, skip to Step 2.

1. Go to [https://aws.amazon.com](https://aws.amazon.com)
2. Click **"Create an AWS Account"**
3. Fill in:
   - Email address
   - Password
   - AWS account name (e.g., "vllm-wheels")
4. Click **"Continue"**
5. Choose **"Personal"** account type
6. Fill in contact information
7. Enter payment information (required, but you won't be charged much)
   - AWS has a free tier for new accounts
   - Estimated cost: $1-5/month for this use case
8. Verify your phone number
9. Select **"Basic Support - Free"** plan
10. Complete sign-up

✅ **Account created!** You should receive a confirmation email.

---

## Step 2: Sign in to AWS Console

1. Go to [https://console.aws.amazon.com](https://console.aws.amazon.com)
2. Sign in with your root account credentials
3. You'll see the AWS Management Console

---

## Step 3: Create S3 Bucket

### 3.1 Navigate to S3

1. In the AWS Console, search for **"S3"** in the top search bar
2. Click on **"S3"** under Services
3. You'll see the S3 dashboard

### 3.2 Create Bucket

1. Click **"Create bucket"** (orange button)
2. Fill in bucket settings:

   **Bucket name**:
   - Enter: `vllm-rocm-wheels` (or similar)
   - Must be globally unique across all of AWS
   - If taken, try: `vllm-rocm-wheels-<your-name>` or `vllm-rocm-wheels-<random-number>`
   - **Write down your bucket name** - you'll need it later!

   **AWS Region**:
   - Select region closest to your users
   - Recommended: `us-east-1` (US East - N. Virginia) - most common, good performance
   - Or: `us-west-2` (US West - Oregon) if your users are on west coast
   - **Write down your region** - you'll need it later!

   **Object Ownership**:
   - Keep default: **"ACLs disabled"**

   **Block Public Access settings**:
   - ⚠️ **IMPORTANT**: **Uncheck** "Block all public access"
   - Check the box that says "I acknowledge..."
   - This allows anyone to download wheels (which is what we want)

   **Bucket Versioning**:
   - Keep disabled (not needed for wheels)

   **Tags**:
   - Optional, can leave empty

   **Default encryption**:
   - Keep default: **"Server-side encryption with Amazon S3 managed keys (SSE-S3)"**

   **Advanced settings**:
   - Keep defaults

3. Click **"Create bucket"** at the bottom

✅ **Bucket created!** You should see it in your buckets list.

### 3.3 Configure Bucket Policy for Public Read

Now we need to make the wheels publicly accessible:

1. Click on your bucket name
2. Click the **"Permissions"** tab
3. Scroll down to **"Bucket policy"**
4. Click **"Edit"**
5. Paste this policy (replace `YOUR-BUCKET-NAME` with your actual bucket name):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
    }
  ]
}
```

6. Click **"Save changes"**

✅ **Bucket is now publicly readable!**

---

## Step 4: Create IAM User for GitHub Actions

We need to create a user account that GitHub Actions can use to upload wheels.

### 4.1 Navigate to IAM

1. In the AWS Console, search for **"IAM"** in the top search bar
2. Click on **"IAM"** under Services
3. You'll see the IAM dashboard

### 4.2 Create Policy

First, we create a permission policy:

1. In the left sidebar, click **"Policies"**
2. Click **"Create policy"** (blue button)
3. Click the **"JSON"** tab
4. Paste this policy (replace `YOUR-BUCKET-NAME` with your actual bucket name):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "VLLMWheelUploaderPolicy",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:PutObjectAcl",
        "s3:GetObject",
        "s3:ListBucket",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::YOUR-BUCKET-NAME",
        "arn:aws:s3:::YOUR-BUCKET-NAME/*"
      ]
    }
  ]
}
```

5. Click **"Next: Tags"** (can skip tags)
6. Click **"Next: Review"**
7. Name the policy: `vllm-wheel-uploader-policy`
8. Description: `Policy for uploading vLLM wheels to S3`
9. Click **"Create policy"**

✅ **Policy created!**

### 4.3 Create User

Now create the user and attach the policy:

1. In the left sidebar, click **"Users"**
2. Click **"Add users"** (or "Create user" button)
3. Fill in user details:

   **User name**: `github-actions-vllm-uploader`

   **Access type**: Check **"Access key - Programmatic access"**
   - ⚠️ Do NOT check "AWS Management Console access"

4. Click **"Next: Permissions"**

5. Select **"Attach existing policies directly"**

6. In the search box, type: `vllm-wheel-uploader-policy`

7. Check the box next to your policy

8. Click **"Next: Tags"** (can skip tags)

9. Click **"Next: Review"**

10. Review and click **"Create user"**

### 4.4 Save Access Keys

**⚠️ CRITICAL: This is shown only once!**

You'll see a success page with:
- **Access key ID**: Looks like `AKIAIOSFODNN7EXAMPLE`
- **Secret access key**: Looks like `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`

**IMMEDIATELY**:
1. Click **"Download .csv"** to save the credentials
2. Or copy both keys to a secure location (password manager, secure note, etc.)

**⚠️ You CANNOT retrieve the secret key again!** If you lose it, you'll need to create new keys.

✅ **User created!** Keep these credentials safe.

---

## Step 5: Configure GitHub Repository Secrets

Now we'll add the AWS credentials to your GitHub repository so the workflow can use them.

### 5.1 Navigate to Repository Settings

1. Go to your GitHub repository: `https://github.com/YOUR-USERNAME/vllm-wheel`
2. Click **"Settings"** tab (top right)
3. In the left sidebar, expand **"Secrets and variables"**
4. Click **"Actions"**

### 5.2 Add Secrets

Click **"New repository secret"** for each of these:

#### Secret 1: AWS_ACCESS_KEY_ID
- **Name**: `AWS_ACCESS_KEY_ID`
- **Value**: Paste your Access key ID from Step 4.4
- Click **"Add secret"**

#### Secret 2: AWS_SECRET_ACCESS_KEY
- **Name**: `AWS_SECRET_ACCESS_KEY`
- **Value**: Paste your Secret access key from Step 4.4
- Click **"Add secret"**

#### Secret 3: AWS_S3_BUCKET
- **Name**: `AWS_S3_BUCKET`
- **Value**: Your bucket name (e.g., `vllm-rocm-wheels`)
- Click **"Add secret"**

#### Secret 4: AWS_REGION
- **Name**: `AWS_REGION`
- **Value**: Your AWS region (e.g., `us-east-1`)
- Click **"Add secret"**

✅ **All secrets configured!**

You should now see 4 secrets in your repository:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_S3_BUCKET`
- `AWS_REGION`

---

## Step 6: Test the Setup

Now let's verify everything works:

### 6.1 Run the Workflow

1. Go to your repository's **"Actions"** tab
2. Click on **"Build ROCm Wheels and Publish to PyPI"** workflow
3. Click **"Run workflow"** (right side)
4. Fill in parameters (or use defaults):
   - ROCm GPU architectures: `gfx942`
   - Python version: `3.12`
   - ROCm version: `7.1`
5. Click **"Run workflow"** (green button)

The workflow will:
- Build base wheels (torch, triton, etc.)
- Collect dependencies
- Build vLLM wheel
- Upload everything to S3

**This will take 30-60 minutes** on first run (builds are slow).

### 6.2 Monitor Progress

1. Click on the running workflow to see progress
2. Watch the logs for any errors
3. Job 4 "Create PyPI Repository and Publish" should show S3 upload

### 6.3 Verify S3 Upload

After workflow completes:

1. Go to AWS S3 Console
2. Click on your bucket
3. You should see:
   - `packages/` folder with wheel files
   - `simple/` folder with index HTML files
   - `index.html` landing page

### 6.4 Test Installation

Your S3 URL will be:
```
https://YOUR-BUCKET-NAME.s3.YOUR-REGION.amazonaws.com
```

Test installing vLLM:
```bash
# In a ROCm 7.1 + Python 3.12 environment
pip install vllm --index-url https://YOUR-BUCKET-NAME.s3.YOUR-REGION.amazonaws.com/simple/
```

If this works, **you're done!** 🎉

---

## Troubleshooting

### Error: "Access Denied" when uploading to S3

**Possible causes:**
1. IAM policy doesn't have correct permissions
2. Bucket name in GitHub secret doesn't match actual bucket
3. AWS credentials are incorrect

**Solutions:**
- Double-check bucket name in `AWS_S3_BUCKET` secret
- Verify IAM policy has `s3:PutObject` permission
- Regenerate IAM user access keys if needed

### Error: "Bucket not found"

**Possible causes:**
1. Wrong bucket name in GitHub secret
2. Wrong region in GitHub secret

**Solutions:**
- Verify `AWS_S3_BUCKET` secret matches actual bucket name exactly
- Verify `AWS_REGION` secret matches bucket's region

### Error: "Could not fetch versions from PyPI"

**Possible causes:**
1. Network issue in GitHub Actions
2. PyPI rate limiting

**Solutions:**
- Re-run the workflow (usually resolves temporary issues)
- Check Job 2 logs for specific errors

### Wheels installed but vLLM doesn't work

**Possible causes:**
1. Transitive dependencies missing
2. Version incompatibilities

**Solutions:**
- Check that all critical packages are in the index
- Verify wheel versions are normalized (no `+git...` suffixes)
- Check installation logs for warnings

### Cost concerns

**Typical costs:**
- **Storage**: ~$0.023/GB/month for Standard S3
  - 10GB of wheels = ~$0.23/month
- **Transfer out**: ~$0.09/GB
  - 100 downloads/month of 10GB = ~$9/month
  - First 100GB/month is free with AWS Free Tier (first 12 months)

**To reduce costs:**
- Use S3 Intelligent-Tiering for storage
- Set up CloudFront CDN (reduces transfer costs)
- Delete old wheel versions

---

## Next Steps

1. ✅ Set up automated builds (e.g., weekly or on new vLLM releases)
2. ✅ Add monitoring/alerting for failed builds
3. ✅ Consider adding CloudFront CDN for faster downloads
4. ✅ Set up S3 lifecycle policies to archive old wheels

---

## Security Notes

- ✅ IAM user has minimal permissions (only for the specific bucket)
- ✅ Access keys are stored securely in GitHub Secrets
- ✅ Wheels are public (expected for a PyPI repository)
- ✅ Landing page and index are public (expected)

**Do NOT:**
- ❌ Share your AWS access keys publicly
- ❌ Commit `.aws/credentials` or access keys to git
- ❌ Use root AWS account credentials for GitHub Actions

---

## Support

If you encounter issues:

1. Check the troubleshooting section above
2. Review GitHub Actions workflow logs
3. Check AWS S3 bucket permissions
4. Verify IAM policy and user configuration

---

## Summary Checklist

- [ ] AWS account created
- [ ] S3 bucket created with public read access
- [ ] Bucket policy configured
- [ ] IAM policy created
- [ ] IAM user created with policy attached
- [ ] Access keys downloaded and saved securely
- [ ] All 4 GitHub secrets added:
  - [ ] `AWS_ACCESS_KEY_ID`
  - [ ] `AWS_SECRET_ACCESS_KEY`
  - [ ] `AWS_S3_BUCKET`
  - [ ] `AWS_REGION`
- [ ] Workflow tested and completed successfully
- [ ] Wheels accessible via S3 URL
- [ ] Installation tested and working

If all boxes are checked, you're ready to use your S3-hosted PyPI repository! 🚀
