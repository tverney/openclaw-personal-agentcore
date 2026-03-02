# AgentCore OpenClaw Personal — Serverless AI Assistant on AWS

> Cost-optimized [OpenClaw](https://github.com/aws-samples/sample-OpenClaw-on-AWS-with-Bedrock) deployment using AWS Bedrock AgentCore Runtime, with Discord bot integration.

## What Is This?

A single-user, serverless deployment of OpenClaw on AWS. Instead of running an EC2 instance 24/7, the AI runs on-demand via AgentCore Runtime — you only pay when you use it.

An optional Discord bot (Python, on a tiny EC2 t4g.nano) lets you chat with the AI from Discord.

## Cost Comparison

| | Original EC2 Deployment | This AgentCore Deployment |
|---|---|---|
| Compute | EC2 running 24/7 (~$35/mo) | Serverless, pay-per-use |
| Complexity | Multi-tenant, VPC required | Single-user, minimal infra |
| Typical cost | ~$80/month | ~$6-13/month |

## Project Structure

```
├── openclaw-simplified.yaml    # CloudFormation template (everything)
├── agent-container/            # Docker container for AgentCore
│   ├── server.py               # HTTP server wrapping OpenClaw
│   ├── openclaw.json           # OpenClaw configuration
│   ├── Dockerfile
│   └── requirements.txt
├── discord-bot/                # Python Discord bot (runs on EC2)
│   ├── bot.py                  # Bot using boto3 invoke-agent-runtime
│   └── requirements.txt
├── scripts/                    # Deployment & utility scripts
│   ├── deploy.sh               # Full deployment (build + push + CFN)
│   ├── quick-redeploy.sh       # Rebuild & push container only
│   ├── deploy-discord-bot.sh   # Update bot on EC2 via SSM
│   └── ...
├── tests/                      # Test suite
└── docs/                       # Documentation
```

## Quick Start

### 1. Configure

```bash
cp agent-container/.env.example agent-container/.env
# Edit with your Discord bot token (optional)
```

### 2. Deploy

```bash
aws cloudformation deploy \
  --template-file openclaw-simplified.yaml \
  --stack-name openclaw-personal \
  --parameter-overrides \
    AdminEmail=your-email@example.com \
    MonthlyBudgetLimit=15 \
    DefaultModelId=us.anthropic.claude-3-5-haiku-20241022-v1:0 \
    EnableDiscordBot=true \
    DiscordBotToken=YOUR_TOKEN \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-2
```

### 3. Build & Push Container

```bash
bash scripts/deploy.sh
```

### 4. Chat

In Discord: `@YourBot hello!`

## Key Features

- **Serverless AI**: AgentCore Runtime — no idle costs
- **Session persistence**: Conversations and memory backed up to S3
- **Discord integration**: Python bot on EC2 t4g.nano (~$3/mo)
- **Budget protection**: SNS alerts at configurable threshold
- **Model flexibility**: Switch models via CloudFormation parameter

## Documentation

- [Deployment Guide](docs/DEPLOYMENT.md)
- [Discord Setup](docs/DISCORD-SETUP.md)
- [Configuration](docs/CONFIGURATION.md)
- [Session Persistence](docs/SESSION-PERSISTENCE.md)
- [Cost Optimization](docs/COST-OPTIMIZATION.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Inference Profiles](docs/INFERENCE-PROFILES.md)
- [Security](docs/SECURITY.md)

## License

See [LICENSE](LICENSE) for details.
