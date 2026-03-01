#!/usr/bin/env python3
"""Test AgentCore Runtime /invocations endpoint"""
import boto3
import json
import uuid

# Get the runtime ARN from CloudFormation outputs
cfn = boto3.client('cloudformation', region_name='us-east-2')
response = cfn.describe_stacks(StackName='openclaw-personal')
runtime_id = None
for output in response['Stacks'][0]['Outputs']:
    if output['OutputKey'] == 'AgentCoreRuntimeId':
        runtime_id = output['OutputValue']
        break

if not runtime_id:
    print("ERROR: Could not find AgentCoreRuntimeId in stack outputs")
    exit(1)

print(f"Runtime ID: {runtime_id}")

# Construct the ARN
account_id = boto3.client('sts').get_caller_identity()['Account']
runtime_arn = f"arn:aws:bedrock-agentcore:us-east-2:{account_id}:runtime/{runtime_id}"
print(f"Runtime ARN: {runtime_arn}")

# Test /invocations endpoint with a test message
client = boto3.client('bedrock-agentcore', region_name='us-east-2')

try:
    # Send a test message
    payload = json.dumps({
        "message": "Hello, this is a test message. Please respond with a greeting.",
        "channel": "discord_general"
    }).encode()
    
    session_id = str(uuid.uuid4())
    print(f"Session ID: {session_id}")
    
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=session_id,
        payload=payload
    )
    
    print(f"\nResponse Content-Type: {response.get('contentType')}")
    
    # Read the response
    if 'response' in response:
        content = b''
        for event in response['response']:
            content += event
        
        full_response = content.decode('utf-8')
        print(f"\nFull Response:\n{full_response}")
        
        # Parse and verify
        try:
            parsed = json.loads(full_response)
            
            # Check for AI-generated reply
            if 'choices' in parsed and len(parsed['choices']) > 0:
                message = parsed['choices'][0].get('message', {}).get('content', '')
                print(f"\n✅ SUCCESS: Received AI response: {message[:100]}...")
                
                # Check for model_used in metadata
                if 'metadata' in parsed and 'model_used' in parsed['metadata']:
                    model_used = parsed['metadata']['model_used']
                    print(f"✅ Model used: {model_used}")
                    exit(0)
                else:
                    print("⚠️  WARNING: No model_used in metadata")
                    exit(0)
            else:
                print(f"\n⚠️  Response format unexpected: {parsed}")
                exit(1)
                
        except json.JSONDecodeError as e:
            print(f"\n❌ FAILED: Response is not valid JSON: {e}")
            exit(1)
    else:
        print("\n❌ FAILED: No response body")
        exit(1)
        
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
