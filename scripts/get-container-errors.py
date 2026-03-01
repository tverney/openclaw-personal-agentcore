#!/usr/bin/env python3
"""
Retrieve error logs from the OpenClaw container by invoking the /errors endpoint.
"""
import boto3
import json
import sys

def get_container_errors(runtime_arn, region='us-east-2'):
    """Invoke the container's /errors endpoint to get recent error logs."""
    try:
        # Use bedrock-agent-runtime client (not bedrock-agentcore)
        client = boto3.client('bedrock-agent-runtime', region_name=region)
        
        # The actual API call for AgentCore is through InvokeAgent
        # But we need to use the HTTP endpoint directly since there's no direct API
        # Let's try a different approach - invoke through the runtime
        
        # Actually, let's just make a direct HTTP request to the container
        # through the AgentCore runtime invocation
        import requests
        
        # We can't directly access the container, so let's use the invoke_agentcore.py approach
        print("Note: Direct container access not available through boto3.")
        print("Use the Discord bot or invoke_agentcore.py to trigger the container,")
        print("then check the response for error information.")
        
        return {
            "message": "Container logs are captured in responses when errors occur",
            "suggestion": "Send a test message through Discord bot and check the error response"
        }
        
    except Exception as e:
        return {"error": str(e), "error_type": type(e).__name__}

if __name__ == '__main__':
    runtime_arn = "arn:aws:bedrock-agentcore:us-east-2:354444542378:runtime/openclawpersonal_runtime-w6iQAuAZYI"
    
    if len(sys.argv) > 1:
        runtime_arn = sys.argv[1]
    
    print("Fetching container error logs...")
    print(f"Runtime: {runtime_arn}")
    print("=" * 60)
    
    result = get_container_errors(runtime_arn)
    
    if "errors" in result:
        print(result["errors"])
    else:
        print(json.dumps(result, indent=2))
