#!/usr/bin/env python3
"""
Invoke AgentCore Runtime using boto3
Since AWS CLI doesn't have bedrock-agentcore yet in all versions
"""

import boto3
import json
import sys

def invoke_agentcore(runtime_arn, payload, profile='personal', region='us-east-2'):
    """Invoke AgentCore runtime with payload"""
    
    # Create session
    session = boto3.Session(profile_name=profile, region_name=region)
    
    # Create client
    try:
        client = session.client('bedrock-agentcore')
    except Exception as e:
        print(f"❌ Error creating bedrock-agentcore client: {e}")
        print("\n⚠️  boto3 may not have bedrock-agentcore support yet.")
        print("   Try updating: pip install --upgrade boto3")
        return None
    
    # Invoke runtime
    try:
        print(f"🚀 Invoking AgentCore Runtime...")
        print(f"   ARN: {runtime_arn}")
        print(f"   Payload: {json.dumps(payload, indent=2)}")
        print()
        
        response = client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            payload=json.dumps(payload).encode('utf-8')
        )
        
        print("✅ Runtime invoked successfully!")
        print(f"   Status Code: {response['ResponseMetadata']['HTTPStatusCode']}")
        
        # Read streaming response
        if 'response' in response:
            print("\n📥 Response:")
            response_data = b''
            for chunk in response['response']:
                response_data += chunk
            
            result = json.loads(response_data.decode('utf-8'))
            print(json.dumps(result, indent=2))
            return result
        
        return response
        
    except client.exceptions.ResourceNotFoundException:
        print(f"❌ Runtime not found: {runtime_arn}")
        return None
    except AttributeError as e:
        print(f"❌ Method not available: {e}")
        print("\n⚠️  boto3 doesn't have invoke_agent_runtime method yet.")
        print("   This is expected for very new AWS services.")
        return None
    except Exception as e:
        print(f"❌ Error invoking runtime: {e}")
        print(f"   Error type: {type(e).__name__}")
        return None

def main():
    # Get runtime ARN from CloudFormation
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
            print("❌ Could not find AgentCoreRuntimeId in stack outputs")
            sys.exit(1)
        
        # Construct ARN
        account_id = session.client('sts').get_caller_identity()['Account']
        runtime_arn = f"arn:aws:bedrock-agentcore:us-east-2:{account_id}:runtime/{runtime_id}"
        
        # Test payloads
        test_payloads = [
            {"path": "/ping"},
            {"message": "Hello, OpenClaw!", "channel": "discord_general"},
        ]
        
        for i, payload in enumerate(test_payloads, 1):
            print(f"\n{'='*60}")
            print(f"Test {i}/{len(test_payloads)}")
            print(f"{'='*60}\n")
            
            result = invoke_agentcore(runtime_arn, payload)
            
            if result:
                print("\n✅ Test passed!")
            else:
                print("\n⚠️  Test completed with limitations")
            
            if i < len(test_payloads):
                print("\n" + "-"*60 + "\n")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
