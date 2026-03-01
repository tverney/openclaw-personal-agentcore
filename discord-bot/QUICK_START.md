# Discord Bot Quick Start

## 5-Minute Setup

### 1. Create Discord Bot (2 minutes)
1. Go to https://discord.com/developers/applications
2. Click "New Application" → Name it → Create
3. Go to "Bot" tab → Copy the bot token
4. Enable "Message Content Intent" under Privileged Gateway Intents
5. Go to "OAuth2" → "URL Generator"
   - Scopes: `bot`
   - Permissions: `Send Messages`, `Read Messages/View Channels`, `Read Message History`, `Add Reactions`
6. Copy the URL and open it to invite bot to your server

### 2. Deploy with Discord Bot Enabled

```bash
aws cloudformation deploy \
  --template-file openclaw-simplified.yaml \
  --stack-name openclaw-personal \
  --parameter-overrides \
    AdminEmail=your-email@example.com \
    DiscordBotToken=YOUR_BOT_TOKEN \
    EnableDiscordBot=true \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-2
```

### 3. Build and Push Container

```bash
bash scripts/deploy.sh
```

### 4. Test in Discord

```
@YourBot hello!
```

That's it. The bot runs on a t4g.nano EC2 instance (~$3/month) and calls your serverless AgentCore.

## Running Locally Instead

```bash
cd discord-bot
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your token and runtime ARN
python bot.py
```

## Troubleshooting

- **Bot not responding?** Check Message Content Intent is enabled in Discord Developer Portal
- **"ResourceNotFoundException"?** Verify AGENTCORE_RUNTIME_ARN in CloudFormation outputs
- **"AccessDeniedException"?** Check `aws sts get-caller-identity` works
