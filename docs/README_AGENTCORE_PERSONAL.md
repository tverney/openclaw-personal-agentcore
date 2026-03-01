# OpenClaw Personal - AWS Bedrock AgentCore Deployment

> Serverless OpenClaw deployment using AWS Bedrock AgentCore Runtime with Discord integration

[![AWS](https://img.shields.io/badge/AWS-AgentCore-orange.svg)](https://aws.amazon.com/bedrock/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

This is a simplified, personal deployment of OpenClaw using AWS Bedrock AgentCore Runtime. Unlike the EC2-based deployment, this runs serverless and only costs money when you use it.

### Key Features

- 🚀 **Serverless**: Pay only when your agent is invoked
- 💰 **Cost-Optimized**: Uses Nova 2 Lite (90% cheaper than Claude)
- 🤖 **Discord Ready**: Pre-configured Discord bot integration
- 💾 **Session Persistence**: Automatic S3 backup every 5 minutes
- 📊 **Budget Protected**: CloudWatch alarms and AWS Budgets
- 🔒 **Secure**: IAM roles, no API keys to manage

## Quick Start

### Prerequisites

1. AWS CLI configured with credentials
2. Docker with buildx support (for ARM64)
3. Python 3.10+
4. Discord bot token (optional)

### 1. Configure Environment

Edit `agent-container/.env`:

```bash
DISCORD_BOT_TOKEN=your-discord-bot-token-here
AWS_REGION=us-east-2
BEDROCK_MODEL_ID=us.amazon.nova-2-lite-v1:0
```

### 2. Deploy

```bash
cd openclaw-personal
./deploy.sh
```

The script will:
- Build Docker image for ARM64
- Push to Amazon ECR
- Deploy CloudFormation stack
- Configure AgentCore Runtime
- Set up S3, IAM, budgets, and alarms

**Deployment time**: ~8-10 minutes

### 3. Test

```bash
# Test the runtime
python3 test_discord.py

# View logs
aws logs tail /aws/bedrock-agentcore/runtimes/openclawpersonal_runtime-w6iQAuAZYI-DEFAULT \
  --follow \
  --profile personal \
  --region us-east-2
```

## Architecture

```
┌─────────────────┐
│  Discord Bot    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  AWS Bedrock AgentCore Runtime      │
│  (Serverless, ARM64 microVM)        │
│                                     │
│  ┌───────────────────────────────┐ │
│  │  OpenClaw Container           │ │
│  │  - HTTP Server (port 8080)    │ │
│  │  - Channel Routing            │ │
│  │  - Session Management         │ │
│  └───────────────────────────────┘ │
└─────────────────┬───────────────────┘
                  │
         ┌────────┴────────┐
         ▼                 ▼
┌─────────────────┐  ┌──────────────┐
│ Amazon Bedrock  │  │  S3 Bucket   │
│ (Nova 2 Lite)   │  │  (Sessions)  │
└─────────────────┘  └──────────────┘
```

## Configuration

### Channel Routing

Configure different models for different Discord channels in `agent-container/server.py`:

```python
CHANNEL_MODEL_ROUTING = {
    "discord_general": "us.amazon.nova-lite-v1:0",      # Cheap, fast
    "discord_technical": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",  # Powerful
}
```

### Available Models

- `us.amazon.nova-2-lite-v1:0` - Most cost-effective (default)
- `us.amazon.nova-pro-v1:0` - Balanced performance
- `us.anthropic.claude-sonnet-4-5-20250929-v1:0` - Most capable
- `us.anthropic.claude-haiku-4-5-20251001-v1:0` - Fast and efficient

### Session Persistence

Sessions are automatically:
- Backed up to S3 every 5 minutes
- Restored on container restart
- Versioned for 30 days

## Cost Breakdown

### Infrastructure (Monthly)
- **AgentCore Runtime**: Pay-per-use (~$0.01-0.05 per invocation)
- **S3 Storage**: ~$0.50/month
- **ECR**: ~$0.10/month
- **CloudWatch**: ~$0.50/month

### Per-Message (Nova 2 Lite)
- **Input**: $0.30 per 1M tokens
- **Output**: $2.50 per 1M tokens
- **Typical message**: ~$0.001-0.01

**Estimated Total**: $5-15/month for typical personal use

## Deployment Scripts

### Full Deployment
```bash
./deploy.sh
```
Builds, pushes, and deploys everything from scratch.

### Quick Redeploy
```bash
./quick-redeploy.sh
```
Rebuilds and pushes Docker image only (after code changes).

### Test Scripts
```bash
# Test AgentCore invocation
python3 invoke_agentcore.py

# Test Discord integration
python3 test_discord.py
```

## Discord Setup

### 1. Create Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create new application
3. Go to "Bot" tab → Create bot
4. Copy bot token to `agent-container/.env`
5. Enable "Message Content Intent"

### 2. Invite Bot to Server

1. Go to "OAuth2" → "URL Generator"
2. Select scopes: `bot`, `applications.commands`
3. Select permissions: Send Messages, Read Messages
4. Copy URL and open in browser
5. Select your server

### 3. Test

Send a message in Discord mentioning your bot!

## Updating

### Update Code

```bash
# Edit files in agent-container/
nano agent-container/server.py

# Rebuild and push
./quick-redeploy.sh
```

### Update Configuration

```bash
# Edit environment variables
nano agent-container/.env

# Update stack
source agent-container/.env
aws cloudformation update-stack \
  --stack-name openclaw-personal \
  --use-previous-template \
  --parameters \
    ParameterKey=DiscordBotToken,ParameterValue=$DISCORD_BOT_TOKEN \
  --capabilities CAPABILITY_NAMED_IAM \
  --profile personal \
  --region us-east-2
```

## Monitoring

### View Logs

```bash
aws logs tail /aws/bedrock-agentcore/runtimes/openclawpersonal_runtime-w6iQAuAZYI-DEFAULT \
  --follow \
  --profile personal \
  --region us-east-2
```

### Check Costs

```bash
aws ce get-cost-and-usage \
  --time-period Start=2026-02-01,End=2026-02-28 \
  --granularity DAILY \
  --metrics BlendedCost \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["Amazon Bedrock"]}}' \
  --profile personal
```

### CloudWatch Metrics

- Go to AWS Console → CloudWatch
- Navigate to Metrics → BedrockAgentCore
- View invocation count, duration, errors

## Troubleshooting

### "Unauthorized" errors

**Cause**: Bedrock permissions issue

**Fix**: Check IAM role has `bedrock:InvokeModel` permission
```bash
aws iam get-role-policy \
  --role-name openclaw-personal-agentcore-role \
  --policy-name BedrockAccess \
  --profile personal
```

### Discord not responding

**Cause**: Bot token not configured or invalid

**Fix**: 
1. Verify token in `agent-container/.env`
2. Redeploy: `./quick-redeploy.sh`
3. Check logs for errors

### High costs

**Fix**:
1. Switch to cheaper model (Nova Lite)
2. Lower monthly budget limit
3. Review CloudWatch metrics
4. Check for unexpected usage

### Container not starting

**Fix**:
1. Check CloudWatch logs
2. Verify Docker image in ECR
3. Check IAM role permissions
4. Rebuild: `./quick-redeploy.sh`

## File Structure

```
openclaw-personal/
├── agent-container/
│   ├── .env                    # Environment variables (Discord token, etc.)
│   ├── Dockerfile              # Container definition
│   ├── server.py               # HTTP server wrapper
│   ├── openclaw.json           # OpenClaw configuration
│   └── requirements.txt        # Python dependencies
├── deploy.sh                   # Full deployment script
├── quick-redeploy.sh           # Quick Docker rebuild
├── openclaw-simplified.yaml    # CloudFormation template
├── invoke_agentcore.py         # Test script for runtime
├── test_discord.py             # Test script for Discord
└── README_AGENTCORE_PERSONAL.md  # This file
```

## Cleanup

To remove all resources:

```bash
# Delete CloudFormation stack
aws cloudformation delete-stack \
  --stack-name openclaw-personal \
  --profile personal \
  --region us-east-2

# Wait for deletion
aws cloudformation wait stack-delete-complete \
  --stack-name openclaw-personal \
  --profile personal \
  --region us-east-2

# Delete ECR images (optional)
aws ecr batch-delete-image \
  --repository-name openclaw-personal \
  --image-ids imageTag=latest \
  --profile personal \
  --region us-east-2
```

## Comparison: AgentCore vs EC2

| Feature | AgentCore (This) | EC2 (Original) |
|---------|------------------|----------------|
| **Cost Model** | Pay-per-use | 24/7 fixed cost |
| **Idle Cost** | $0 | ~$50/month |
| **Scaling** | Automatic | Manual |
| **Maintenance** | Minimal | OS updates, patches |
| **Startup Time** | Cold start (~2s) | Always running |
| **Best For** | Personal, variable use | Teams, 24/7 availability |

## Security Best Practices

- ✅ Never commit `.env` file (already in `.gitignore`)
- ✅ Use AWS Secrets Manager for production
- ✅ Enable CloudTrail for audit logs
- ✅ Set monthly budget alerts
- ✅ Review IAM permissions regularly
- ✅ Rotate Discord bot token periodically

## Resources

- [OpenClaw Documentation](https://docs.openclaw.ai/)
- [AWS Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/)
- [Discord Developer Portal](https://discord.com/developers/applications)
- [AWS Cost Explorer](https://console.aws.amazon.com/cost-management/)

## Support

For issues or questions:
1. Check CloudWatch logs first
2. Review troubleshooting section
3. Check OpenClaw documentation
4. Open GitHub issue

## License

MIT License - See LICENSE file for details

---

**Status**: ✅ Working
**Last Updated**: February 26, 2026
**Deployment**: Serverless AgentCore
**Region**: us-east-2
