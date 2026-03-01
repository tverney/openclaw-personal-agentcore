# Configuration Guide - OpenClaw Personal Edition

Complete guide to configuring channel routing, model selection, and system behavior.

## Configuration Files

### 1. openclaw.json (Container Configuration)

Location: `agent-container/openclaw.json`

This file configures the OpenClaw runtime and channel routing.

```json
{
  "routing": {
    "enabled": true,
    "default_model": "${BEDROCK_MODEL_ID}",
    "channel_models": {
      "discord_general": "us.amazon.nova-lite-v1:0",
      "discord_technical": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
      "whatsapp": "us.amazon.nova-lite-v1:0",
      "telegram": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    }
  }
}
```

**Environment Variable Substitution**:
- `${AWS_REGION}` → Replaced with AWS_REGION environment variable
- `${BEDROCK_MODEL_ID}` → Replaced with BEDROCK_MODEL_ID environment variable

### 2. CloudFormation Parameters

Location: `openclaw-simplified.yaml`

Set these when deploying the stack:

```yaml
Parameters:
  AdminEmail:
    Type: String
    Description: "Email for budget alerts"
  
  MonthlyBudgetLimit:
    Type: Number
    Default: 10
    Description: "Monthly budget limit in USD"
  
  DefaultModelId:
    Type: String
    Default: "us.amazon.nova-lite-v1:0"
    Description: "Default Bedrock inference profile ID"
```

## Channel Routing Configuration

### Understanding Channels

A "channel" identifies the source of a message:
- `discord_general` - Discord #general channel
- `discord_technical` - Discord #technical channel
- `whatsapp` - WhatsApp messages
- `telegram` - Telegram messages
- `slack_casual` - Slack #casual channel
- `default` - Fallback for unknown channels

### Routing Logic

1. Message arrives with `channel` field
2. System looks up channel in `channel_models` mapping
3. If found, uses configured model
4. If not found, uses `default_model`
5. If `default_model` not set, uses environment variable `BEDROCK_MODEL_ID`

### Example Configurations

#### Cost-Optimized (All Nova Lite)

```json
{
  "routing": {
    "enabled": true,
    "default_model": "us.amazon.nova-lite-v1:0",
    "channel_models": {
      "discord_general": "us.amazon.nova-lite-v1:0",
      "whatsapp": "us.amazon.nova-lite-v1:0",
      "telegram": "us.amazon.nova-lite-v1:0"
    }
  }
}
```

**Cost**: ~$3-5/month for typical usage

#### Balanced (Nova Lite + Claude Sonnet)

```json
{
  "routing": {
    "enabled": true,
    "default_model": "us.amazon.nova-lite-v1:0",
    "channel_models": {
      "discord_general": "us.amazon.nova-lite-v1:0",
      "discord_technical": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
      "whatsapp": "us.amazon.nova-lite-v1:0",
      "telegram": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
      "slack_work": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    }
  }
}
```

**Cost**: ~$6-9/month for typical usage

#### Performance-Focused (All Claude Sonnet)

```json
{
  "routing": {
    "enabled": true,
    "default_model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "channel_models": {
      "discord_general": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
      "whatsapp": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
      "telegram": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    }
  }
}
```

**Cost**: ~$15-25/month for typical usage

## Available Models

### Amazon Nova Models

| Model | Inference Profile ID | Input Cost | Output Cost | Best For |
|-------|---------------------|------------|-------------|----------|
| Nova Lite | `us.amazon.nova-lite-v1:0` | $0.06/1M | $0.24/1M | Casual chat, simple queries |
| Nova Pro | `us.amazon.nova-pro-v1:0` | $0.80/1M | $3.20/1M | Balanced performance |

### Anthropic Claude Models

| Model | Inference Profile ID | Input Cost | Output Cost | Best For |
|-------|---------------------|------------|-------------|----------|
| Claude Haiku 4.5 | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | $1/1M | $5/1M | Fast responses |
| Claude Sonnet 4.5 | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | $3/1M | $15/1M | Complex reasoning, coding |
| Claude Opus 4.5 | `global.anthropic.claude-opus-4-5-20251101-v1:0` | $15/1M | $75/1M | Most capable |

### Inference Profile ID Format

✅ **Valid** (with region prefix):
- `us.amazon.nova-lite-v1:0`
- `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
- `eu.amazon.nova-pro-v1:0`
- `global.anthropic.claude-opus-4-5-20251101-v1:0`

❌ **Invalid** (direct model IDs):
- `anthropic.claude-sonnet-4-5-v2:0`
- `amazon.nova-lite-v1:0`

See [INFERENCE-PROFILES.md](INFERENCE-PROFILES.md) for details.

## Environment Variables

Set in CloudFormation template or AgentCore Runtime configuration:

### Required Variables

```bash
AWS_REGION=us-east-2
BEDROCK_MODEL_ID=us.amazon.nova-lite-v1:0
SESSION_BACKUP_BUCKET=openclaw-personal-sessions-XXXXX
```

### Optional Variables

```bash
# Logging level
LOG_LEVEL=INFO

# OpenClaw configuration
OPENCLAW_SKIP_ONBOARDING=1

# Port (default: 8080)
PORT=8080
```

## Budget Configuration

### Setting Budget Limits

Edit CloudFormation parameters:

```bash
aws cloudformation deploy \
  --template-file openclaw-simplified.yaml \
  --stack-name openclaw-personal \
  --parameter-overrides \
    MonthlyBudgetLimit=20 \
  --capabilities CAPABILITY_IAM
```

### Alert Thresholds

Default thresholds:
- 80% of budget → Warning email
- 100% of budget → Critical email

To customize, edit `openclaw-simplified.yaml`:

```yaml
NotificationsWithSubscribers:
  - Notification:
      NotificationType: ACTUAL
      ComparisonOperator: GREATER_THAN
      Threshold: 50  # Alert at 50%
    Subscribers:
      - SubscriptionType: SNS
        Address: !Ref BudgetAlertTopic
```

## Session Persistence Configuration

### S3 Sync Frequency

Default: Every 5 minutes

To change, edit `agent-container/server.py`:

```python
# Sync every 10 minutes instead
SYNC_INTERVAL_SECONDS = 600
```

### S3 Bucket Lifecycle

Default: Delete old versions after 30 days

To change, edit `openclaw-simplified.yaml`:

```yaml
LifecycleConfiguration:
  Rules:
    - Id: DeleteOldVersions
      Status: Enabled
      NoncurrentVersionExpiration:
        NoncurrentDays: 60  # Keep for 60 days
```

## Messaging Platform Configuration

### Discord

1. Create bot at [Discord Developer Portal](https://discord.com/developers/applications)
2. Get bot token
3. Configure in OpenClaw web UI
4. Set channel identifier in messages:

```json
{
  "message": "Hello",
  "channel": "discord_general"
}
```

### WhatsApp

1. Link WhatsApp in OpenClaw web UI
2. Set channel identifier:

```json
{
  "message": "Hello",
  "channel": "whatsapp"
}
```

### Telegram

1. Create bot with [@BotFather](https://t.me/botfather)
2. Get bot token
3. Configure in OpenClaw web UI
4. Set channel identifier:

```json
{
  "message": "Hello",
  "channel": "telegram"
}
```

## Advanced Configuration

### Custom System Prompts

Create custom prompts per channel by modifying `server.py`:

```python
CHANNEL_PROMPTS = {
    "discord_technical": "You are a technical expert. Be precise and detailed.",
    "discord_general": "You are a friendly assistant. Be casual and helpful.",
}
```

### Rate Limiting

Add rate limiting to prevent budget overruns:

```python
from functools import lru_cache
import time

@lru_cache(maxsize=1000)
def check_rate_limit(user_id: str) -> bool:
    # Implement your rate limiting logic
    pass
```

### Custom Metrics

Add custom CloudWatch metrics:

```python
import boto3

cloudwatch = boto3.client('cloudwatch')

cloudwatch.put_metric_data(
    Namespace='OpenClaw/Personal',
    MetricData=[
        {
            'MetricName': 'MessageCount',
            'Value': 1,
            'Unit': 'Count',
            'Dimensions': [
                {'Name': 'Channel', 'Value': channel},
                {'Name': 'Model', 'Value': model_used}
            ]
        }
    ]
)
```

## Testing Configuration Changes

After modifying configuration:

1. **Rebuild Docker image**:
   ```bash
   docker buildx build --platform linux/arm64 -t openclaw-personal:latest .
   ```

2. **Push to ECR**:
   ```bash
   docker tag openclaw-personal:latest $ECR_URI:latest
   docker push $ECR_URI:latest
   ```

3. **Update AgentCore Runtime**:
   ```bash
   aws bedrock-agentcore update-runtime \
     --runtime-id $RUNTIME_ID \
     --container-uri $ECR_URI:latest
   ```

4. **Test the changes**:
   ```bash
   aws bedrock-agentcore invoke-runtime \
     --runtime-id $RUNTIME_ID \
     --body '{"message": "test", "channel": "your_channel"}'
   ```

## Configuration Best Practices

1. **Start with Nova Lite** for all channels, then upgrade specific channels as needed
2. **Monitor costs** for 1 week before adjusting budget limits
3. **Use descriptive channel names** (e.g., `discord_coding` not `dc1`)
4. **Test routing** with sample messages before production use
5. **Keep inference profile IDs** up to date (check Bedrock console for new versions)
6. **Enable S3 versioning** to prevent accidental data loss
7. **Set budget alerts** at 50%, 80%, and 100% for better cost control

## Troubleshooting Configuration

### Model Not Found Error

**Symptom**: "Model not found" in logs

**Solution**: Verify model is enabled in Bedrock console and use correct inference profile ID

### Channel Routing Not Working

**Symptom**: All messages use default model

**Solution**: Check `channel` field in message payload matches `channel_models` keys exactly

### Budget Alerts Not Received

**Symptom**: No emails when budget threshold reached

**Solution**: Confirm SNS subscription in email, check spam folder

### S3 Sync Failures

**Symptom**: "S3 sync failed" in CloudWatch logs

**Solution**: Verify IAM role has S3 permissions, check bucket exists

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for more issues and solutions.
