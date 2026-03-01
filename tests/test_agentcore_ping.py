#!/usr/bin/env python3
"""Test AgentCore Runtime /ping endpoint"""
import boto3
import json

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

# Test /ping endpoint by invoking with a ping request
client = boto3.client('bedrock-agentcore', region_name='us-east-2')

try:
    # For /ping, we send a simple request
    payload = json.dumps({"path": "/ping"}).encode()
    
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId='test-ping-session-' + '0' * 20,  # Min 33 chars
        payload=payload
    )
    
    print(f"\nResponse Content-Type: {response.get('contentType')}")
    
    # Read the response - it's a streaming response
    if 'response' in response:
        # The response is an EventStream
        content = b''
        for event in response['response']:
            # Each event is bytes
            content += event
        
        full_response = content.decode('utf-8')
        print(f"\nResponse: {full_response}")
        
        # Parse and verify
        try:
            parsed = json.loads(full_response)
            if parsed.get('status') == 'ok':
                print("\n✅ SUCCESS: /ping endpoint returned {'status': 'ok'}")
                exit(0)
            else:
                print(f"\n❌ FAILED: Expected status='ok', got: {parsed}")
                exit(1)
        except json.JSONDecodeError:
            print(f"\n❌ FAILED: Response is not valid JSON")
            exit(1)
    else:
        print("\n❌ FAILED: No response body")
        exit(1)
        
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    exit(1)
