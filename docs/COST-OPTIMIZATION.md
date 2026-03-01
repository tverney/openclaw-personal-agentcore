# Cost Optimization Guide - OpenClaw Personal Edition

Strategies and tips for minimizing costs while maintaining functionality.

## Cost Breakdown

### Current Architecture Costs

| Service | Monthly Cost | Optimization Potential |
|---------|--------------|------------------------|
| Bedrock API (Nova Lite) | $3-5 | ⭐⭐⭐ High |
| Bedrock API (Claude Sonnet) | $2-3 | ⭐⭐⭐ High |
| AgentCore Runtime | $0.50-1 | ⭐ Low |
| ECR Storage | $0.10 | ⭐ Low |
| CloudWatch Logs | $0.50 | ⭐⭐ Medium |
| S3 Session Storage | $0.03 | ⭐ Low |
| **Total** | **$6-9** | |

### Savings vs Original Architecture

| Component | Original | Simplified | Savings |
|-----------|----------|------------|---------|
| EC2 Gateway | $35 | $0 | $35 |
| VPC Endpoints | $22 | $0 | $22 |
| EBS Storage | $2.40 | $0 | $2.40 |
| **Total Savings** | | | **$59.40/month** |

## Optimization Strategies

### 1. Model Selection (Highest Impact)

**Use Nova Lite for Simple Queries**

Nova Lite is 98% cheaper than Claude Sonnet for input tokens:
- Nova Lite: $0.06/1M input tokens
- Claude Sonnet: $3/1M input tokens

**Example Configuration**:
```json
{
  "routing": {
    "enabled": true,
    "default_model": "us.amazon.nova-lite-v1:0",
    "channel_models": {
      "discord_general": "us.amazon.nova-lite-v1:0",
      "discord_technical": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
      "whatsapp": "us.amazon.nova-lite-v1:0"
    }
  }
}
```

**Estimated Savings**: $10-15/month

### 2. Channel Routing (High Impact)

**Route by Complexity**

- Casual chat → Nova Lite
- Technical questions → Claude Sonnet
- Code generation → Claude Sonnet
- Simple Q&A → Nova Lite

**Example**:
```json
{
  "discord_casual": "us.amazon.nova-lite-v1:0",      // $0.06/1M
  "discord_coding": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",  // $3/1M
  "whatsapp": "us.amazon.nova-lite-v1:0",            // $0.06/1M
  "telegram": "us.amazon.nova-lite-v1:0"             // $0.06/1M
}
```

**Estimated Savings**: $5-10/month

### 3. Context Window Management (Medium Impact)

**Reset Conversations Regularly**

Long conversations = more tokens = higher costs

**Strategies**:
- Use `/reset` command after completing a task
- Set max conversation length (e.g., 10 messages)
- Implement automatic reset after 1 hour of inactivity

**Implementation**:
```python
MAX_CONVERSATION_LENGTH = 10
CONVERSATION_TIMEOUT = 3600  # 1 hour

def should_reset_conversation(session):
    if len(session['messages']) > MAX_CONVERSATION_LENGTH:
        return True
    if time.time() - session['last_activity'] > CONVERSATION_TIMEOUT:
        return True
    return False
```

**Estimated Savings**: $2-5/month

### 4. CloudWatch Logs Retention (Low Impact)

**Reduce Log Retention Period**

Default: 30 days  
Optimized: 7 days

**Update CloudFormation**:
```yaml
LogGroup:
  Type: AWS::Logs::LogGroup
  Properties:
    LogGroupName: /aws/bedrock-agentcore/openclaw-personal
    RetentionInDays: 7  # Changed from 30
```

**Estimated Savings**: $0.20-0.30/month

### 5. S3 Lifecycle Policies (Low Impact)

**Delete Old Session Versions Faster**

Default: 30 days  
Optimized: 7 days

**Update CloudFormation**:
```yaml
LifecycleConfiguration:
  Rules:
    - Id: DeleteOldVersions
      Status: Enabled
      NoncurrentVersionExpiration:
        NoncurrentDays: 7  # Changed from 30
```

**Estimated Savings**: $0.01-0.02/month

### 6. Request Batching (Medium Impact)

**Combine Multiple Queries**

Instead of:
```
User: What's the weather?
Bot: It's sunny.
User: What about tomorrow?
Bot: It will rain.
```

Encourage:
```
User: What's the weather today and tomorrow?
Bot: Today is sunny, tomorrow will rain.
```

**Estimated Savings**: $1-3/month

### 7. Rate Limiting (High Impact for High Usage)

**Prevent Runaway Costs**

Implement per-user rate limits:

```python
from functools import lru_cache
import time

# Max 100 requests per user per day
MAX_REQUESTS_PER_DAY = 100
REQUEST_WINDOW = 86400  # 24 hours

@lru_cache(maxsize=1000)
def check_rate_limit(user_id: str) -> bool:
    # Implement rate limiting logic
    # Return False if limit exceeded
    pass
```

**Estimated Savings**: Prevents unexpected spikes

### 8. Budget Alerts (Critical)

**Set Multiple Thresholds**

Don't wait until 100% to get alerted:

```yaml
NotificationsWithSubscribers:
  - Notification:
      Threshold: 50  # Early warning
  - Notification:
      Threshold: 80  # Action required
  - Notification:
      Threshold: 100  # Critical
```

**Benefit**: Catch cost overruns early

## Cost Monitoring

### Daily Cost Tracking

```bash
# Check today's costs
aws ce get-cost-and-usage \
  --time-period Start=$(date +%Y-%m-01),End=$(date +%Y-%m-%d) \
  --granularity DAILY \
  --metrics BlendedCost \
  --group-by Type=SERVICE
```

### Cost by Model

Add custom CloudWatch metrics:

```python
cloudwatch.put_metric_data(
    Namespace='OpenClaw/Costs',
    MetricData=[{
        'MetricName': 'TokenCost',
        'Value': cost_estimate,
        'Unit': 'None',
        'Dimensions': [
            {'Name': 'Model', 'Value': model_used},
            {'Name': 'Channel', 'Value': channel}
        ]
    }]
)
```

### Cost Dashboard

Create CloudWatch dashboard:

```bash
aws cloudwatch put-dashboard \
  --dashboard-name openclaw-costs \
  --dashboard-body file://dashboard.json
```

**dashboard.json**:
```json
{
  "widgets": [
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["OpenClaw/Costs", "TokenCost", {"stat": "Sum"}]
        ],
        "period": 86400,
        "stat": "Sum",
        "region": "us-east-2",
        "title": "Daily Token Costs"
      }
    }
  ]
}
```

## Cost Optimization Checklist

### Initial Setup
- [ ] Set budget limit to $10/month
- [ ] Configure alerts at 50%, 80%, 100%
- [ ] Use Nova Lite as default model
- [ ] Enable channel routing
- [ ] Set CloudWatch logs retention to 7 days

### Weekly Review
- [ ] Check Cost Explorer for trends
- [ ] Review CloudWatch metrics
- [ ] Identify high-cost channels
- [ ] Adjust model routing if needed

### Monthly Review
- [ ] Compare actual vs budgeted costs
- [ ] Review model usage distribution
- [ ] Optimize channel routing
- [ ] Update budget if needed

## Cost Scenarios

### Scenario 1: Casual User (50 messages/day)

**Configuration**:
- All channels use Nova Lite
- Average 500 tokens per message

**Monthly Cost**:
- Input tokens: 50 msg/day × 30 days × 500 tokens = 750K tokens
- Output tokens: 50 msg/day × 30 days × 250 tokens = 375K tokens
- Cost: (750K × $0.06/1M) + (375K × $0.24/1M) = $0.14
- **Total: ~$1-2/month** (including infrastructure)

### Scenario 2: Moderate User (200 messages/day)

**Configuration**:
- 80% Nova Lite, 20% Claude Sonnet
- Average 500 tokens per message

**Monthly Cost**:
- Nova Lite: 160 msg/day × 30 days × 500 tokens = 2.4M input tokens
- Claude Sonnet: 40 msg/day × 30 days × 500 tokens = 600K input tokens
- Cost: (2.4M × $0.06/1M) + (600K × $3/1M) + output = $2.14
- **Total: ~$3-5/month** (including infrastructure)

### Scenario 3: Heavy User (500 messages/day)

**Configuration**:
- 70% Nova Lite, 30% Claude Sonnet
- Average 500 tokens per message

**Monthly Cost**:
- Nova Lite: 350 msg/day × 30 days × 500 tokens = 5.25M input tokens
- Claude Sonnet: 150 msg/day × 30 days × 500 tokens = 2.25M input tokens
- Cost: (5.25M × $0.06/1M) + (2.25M × $3/1M) + output = $7.07
- **Total: ~$8-12/month** (including infrastructure)

## Emergency Cost Controls

### If Costs Spike Unexpectedly

1. **Immediate Actions**:
   ```bash
   # Switch all channels to Nova Lite
   # Edit openclaw.json, rebuild, redeploy
   
   # Check recent high-cost requests
   aws logs filter-log-events \
     --log-group-name /aws/bedrock-agentcore/openclaw-personal \
     --filter-pattern "cost_estimate" \
     --start-time $(date -d '1 hour ago' +%s)000
   ```

2. **Temporary Measures**:
   - Disable expensive channels
   - Implement strict rate limiting
   - Reduce context window size

3. **Long-term Solutions**:
   - Analyze usage patterns
   - Optimize model routing
   - Implement request caching
   - Add user quotas

## Advanced Optimization

### Request Caching

Cache common queries:

```python
from functools import lru_cache

@lru_cache(maxsize=100)
def get_cached_response(query_hash: str):
    # Return cached response if available
    pass
```

**Estimated Savings**: $1-3/month

### Prompt Optimization

Shorter prompts = lower costs:

**Before**:
```
You are a helpful assistant. Please provide a detailed answer to the following question, including examples and explanations: What is Python?
```

**After**:
```
Explain Python briefly.
```

**Estimated Savings**: $0.50-1/month

### Output Length Limiting

Limit response length:

```python
max_tokens = 500  # Limit output to 500 tokens
```

**Estimated Savings**: $1-2/month

## Summary

### Top 3 Cost Optimizations

1. **Use Nova Lite for 80%+ of requests** → Save $10-15/month
2. **Implement channel routing** → Save $5-10/month
3. **Reset conversations regularly** → Save $2-5/month

### Expected Monthly Costs

- **Minimal usage** (50 msg/day): $1-2
- **Light usage** (100 msg/day): $2-4
- **Moderate usage** (200 msg/day): $4-7
- **Heavy usage** (500 msg/day): $8-12

### Budget Recommendations

- **Conservative**: $5/month
- **Balanced**: $10/month (default)
- **Generous**: $20/month

## Additional Resources

- [AWS Cost Explorer](https://console.aws.amazon.com/cost-management/home)
- [Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/)
- [CloudWatch Pricing](https://aws.amazon.com/cloudwatch/pricing/)
- [CONFIGURATION.md](CONFIGURATION.md) - Model configuration
- [INFERENCE-PROFILES.md](INFERENCE-PROFILES.md) - Model selection
