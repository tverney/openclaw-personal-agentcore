#!/usr/bin/env python3
"""
Test Discord integration with OpenClaw AgentCore Runtime
"""

import boto3
import json
import sys
import os

# Load .env
if os.path.exists('agent-container/.env'):
    with open('agent-container/.env') as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                key, value = line.strip().split('=', 1)
                os.environ[key] = value

def test_discord_message(runtime_arn, message, profile='personal', region='us-east-2'):
    """Test sending a Discord-style message to OpenClaw"""
    
    session = boto3.Session(profile_name=profile, region_name=region)
    client = session.client('bedrock-agentcore')
    
    # Simulate a Discord message
    payload = {
        "message": message,
        "channel": "discord_general",
        "user": "test_user"
    }
    
    print(f"🎮 Testing Discord message...")
    print(f"   Message: {message}")
    print(f"   Channel: discord_general")
    print()
    
    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            payload=json.dumps(payload).encode('utf-8')
        )
        
        print("✅ Runtime invoked successfully!")
        
        # Read response
        if 'response' in response:
            response_data = b''
            for chunk in response['response']:
                response_data += chunk
            
            result = json.loads(response_data.decode('utf-8'))
            print("\n📥 Response:")
            print(json.dumps(result, indent=2))
            
            # Check if it's an error
            if 'error' in result:
                print(f"\n⚠️  Error: {result['error'].get('message', 'Unknown error')}")
                return False
            
            # Check for AI response
            if 'choices' in result and len(result['choices']) > 0:
                ai_response = result['choices'][0].get('message', {}).get('content', '')
                print(f"\n🤖 AI Response: {ai_response}")
                return True
            
            return False
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    # Get runtime ARN
    session = boto3.Session(profile_name='personal', region_name='us-east-2')
    cfn = session.client('cloudformation')
    
    try:
        response = cfn.describe_stacks(StackName='openclaw-personal')
        outputs = response['Stacks'][0]['Outputs']
        
        runtime_id = None
        for output in outputs:
            if output['OutputKey'] == 'AgentCoreRuntimeId':
                runtime_id = output['OutputValue']
                break
        
        if not runtime_id:
            print("❌ Could not find AgentCoreRuntimeId")
            sys.exit(1)
        
        # Construct ARN
        account_id = session.client('sts').get_caller_identity()['Account']
        runtime_arn = f"arn:aws:bedrock-agentcore:us-east-2:{account_id}:runtime/{runtime_id}"
        
        # Test messages
        test_messages = [
            "Hello! Can you hear me?",
            "What is 2+2?",
            "Tell me a joke",
        ]
        
        print(f"🧪 Testing Discord Integration")
        print(f"{'='*60}\n")
        
        success_count = 0
        for i, message in enumerate(test_messages, 1):
            print(f"Test {i}/{len(test_messages)}")
            print(f"{'-'*60}")
            
            if test_discord_message(runtime_arn, message):
                success_count += 1
            
            print()
        
        print(f"{'='*60}")
        print(f"Results: {success_count}/{len(test_messages)} tests passed")
        
        if success_count == 0:
            print("\n⚠️  All tests failed. OpenClaw may not be properly configured.")
            print("   Check CloudWatch logs for details:")
            print(f"   aws logs tail /aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT --follow --profile personal --region us-east-2")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
