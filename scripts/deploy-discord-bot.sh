#!/bin/bash
set -e

# Discord Bot Deployment Script for EC2
echo "🤖 Deploying Discord Bot to EC2"
echo "================================"
echo ""

# Configuration
AWS_PROFILE="${AWS_PROFILE:-personal}"
AWS_REGION="${AWS_REGION:-us-east-2}"
INSTANCE_ID="${INSTANCE_ID:-i-0bb87d247a92713e4}"
STACK_NAME="openclaw-personal"

export AWS_PROFILE=$AWS_PROFILE

# Get Runtime ARN from CloudFormation
echo "📋 Getting AgentCore Runtime ARN..."
RUNTIME_ARN=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --profile $AWS_PROFILE \
    --region $AWS_REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`AgentCoreRuntimeId`].OutputValue' \
    --output text)

if [ -z "$RUNTIME_ARN" ]; then
    echo "❌ Could not get Runtime ARN from stack $STACK_NAME"
    exit 1
fi

echo "✅ Runtime ARN: $RUNTIME_ARN"
echo ""

# Load Discord token from .env
if [ -f "agent-container/.env" ]; then
    export $(grep -v '^#' agent-container/.env | grep DISCORD_BOT_TOKEN | xargs)
fi

if [ -z "$DISCORD_BOT_TOKEN" ]; then
    echo "❌ DISCORD_BOT_TOKEN not found in agent-container/.env"
    exit 1
fi

echo "✅ Discord token loaded"
echo ""

# Create deployment package
echo "📦 Creating deployment package..."
cd discord-bot
tar -czf ../discord-bot-deploy.tar.gz \
    bot.js \
    invoke_agentcore.py \
    package.json \
    .env.example \
    README.md
cd ..
echo "✅ Package created"
echo ""

# Upload to EC2 via SSM
echo "📤 Uploading to EC2..."
aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[
        'sudo yum install -y nodejs npm python3-pip',
        'pip3 install boto3',
        'mkdir -p /home/ec2-user/discord-bot',
        'cd /home/ec2-user',
        'echo \"Waiting for file upload...\"'
    ]" \
    --profile $AWS_PROFILE \
    --region $AWS_REGION \
    --output text

echo "⏳ Waiting for package manager installation..."
sleep 10

# Copy files using base64 encoding (workaround for SSM file transfer)
echo "📋 Deploying bot files..."
COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[
        'cd /home/ec2-user/discord-bot',
        'cat > .env << EOF
DISCORD_BOT_TOKEN=$DISCORD_BOT_TOKEN
AGENTCORE_RUNTIME_ARN=$RUNTIME_ARN
AWS_REGION=$AWS_REGION
EOF',
        'cat > package.json << EOF
{
  \"name\": \"openclaw-discord-bot\",
  \"version\": \"1.0.0\",
  \"description\": \"Discord bot for OpenClaw\",
  \"main\": \"bot.js\",
  \"scripts\": {
    \"start\": \"node bot.js\"
  },
  \"dependencies\": {
    \"discord.js\": \"^14.14.1\",
    \"dotenv\": \"^16.4.1\"
  }
}
EOF',
        'npm install',
        'chown -R ec2-user:ec2-user /home/ec2-user/discord-bot',
        'echo \"Installation complete\"'
    ]" \
    --profile $AWS_PROFILE \
    --region $AWS_REGION \
    --query 'Command.CommandId' \
    --output text)

echo "⏳ Installing dependencies..."
sleep 15

# Copy bot.js and invoke_agentcore.py
echo "📝 Copying bot code..."
BOT_JS=$(cat discord-bot/bot.js | base64)
INVOKE_PY=$(cat discord-bot/invoke_agentcore.py | base64)

aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[
        'cd /home/ec2-user/discord-bot',
        'echo \"$BOT_JS\" | base64 -d > bot.js',
        'echo \"$INVOKE_PY\" | base64 -d > invoke_agentcore.py',
        'chmod +x invoke_agentcore.py',
        'chown -R ec2-user:ec2-user /home/ec2-user/discord-bot'
    ]" \
    --profile $AWS_PROFILE \
    --region $AWS_REGION \
    --output text

sleep 5

# Start the bot with PM2
echo "🚀 Starting Discord bot..."
START_CMD=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[
        'cd /home/ec2-user/discord-bot',
        'sudo npm install -g pm2',
        'pm2 delete discord-bot 2>/dev/null || true',
        'pm2 start bot.js --name discord-bot',
        'pm2 save',
        'pm2 startup systemd -u ec2-user --hp /home/ec2-user',
        'pm2 list'
    ]" \
    --profile $AWS_PROFILE \
    --region $AWS_REGION \
    --query 'Command.CommandId' \
    --output text)

echo "⏳ Starting bot..."
sleep 10

# Get status
aws ssm get-command-invocation \
    --command-id $START_CMD \
    --instance-id $INSTANCE_ID \
    --profile $AWS_PROFILE \
    --region $AWS_REGION \
    --query 'StandardOutputContent' \
    --output text

echo ""
echo "✅ Discord bot deployed!"
echo ""
echo "📊 Check status:"
echo "  aws ssm start-session --target $INSTANCE_ID --profile $AWS_PROFILE --region $AWS_REGION"
echo "  Then run: pm2 status"
echo ""
echo "📝 View logs:"
echo "  pm2 logs discord-bot"
echo ""

# Cleanup
rm -f discord-bot-deploy.tar.gz

