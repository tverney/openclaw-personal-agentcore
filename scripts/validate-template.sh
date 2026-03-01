#!/bin/bash
# Validate CloudFormation template

set -e

echo "🔍 Validating CloudFormation template..."
echo ""

# Validate template syntax
aws cloudformation validate-template \
  --template-body file://openclaw-simplified.yaml \
  --profile personal \
  --region us-east-2

if [ $? -eq 0 ]; then
  echo ""
  echo "✅ Template is valid!"
  echo ""
  echo "Template includes:"
  echo "  - AgentCore Runtime (serverless)"
  echo "  - ECR Repository"
  echo "  - S3 Session Bucket"
  echo "  - Budget Alerts"
  echo "  - Discord Bot EC2 (optional)"
  echo "  - VPC & Networking (if Discord bot enabled)"
  echo "  - IAM Roles & Policies"
  echo ""
  echo "Parameters:"
  echo "  - AdminEmail (required)"
  echo "  - MonthlyBudgetLimit (default: 10)"
  echo "  - DefaultModelId (default: us.amazon.nova-lite-v1:0)"
  echo "  - DiscordBotToken (optional)"
  echo "  - EnableDiscordBot (default: true)"
  echo "  - DiscordBotKeyPair (optional)"
  echo ""
  echo "Ready to deploy!"
else
  echo ""
  echo "❌ Template validation failed"
  exit 1
fi
