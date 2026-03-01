#!/bin/bash
set -e

# OpenClaw Personal Deployment Script
# This script builds, pushes, and deploys OpenClaw to AWS using CloudFormation

echo "🚀 OpenClaw Personal Deployment"
echo "================================"
echo ""

# Configuration
STACK_NAME="openclaw-personal"
AWS_REGION="${AWS_REGION:-us-east-2}"
AWS_PROFILE="${AWS_PROFILE:-personal}"
ADMIN_EMAIL="${ADMIN_EMAIL:-}"
MONTHLY_BUDGET="${MONTHLY_BUDGET:-15}"
DEFAULT_MODEL="${DEFAULT_MODEL:-us.amazon.nova-lite-v1:0}"

# Load .env file if it exists
if [ -f "agent-container/.env" ]; then
    echo "📄 Loading configuration from agent-container/.env"
    export $(grep -v '^#' agent-container/.env | xargs)
    echo "   ✅ Environment variables loaded"
    echo ""
fi

# Use Discord token from .env if available
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN:-}"

# Set AWS profile for all commands
export AWS_PROFILE=$AWS_PROFILE

# Prompt for required parameters if not set
if [ -z "$ADMIN_EMAIL" ]; then
    read -p "Enter your email for budget alerts: " ADMIN_EMAIL
fi

echo ""
echo "📋 Deployment Configuration:"
echo "  Stack Name: $STACK_NAME"
echo "  Region: $AWS_REGION"
echo "  AWS Profile: $AWS_PROFILE"
echo "  Admin Email: $ADMIN_EMAIL"
echo "  Monthly Budget: \$$MONTHLY_BUDGET"
echo "  Default Model: $DEFAULT_MODEL"
if [ -n "$DISCORD_BOT_TOKEN" ]; then
    echo "  Discord Bot: ✅ Configured"
else
    echo "  Discord Bot: ⚠️  Not configured (optional)"
fi
echo ""

# Verify AWS credentials
echo "🔐 Verifying AWS credentials..."
if ! aws sts get-caller-identity --profile $AWS_PROFILE --region $AWS_REGION > /dev/null 2>&1; then
    echo "❌ AWS credentials are not configured or expired for profile: $AWS_PROFILE"
    echo "   Run: aws sso login --profile $AWS_PROFILE"
    echo "   Or: aws configure --profile $AWS_PROFILE"
    exit 1
fi
ACCOUNT_ID=$(aws sts get-caller-identity --profile $AWS_PROFILE --query Account --output text)
echo "✅ Authenticated as account: $ACCOUNT_ID (profile: $AWS_PROFILE)"
echo ""

# Step 1: Build Docker image
echo "🐳 Step 1: Building Docker image for ARM64..."
docker buildx build --platform linux/arm64 -t openclaw-personal:latest -f agent-container/Dockerfile .
echo "✅ Docker image built successfully"
echo ""

# Step 2: Create ECR repository if it doesn't exist
echo "📦 Step 2: Setting up ECR repository..."
if ! aws ecr describe-repositories --repository-names openclaw-personal --profile $AWS_PROFILE --region $AWS_REGION > /dev/null 2>&1; then
    echo "Creating ECR repository..."
    aws ecr create-repository \
        --repository-name openclaw-personal \
        --profile $AWS_PROFILE \
        --region $AWS_REGION \
        --image-scanning-configuration scanOnPush=true
    echo "✅ ECR repository created"
else
    echo "✅ ECR repository already exists"
fi

ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/openclaw-personal"
echo "   Repository URI: $ECR_URI"
echo ""

# Step 3: Push Docker image to ECR
echo "🚢 Step 3: Pushing Docker image to ECR..."
echo "Authenticating with ECR..."
aws ecr get-login-password --profile $AWS_PROFILE --region $AWS_REGION | \
    docker login --username AWS --password-stdin $ECR_URI

echo "Tagging image..."
docker tag openclaw-personal:latest $ECR_URI:latest

echo "Pushing image..."
docker push $ECR_URI:latest
echo "✅ Docker image pushed successfully"
echo ""

# Step 4: Validate CloudFormation template
echo "✅ Step 4: Validating CloudFormation template..."
aws cloudformation validate-template \
    --template-body file://openclaw-simplified.yaml \
    --profile $AWS_PROFILE \
    --region $AWS_REGION > /dev/null
echo "✅ Template is valid"
echo ""

# Step 5: Deploy CloudFormation stack
echo "☁️  Step 5: Deploying CloudFormation stack..."
DEPLOY_PARAMS="AdminEmail=$ADMIN_EMAIL MonthlyBudgetLimit=$MONTHLY_BUDGET DefaultModelId=$DEFAULT_MODEL"

if [ -n "$DISCORD_BOT_TOKEN" ]; then
    echo "   Including Discord bot configuration..."
    DEPLOY_PARAMS="$DEPLOY_PARAMS DiscordBotToken=$DISCORD_BOT_TOKEN EnableDiscordBot=true"
else
    echo "   Skipping Discord bot (no token provided)..."
    DEPLOY_PARAMS="$DEPLOY_PARAMS EnableDiscordBot=false"
fi

aws cloudformation deploy \
    --template-file openclaw-simplified.yaml \
    --stack-name $STACK_NAME \
    --parameter-overrides $DEPLOY_PARAMS \
    --capabilities CAPABILITY_NAMED_IAM \
    --profile $AWS_PROFILE \
    --region $AWS_REGION

echo "✅ Stack deployed successfully"
echo ""

# Step 6: Get stack outputs
echo "📊 Step 6: Retrieving stack outputs..."
RUNTIME_ID=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --profile $AWS_PROFILE \
    --region $AWS_REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`AgentCoreRuntimeId`].OutputValue' \
    --output text)

S3_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --profile $AWS_PROFILE \
    --region $AWS_REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`SessionBackupBucketName`].OutputValue' \
    --output text)

DISCORD_INSTANCE=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --profile $AWS_PROFILE \
    --region $AWS_REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`DiscordBotInstanceId`].OutputValue' \
    --output text 2>/dev/null || echo "Not deployed")

echo ""
echo "🎉 Deployment Complete!"
echo "======================="
echo ""
echo "📋 Stack Information:"
echo "  Runtime ID: $RUNTIME_ID"
echo "  S3 Bucket: $S3_BUCKET"
echo "  ECR Repository: $ECR_URI"
if [ "$DISCORD_INSTANCE" != "Not deployed" ]; then
    echo "  Discord Bot Instance: $DISCORD_INSTANCE"
fi
echo ""
echo "🧪 Test the deployment:"
echo "  aws bedrock-agentcore invoke-runtime \\"
echo "    --runtime-id $RUNTIME_ID \\"
echo "    --body '{\"path\": \"/ping\"}' \\"
echo "    --profile $AWS_PROFILE \\"
echo "    --region $AWS_REGION"
echo ""
echo "📧 Check your email ($ADMIN_EMAIL) to confirm SNS subscription for budget alerts"
echo ""
echo "📖 Next steps:"
echo "  1. Configure messaging platforms (WhatsApp, Discord, Telegram)"
echo "  2. Monitor costs in AWS Cost Explorer"
echo "  3. View logs: aws logs tail /aws/bedrock-agentcore/openclaw-personal --follow --profile $AWS_PROFILE --region $AWS_REGION"
echo ""
