# Discord Bot for OpenClaw Personal

Python Discord bot that connects your Discord server to your OpenClaw AgentCore deployment on AWS.

## Architecture

```
Discord Server
    ↓ (mentions / DMs)
Discord Bot (Python, runs on EC2 t4g.nano)
    ↓ (boto3 invoke-agent-runtime)
AWS AgentCore Runtime
    ↓
OpenClaw Container + Bedrock Models
```

The bot runs on a small EC2 instance (deployed via CloudFormation) and calls AgentCore via `boto3`.

## Prerequisites

- OpenClaw Personal deployed on AWS (see main README)
- Discord bot created (see [docs/DISCORD-SETUP.md](../docs/DISCORD-SETUP.md))
- Python 3.9+
- AWS credentials configured

## How It Works

- Responds to @mentions and DMs
- Shows 🐾 reaction while processing
- Typing indicator stays active during AI response
- Per-channel processing lock prevents duplicate responses
- Retries once on 502 errors (cold-start)
- 180s timeout per request
- Messages over 2000 chars are split automatically

## Local Development

```bash
cd discord-bot
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Discord token and Runtime ARN
python bot.py
```

## EC2 Deployment

The CloudFormation template (`openclaw-simplified.yaml`) deploys the bot as a systemd service on a `t4g.nano` instance when `EnableDiscordBot=true`.

To update the bot on EC2 after code changes, use the deploy script:
```bash
bash scripts/deploy-discord-bot.sh
```

## Configuration

See `.env.example` for all configuration options:

| Variable | Description |
|----------|-------------|
| `DISCORD_BOT_TOKEN` | Bot token from Discord Developer Portal |
| `AGENTCORE_RUNTIME_ARN` | AgentCore Runtime ARN from CloudFormation outputs |
| `AWS_REGION` | AWS region (default: us-east-2) |

## Cost

- EC2 t4g.nano: ~$3/month
- AI usage depends on model and volume

## Troubleshooting

See [docs/TROUBLESHOOTING.md](../docs/TROUBLESHOOTING.md) for common issues.
