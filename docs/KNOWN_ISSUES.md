# Known Issues with OpenClaw + Bedrock + Discord

## Current Issue: Reasoning Content Error

### Problem
When using OpenClaw 2026.2.25 with AWS Bedrock (Nova models) and Discord, you get this error:
```
User messages cannot contain reasoning content. Please remove the reasoning content and try again.
```

### Root Cause
This is a known bug in OpenClaw tracked at:
- https://github.com/openclaw/openclaw/issues/6470
- https://github.com/langchain-ai/langchain-aws/issues/401

OpenClaw is:
1. Setting `thinking=low` on all models (even non-reasoning ones)
2. Including reasoning_content in message history
3. Sending that reasoning_content back to Bedrock API, which rejects it

### Why It Happens
- First message works fine
- AI responds with reasoning_content in the response
- OpenClaw includes that reasoning_content in the next message's history
- Bedrock API rejects it because "User messages cannot contain reasoning content"

### Solutions

#### Option 1: Request Claude Access (Recommended)
1. Go to AWS Bedrock Console → Model access
2. Request access to "Anthropic Claude Sonnet 4"
3. Wait for approval (usually instant)
4. Update `.env`:
   ```
   BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-20250514-v1:0
   ```
5. Rebuild and restart container

#### Option 2: Wait for OpenClaw Fix
Monitor the GitHub issue for updates. The OpenClaw team is aware of this bug.

#### Option 3: Use Different Integration
Instead of using OpenClaw's Discord integration, you could:
- Use the HTTP API directly
- Build a custom Discord bot that doesn't include reasoning_content in history
- Use a different chat platform that OpenClaw handles better

## Current Configuration

Your setup is correctly configured:
- ✅ Docker container built successfully
- ✅ AWS credentials mounted properly
- ✅ Bedrock provider configured correctly
- ✅ Discord bot connected
- ❌ Reasoning content bug preventing multi-turn conversations

## Next Steps

1. Request Claude access in AWS Bedrock Console
2. Once approved, update BEDROCK_MODEL_ID to Claude Sonnet
3. Rebuild container: `docker build -f agent-container/Dockerfile -t openclaw-personal:latest .`
4. Restart: `docker run -d --name openclaw-discord -p 8080:8080 --env-file agent-container/.env -e AWS_PROFILE=personal -v ~/.aws:/root/.aws:ro openclaw-personal:latest`

## References
- OpenClaw Issue: https://github.com/openclaw/openclaw/issues/6470
- LangChain AWS Issue: https://github.com/langchain-ai/langchain-aws/issues/401
- AWS Bedrock Reasoning Content Docs: https://docs.aws.amazon.com/bedrock/latest/userguide/nova-2-sft-data-prep.html
