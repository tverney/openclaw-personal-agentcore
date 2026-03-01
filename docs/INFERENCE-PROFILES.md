# Inference Profile IDs - Understanding and Usage

## What Are Inference Profile IDs?

Inference Profile IDs are Amazon Bedrock's cross-region identifiers for AI models. They enable automatic failover and load balancing across AWS regions.

### Key Differences

| Feature | Direct Model ID | Inference Profile ID |
|---------|----------------|---------------------|
| Format | `anthropic.claude-sonnet-4-5-v2:0` | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| Region Prefix | ❌ No | ✅ Yes (`us.`, `eu.`, `global.`) |
| Cross-Region Failover | ❌ No | ✅ Yes |
| Load Balancing | ❌ No | ✅ Yes |
| Required for AgentCore | ❌ No | ✅ Yes |

## Why Use Inference Profile IDs?

### 1. Automatic Failover

If one region is unavailable, requests automatically route to another region:

```
Request → us-east-1 (unavailable) → us-west-2 (success)
```

### 2. Load Balancing

Requests distribute across multiple regions for better performance:

```
Request 1 → us-east-1
Request 2 → us-west-2
Request 3 → eu-west-1
```

### 3. Consistent Pricing

Same price regardless of which region processes your request.

### 4. AgentCore Requirement

AgentCore Runtime requires inference profile IDs (not direct model IDs).

## Inference Profile ID Format

### Structure

```
<region>.<provider>.<model-name>-<version>:<revision>
```

### Examples

✅ **Valid Inference Profile IDs**:
```
us.amazon.nova-lite-v1:0
us.amazon.nova-pro-v1:0
us.anthropic.claude-sonnet-4-5-20250929-v1:0
us.anthropic.claude-haiku-4-5-20251001-v1:0
eu.amazon.nova-lite-v1:0
global.anthropic.claude-opus-4-5-20251101-v1:0
```

❌ **Invalid Direct Model IDs**:
```
anthropic.claude-sonnet-4-5-v2:0
amazon.nova-lite-v1:0
claude-sonnet-4-5
nova-lite
```

### Region Prefixes

| Prefix | Coverage | Use Case |
|--------|----------|----------|
| `us.` | US regions | North America users |
| `eu.` | EU regions | European users |
| `global.` | All regions | Worldwide availability |

## Available Inference Profile IDs

### Amazon Nova Models

```
us.amazon.nova-lite-v1:0
us.amazon.nova-pro-v1:0
us.amazon.nova-micro-v1:0
```

**Pricing**:
- Nova Lite: $0.06/1M input, $0.24/1M output
- Nova Pro: $0.80/1M input, $3.20/1M output
- Nova Micro: $0.035/1M input, $0.14/1M output

### Anthropic Claude Models

```
us.anthropic.claude-haiku-4-5-20251001-v1:0
us.anthropic.claude-sonnet-4-5-20250929-v1:0
global.anthropic.claude-opus-4-5-20251101-v1:0
```

**Pricing**:
- Claude Haiku: $1/1M input, $5/1M output
- Claude Sonnet: $3/1M input, $15/1M output
- Claude Opus: $15/1M input, $75/1M output

## How to Find Inference Profile IDs

### Method 1: AWS Console

1. Open AWS Console → Amazon Bedrock
2. Navigate to "Inference profiles"
3. Find your model
4. Copy the "Inference profile ID"

### Method 2: AWS CLI

```bash
# List all inference profiles
aws bedrock list-inference-profiles --region us-east-2

# Filter for specific model
aws bedrock list-inference-profiles \
  --region us-east-2 \
  --query 'inferenceProfiles[?contains(modelId, `nova-lite`)]'
```

### Method 3: Bedrock API

```python
import boto3

bedrock = boto3.client('bedrock', region_name='us-east-2')
response = bedrock.list_inference_profiles()

for profile in response['inferenceProfiles']:
    print(f"{profile['inferenceProfileName']}: {profile['inferenceProfileId']}")
```

## Validation in Code

The simplified server validates inference profile IDs:

```python
def validate_inference_profile_id(model_id: str) -> bool:
    """
    Validate that model_id is an inference profile ID.
    
    Returns True if model_id starts with valid region prefix.
    """
    valid_prefixes = ("us.", "eu.", "global.")
    return model_id.startswith(valid_prefixes)
```

### Usage Example

```python
# Valid
validate_inference_profile_id("us.amazon.nova-lite-v1:0")  # True

# Invalid
validate_inference_profile_id("amazon.nova-lite-v1:0")  # False
validate_inference_profile_id("anthropic.claude-sonnet-4-5-v2:0")  # False
```

## Error Messages

### Invalid Model ID Error

```
ERROR: Invalid model ID 'anthropic.claude-sonnet-4-5-v2:0' - 
must be inference profile ID (e.g., 'us.amazon.nova-lite-v1:0'), 
not direct model ID
```

**Solution**: Replace with inference profile ID:
```
anthropic.claude-sonnet-4-5-v2:0 
→ us.anthropic.claude-sonnet-4-5-20250929-v1:0
```

### Model Not Found Error

```
ERROR: Model 'us.amazon.nova-lite-v1:0' not found
```

**Solution**: Verify model is enabled in Bedrock console

## Configuration Examples

### openclaw.json

```json
{
  "routing": {
    "enabled": true,
    "default_model": "us.amazon.nova-lite-v1:0",
    "channel_models": {
      "discord_general": "us.amazon.nova-lite-v1:0",
      "discord_technical": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    }
  }
}
```

### CloudFormation Parameters

```yaml
Parameters:
  DefaultModelId:
    Type: String
    Default: "us.amazon.nova-lite-v1:0"
    AllowedValues:
      - "us.amazon.nova-lite-v1:0"
      - "us.amazon.nova-pro-v1:0"
      - "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
      - "us.anthropic.claude-haiku-4-5-20251001-v1:0"
      - "global.anthropic.claude-opus-4-5-20251101-v1:0"
```

## Migration from Direct Model IDs

If you have existing code using direct model IDs:

### Before (Direct Model IDs)

```python
model_id = "anthropic.claude-sonnet-4-5-v2:0"
```

### After (Inference Profile IDs)

```python
model_id = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
```

### Automated Migration

```python
def migrate_to_inference_profile(direct_model_id: str, region: str = "us") -> str:
    """Convert direct model ID to inference profile ID."""
    
    mappings = {
        "anthropic.claude-sonnet-4-5-v2:0": f"{region}.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "anthropic.claude-haiku-4-5-v1:0": f"{region}.anthropic.claude-haiku-4-5-20251001-v1:0",
        "amazon.nova-lite-v1:0": f"{region}.amazon.nova-lite-v1:0",
        "amazon.nova-pro-v1:0": f"{region}.amazon.nova-pro-v1:0",
    }
    
    return mappings.get(direct_model_id, f"{region}.amazon.nova-lite-v1:0")
```

## Best Practices

1. **Always use inference profile IDs** in production
2. **Use `us.` prefix** for North America deployments
3. **Use `eu.` prefix** for European deployments
4. **Use `global.` prefix** for worldwide availability (limited models)
5. **Validate model IDs** before deployment
6. **Keep IDs up to date** as new versions release
7. **Test failover** by temporarily disabling a region

## Troubleshooting

### Issue: "Invalid inference profile ID"

**Cause**: Using direct model ID instead of inference profile ID

**Solution**: Add region prefix:
```
amazon.nova-lite-v1:0 → us.amazon.nova-lite-v1:0
```

### Issue: "Model not available in region"

**Cause**: Model not enabled in your AWS region

**Solution**: 
1. Open Bedrock console
2. Navigate to "Model access"
3. Request access to the model
4. Wait for approval

### Issue: "Cross-region failover not working"

**Cause**: Using direct model ID

**Solution**: Switch to inference profile ID with region prefix

## Additional Resources

- [Bedrock Inference Profiles Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles.html)
- [Bedrock Model IDs](https://docs.aws.amazon.com/bedrock/latest/userguide/model-ids.html)
- [Cross-Region Inference](https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html)

## Summary

- ✅ Use inference profile IDs (with region prefix)
- ❌ Don't use direct model IDs (without region prefix)
- ✅ Validate IDs before deployment
- ✅ Test failover in non-production environments
- ✅ Keep IDs updated as new versions release
