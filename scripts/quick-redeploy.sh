#!/bin/bash
set -e

echo "🔄 Quick Redeploy - Rebuild and Push Docker Image"
echo "=================================================="
echo ""

AWS_PROFILE="${AWS_PROFILE:-personal}"
AWS_REGION="${AWS_REGION:-us-east-2}"

export AWS_PROFILE=$AWS_PROFILE

# Get account ID
ACCOUNT_ID=$(aws sts get-caller-identity --profile $AWS_PROFILE --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/openclaw-personal"

echo "📦 Building Docker image..."
docker buildx build --platform linux/arm64 -t openclaw-personal:latest -f agent-container/Dockerfile .

echo ""
echo "🔐 Authenticating with ECR..."
aws ecr get-login-password --profile $AWS_PROFILE --region $AWS_REGION | \
    docker login --username AWS --password-stdin $ECR_URI

echo ""
echo "🏷️  Tagging image..."
docker tag openclaw-personal:latest $ECR_URI:latest

echo ""
echo "🚢 Pushing to ECR..."
docker push $ECR_URI:latest

echo ""
echo "✅ Redeploy complete!"
echo ""
echo "📝 Note: AgentCore will automatically use the new image on next invocation"
echo ""
echo "🧪 Test with:"
echo "  python3 scripts/invoke_agentcore.py"
echo ""
echo "💡 Run this script from the repo root: bash scripts/quick-redeploy.sh"
echo ""
