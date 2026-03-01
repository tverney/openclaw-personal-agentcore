# Discord Configuration Guide

Complete step-by-step guide to configure Discord with your OpenClaw Personal deployment.

## Overview

This guide will help you:
1. Create a Discord bot
2. Configure OpenClaw to connect to Discord
3. Set up channel-specific model routing
4. Test your Discord integration

## Prerequisites

- ✅ OpenClaw Personal stack deployed on AWS
- ✅ Discord account
- ✅ Discord server where you have admin permissions

## Step 1: Create Discord Bot

### 1.1 Go to Discord Developer Portal

Visit: https://discord.com/developers/applications

### 1.2 Create New Application

1. Click **"New Application"** button
2. Enter application name (e.g., "OpenClaw Personal")
3. Click **"Create"**

### 1.3 Configure Bot

1. Go to **"Bot"** tab in left sidebar
2. Click **"Add Bot"**
3. Confirm by clicking **"Yes, do it!"**

### 1.4 Get Bot Token

1. Under **"TOKEN"** section, click **"Reset Token"**
2. Click **"Copy"** to copy the token
3. **Save this token securely** - you'll need it later

⚠️ **Important**: Never share your bot token publicly!

### 1.5 Configure Bot Permissions

Under **"Privileged Gateway Intents"**, enable:
- ✅ **MESSAGE CONTENT INTENT** (required to read messages)
- ✅ **SERVER MEMBERS INTENT** (optional, for member info)

### 1.6 Generate Invite Link

1. Go to **"OAuth2"** → **"URL Generator"** tab
2. Under **"SCOPES"**, select:
   - ✅ `bot`
   - ✅ `applications.commands`
3. Under **"BOT PERMISSIONS"**, select:
   - ✅ `Send Messages`
   - ✅ `Read Messages/View Channels`
   - ✅ `Read Message History`
   - ✅ `Embed Links`
   - ✅ `Attach Files`
4. Copy the generated URL at the bottom

### 1.7 Invite Bot to Your Server

1. Paste the URL in your browser
2. Select your Discord server
3. Click **"Authorize"**
4. Complete the CAPTCHA

Your bot should now appear in your server's member list (offline).

## Step 2: Configure Discord Bot Token

### Important Note About OpenClaw

OpenClaw in this deployment runs **inside the Docker container** on AWS AgentCore Runtime. You don't need to install OpenClaw locally. Instead, you'll configure Discord by:

1. Setting environment variables in your CloudFormation stack
2. Modifying the openclaw.json configuration file
3. Rebuilding and redeploying the Docker container

### 2.1 Set Discord Bot Token as Environment Variable

You have two options:

**Option A: Add to CloudFormation Template** (Recommended)

Edit `openclaw-simplified.yaml` and add the Discord token parameter:

```yaml
Parameters:
  # ... existing parameters ...
  
  DiscordBotToken:
    Type: String
    NoEcho: true
    Description: "Discord bot token"
```

Then add it to the AgentCore Runtime environment:

```yaml
AgentCoreRuntime:
  Type: AWS::BedrockAgentCore::Runtime
  Properties:
    # ... existing properties ...
    Environment:
      - Name: AWS_REGION
        Value: !Ref AWS::Region
      - Name: BEDROCK_MODEL_ID
        Value: !Ref DefaultModelId
      - Name: SESSION_BACKUP_BUCKET
        Value: !Ref SessionBackupBucket
      - Name: DISCORD_BOT_TOKEN
        Value: !Ref DiscordBotToken
```

**Option B: Use AWS Systems Manager Parameter Store**

Store the token securely:

```bash
aws ssm put-parameter \
  --name "/openclaw/discord/bot-token" \
  --value "YOUR_BOT_TOKEN_HERE" \
  --type "SecureString" \
  --description "Discord bot token for OpenClaw"
```

Then reference it in your application code.

### 2.2 Configure OpenClaw for Discord

OpenClaw doesn't have a built-in Discord integration in this simplified deployment. Instead, Discord messages will be sent to your AgentCore Runtime via webhooks or a Discord bot library.

**For this simplified setup, you have two approaches:**

**Approach 1: Use Discord.js Bot (Recommended)**

You'll need to create a simple Discord bot that forwards messages to your AgentCore Runtime. This requires:

1. A separate Discord bot application (Node.js)
2. The bot sends messages to your AgentCore `/invocations` endpoint
3. The bot receives responses and sends them back to Discord

**Approach 2: Use Discord Webhooks**

Configure Discord webhooks to send messages directly to your AgentCore endpoint (requires custom webhook handling).

### 2.3 Alternative: Deploy Discord Bot Separately

Since this is a simplified deployment focused on the AgentCore Runtime, the easiest approach is to:

1. **Keep your Discord bot separate** (running locally or on a small EC2 instance)
2. **Have the bot call your AgentCore Runtime** via HTTP
3. **Use channel routing** to select the right model

Here's a simple Discord bot example:

```javascript
// discord-bot.js
const { Client, GatewayIntentBits } = require('discord.js');
const axios = require('axios');

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
  ],
});

const AGENTCORE_ENDPOINT = 'YOUR_AGENTCORE_RUNTIME_URL';

// Map Discord channel IDs to routing identifiers
const CHANNEL_MAPPING = {
  '123456789012345678': 'discord_general',
  '987654321098765432': 'discord_technical',
};

client.on('messageCreate', async (message) => {
  if (message.author.bot) return;
  
  // Determine channel routing
  const channel = CHANNEL_MAPPING[message.channel.id] || 'discord_general';
  
  try {
    // Call AgentCore Runtime
    const response = await axios.post(AGENTCORE_ENDPOINT + '/invocations', {
      message: message.content,
      channel: channel,
    });
    
    // Send response back to Discord
    await message.reply(response.data.output.message);
  } catch (error) {
    console.error('Error calling AgentCore:', error);
    await message.reply('Sorry, I encountered an error processing your request.');
  }
});

client.login(process.env.DISCORD_BOT_TOKEN);
```

### 2.4 Install and Run Discord Bot

```bash
# Create a new directory for your Discord bot
mkdir discord-bot
cd discord-bot

# Initialize npm project
npm init -y

# Install dependencies
npm install discord.js axios

# Create the bot file
# (paste the code from 2.3 above into discord-bot.js)

# Set your Discord bot token
export DISCORD_BOT_TOKEN="your_bot_token_here"

# Run the bot
node discord-bot.js
```

The bot will now:
1. Listen for messages in Discord
2. Forward them to your AgentCore Runtime with the correct channel identifier
3. Send the AI response back to Discord

## Step 3: Configure Channel Routing

### 3.1 Understand Channel Identifiers

Your OpenClaw deployment supports different models for different Discord channels:

- `discord_general` → Nova Lite (cheap, fast)
- `discord_technical` → Claude Sonnet 4.5 (smart, expensive)

### 3.2 Get Discord Channel IDs

To route specific Discord channels to specific models:

1. **Enable Developer Mode** in Discord:
   - User Settings → Advanced → Developer Mode (toggle ON)

2. **Get Channel ID**:
   - Right-click on a channel
   - Click **"Copy Channel ID"**
   - Save this ID

### 3.3 Map Channels to Identifiers

Edit `agent-container/openclaw.json`:

```json
{
  "discord": {
    "channels": {
      "123456789012345678": "discord_general",
      "987654321098765432": "discord_technical"
    }
  },
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

Replace the channel IDs with your actual Discord channel IDs.

### 3.4 Rebuild and Deploy

After modifying the configuration:

```bash
# Navigate to agent-container directory
cd agent-container

# Rebuild Docker image
docker buildx build --platform linux/arm64 -t openclaw-personal:latest .

# Authenticate with ECR
aws ecr get-login-password --region us-east-2 | \
  docker login --username AWS --password-stdin \
  354444542378.dkr.ecr.us-east-2.amazonaws.com

# Tag image
docker tag openclaw-personal:latest \
  354444542378.dkr.ecr.us-east-2.amazonaws.com/openclaw-personal:latest

# Push to ECR
docker push 354444542378.dkr.ecr.us-east-2.amazonaws.com/openclaw-personal:latest
```

The AgentCore Runtime will automatically pull the new image.

## Step 4: Test Discord Integration

### 4.1 Basic Test

In any Discord channel where your bot has access:

```
@YourBot hello
```

The bot should respond with a message.

### 4.2 Test Channel Routing

**Test General Channel (Nova Lite)**:
```
@YourBot what's 2+2?
```
Expected: Fast, simple response

**Test Technical Channel (Claude Sonnet)**:
```
@YourBot explain how async/await works in JavaScript
```
Expected: Detailed, technical explanation

### 4.3 Verify Model Usage

Check CloudWatch Logs to see which model was used:

```bash
aws logs tail /aws/bedrock-agentcore/openclaw-personal --follow
```

Look for log entries like:
```
Processing message from channel 'discord_general' using model 'us.amazon.nova-lite-v1:0'
```

## Step 5: Advanced Configuration

### 5.1 Custom Commands

Add custom slash commands in OpenClaw web UI:

1. Go to **"Commands"** tab
2. Click **"Add Command"**
3. Configure:
   - **Name**: `ask`
   - **Description**: "Ask OpenClaw a question"
   - **Options**: `question` (string, required)

### 5.2 Role-Based Routing

Route messages based on user roles:

```json
{
  "discord": {
    "role_routing": {
      "123456789012345678": "discord_admin",
      "987654321098765432": "discord_user"
    }
  },
  "routing": {
    "channel_models": {
      "discord_admin": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
      "discord_user": "us.amazon.nova-lite-v1:0"
    }
  }
}
```

### 5.3 Message Filtering

Filter messages by content:

```json
{
  "discord": {
    "filters": {
      "ignore_bots": true,
      "ignore_webhooks": true,
      "min_message_length": 3,
      "max_message_length": 2000
    }
  }
}
```

### 5.4 Rate Limiting

Prevent spam and control costs:

```json
{
  "discord": {
    "rate_limits": {
      "messages_per_user_per_minute": 5,
      "messages_per_channel_per_minute": 20
    }
  }
}
```

## Cost Optimization for Discord

### Recommended Channel Setup

**For a typical Discord server**:

```json
{
  "routing": {
    "channel_models": {
      "discord_general": "us.amazon.nova-lite-v1:0",
      "discord_casual": "us.amazon.nova-lite-v1:0",
      "discord_memes": "us.amazon.nova-lite-v1:0",
      "discord_coding": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
      "discord_help": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    }
  }
}
```

**Estimated Monthly Cost**:
- General/Casual/Memes (Nova Lite): ~$2-3
- Coding/Help (Claude Sonnet): ~$3-5
- **Total**: ~$5-8/month

### Cost-Saving Tips

1. **Use Nova Lite by default** - Only use Claude Sonnet for technical channels
2. **Set rate limits** - Prevent excessive usage
3. **Ignore bot messages** - Don't respond to other bots
4. **Monitor usage** - Check CloudWatch metrics weekly

## Troubleshooting

### Bot Not Responding

**Check 1**: Bot is online in Discord
- If offline, check OpenClaw logs for connection errors

**Check 2**: Bot has permissions
- Verify bot can read and send messages in the channel

**Check 3**: Message Content Intent enabled
- Go to Discord Developer Portal → Bot → Privileged Gateway Intents

### Wrong Model Being Used

**Check 1**: Channel ID mapping
- Verify Discord channel ID matches openclaw.json configuration

**Check 2**: Rebuild and deploy
- Changes to openclaw.json require rebuilding the Docker image

**Check 3**: Check CloudWatch logs
- Look for "Processing message from channel" log entries

### High Costs

**Check 1**: Review CloudWatch metrics
```bash
aws cloudwatch get-metric-statistics \
  --namespace OpenClaw/Personal \
  --metric-name ModelUsageCost \
  --dimensions Name=Channel,Value=discord_general \
  --start-time 2025-02-01T00:00:00Z \
  --end-time 2025-02-28T23:59:59Z \
  --period 86400 \
  --statistics Sum
```

**Check 2**: Implement rate limiting
- Add rate limits to openclaw.json

**Check 3**: Switch to Nova Lite
- Change expensive channels to use Nova Lite

### Bot Mentions Not Working

**Check 1**: Mention format
- Use `@BotName` not `@Bot Name` (no spaces)

**Check 2**: Bot nickname
- If bot has a nickname, use the nickname

**Check 3**: Message Content Intent
- Must be enabled in Discord Developer Portal

## Example Discord Server Setup

### Recommended Channel Structure

```
📢 announcements (read-only)
💬 general → Nova Lite
🎮 gaming → Nova Lite
🎨 creative → Nova Lite
💻 coding → Claude Sonnet 4.5
🔧 tech-support → Claude Sonnet 4.5
📚 learning → Claude Sonnet 4.5
```

### Configuration for This Setup

```json
{
  "discord": {
    "channels": {
      "GENERAL_CHANNEL_ID": "discord_general",
      "GAMING_CHANNEL_ID": "discord_general",
      "CREATIVE_CHANNEL_ID": "discord_general",
      "CODING_CHANNEL_ID": "discord_technical",
      "SUPPORT_CHANNEL_ID": "discord_technical",
      "LEARNING_CHANNEL_ID": "discord_technical"
    }
  },
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

## Next Steps

1. ✅ Bot created and invited to server
2. ✅ OpenClaw configured with Discord token
3. ✅ Channel routing configured
4. ✅ Docker image rebuilt and deployed
5. ✅ Integration tested

**You're all set!** Your Discord bot is now powered by OpenClaw Personal with intelligent model routing.

## Additional Resources

- [Discord Developer Portal](https://discord.com/developers/docs)
- [OpenClaw Documentation](https://github.com/openclaw/openclaw)
- [Configuration Guide](CONFIGURATION.md)
- [Cost Optimization Guide](COST-OPTIMIZATION.md)
- [Troubleshooting Guide](TROUBLESHOOTING.md)

## Support

If you encounter issues:

1. Check CloudWatch logs for errors
2. Review [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
3. Verify all configuration steps completed
4. Test with simple messages first

---

**Last Updated**: February 26, 2026  
**Version**: 1.0
