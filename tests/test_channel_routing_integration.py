"""
Integration tests for channel-based model routing on deployed AgentCore Runtime.

These tests verify that the deployed AgentCore Runtime correctly routes messages
to different Bedrock models based on the channel field in the request payload.

Requirements tested: 12.4
"""
import json
import unittest
import boto3
import time


class TestChannelRoutingIntegration(unittest.TestCase):
    """Integration tests for channel-based model routing"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        # Get AgentCore Runtime ID from CloudFormation stack
        cfn_client = boto3.client('cloudformation', region_name='us-east-2')
        sts_client = boto3.client('sts', region_name='us-east-2')
        
        try:
            response = cfn_client.describe_stacks(StackName='openclaw-personal')
            outputs = response['Stacks'][0]['Outputs']
            
            cls.runtime_id = None
            for output in outputs:
                if output['OutputKey'] == 'AgentCoreRuntimeId':
                    cls.runtime_id = output['OutputValue']
                    break
            
            if not cls.runtime_id:
                raise ValueError("AgentCore Runtime ID not found in stack outputs")
            
            # Construct the runtime ARN
            account_id = sts_client.get_caller_identity()['Account']
            cls.runtime_arn = f"arn:aws:bedrock-agentcore:us-east-2:{account_id}:runtime/{cls.runtime_id}"
            
            print(f"Testing AgentCore Runtime: {cls.runtime_id}")
            print(f"Runtime ARN: {cls.runtime_arn}")
            
            # Initialize Bedrock AgentCore Runtime client
            cls.agentcore_client = boto3.client('bedrock-agentcore', region_name='us-east-2')
            
        except Exception as e:
            raise RuntimeError(f"Failed to initialize test fixtures: {e}")
    
    def invoke_runtime(self, channel, message="Hello, this is a test message"):
        """
        Helper method to invoke AgentCore Runtime with a message.
        
        Args:
            channel: Channel identifier (e.g., "discord_general", "telegram")
            message: Test message to send
            
        Returns:
            Response dictionary from AgentCore Runtime
        """
        import uuid
        
        payload = {
            "message": message,
            "channel": channel
        }
        
        try:
            session_id = str(uuid.uuid4())
            
            response = self.agentcore_client.invoke_agent_runtime(
                agentRuntimeArn=self.runtime_arn,
                runtimeSessionId=session_id,
                payload=json.dumps(payload).encode()
            )
            
            # Read the response stream
            if 'response' in response:
                content = b''
                for event in response['response']:
                    content += event
                
                full_response = content.decode('utf-8')
                result = json.loads(full_response)
                return result
            else:
                self.fail("No response body from AgentCore Runtime")
            
        except Exception as e:
            self.fail(f"Failed to invoke AgentCore Runtime: {e}")
    
    def test_discord_general_routes_to_nova(self):
        """
        Task 9.1: Test Discord general channel routing
        
        Send message with channel="discord_general"
        Verify model_used is "us.amazon.nova-lite-v1:0"
        """
        print("\n=== Task 9.1: Testing Discord general channel routing ===")
        
        response = self.invoke_runtime(channel="discord_general")
        
        # Verify response has metadata
        self.assertIn("metadata", response, "Response should contain metadata")
        
        # Verify model_used field exists
        self.assertIn("model_used", response["metadata"], 
                     "Response metadata should contain model_used")
        
        # Verify correct model was used
        model_used = response["metadata"]["model_used"]
        expected_model = "us.amazon.nova-lite-v1:0"
        
        self.assertEqual(model_used, expected_model,
                        f"Discord general channel should use {expected_model}, "
                        f"but used {model_used}")
        
        print(f"✓ Discord general channel correctly routed to {model_used}")
    
    def test_discord_technical_routes_to_claude(self):
        """
        Task 9.2: Test Discord technical channel routing
        
        Send message with channel="discord_technical"
        Verify model_used is "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        """
        print("\n=== Task 9.2: Testing Discord technical channel routing ===")
        
        response = self.invoke_runtime(channel="discord_technical")
        
        # Verify response has metadata
        self.assertIn("metadata", response, "Response should contain metadata")
        
        # Verify model_used field exists
        self.assertIn("model_used", response["metadata"],
                     "Response metadata should contain model_used")
        
        # Verify correct model was used
        model_used = response["metadata"]["model_used"]
        expected_model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        
        self.assertEqual(model_used, expected_model,
                        f"Discord technical channel should use {expected_model}, "
                        f"but used {model_used}")
        
        print(f"✓ Discord technical channel correctly routed to {model_used}")
    
    def test_whatsapp_routes_to_nova(self):
        """
        Task 9.3: Test WhatsApp channel routing
        
        Send message with channel="whatsapp"
        Verify model_used is "us.amazon.nova-lite-v1:0"
        """
        print("\n=== Task 9.3: Testing WhatsApp channel routing ===")
        
        response = self.invoke_runtime(channel="whatsapp")
        
        # Verify response has metadata
        self.assertIn("metadata", response, "Response should contain metadata")
        
        # Verify model_used field exists
        self.assertIn("model_used", response["metadata"],
                     "Response metadata should contain model_used")
        
        # Verify correct model was used
        model_used = response["metadata"]["model_used"]
        expected_model = "us.amazon.nova-lite-v1:0"
        
        self.assertEqual(model_used, expected_model,
                        f"WhatsApp channel should use {expected_model}, "
                        f"but used {model_used}")
        
        print(f"✓ WhatsApp channel correctly routed to {model_used}")
    
    def test_telegram_routes_to_claude(self):
        """
        Task 9.4: Test Telegram channel routing
        
        Send message with channel="telegram"
        Verify model_used is "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        """
        print("\n=== Task 9.4: Testing Telegram channel routing ===")
        
        response = self.invoke_runtime(channel="telegram")
        
        # Verify response has metadata
        self.assertIn("metadata", response, "Response should contain metadata")
        
        # Verify model_used field exists
        self.assertIn("model_used", response["metadata"],
                     "Response metadata should contain model_used")
        
        # Verify correct model was used
        model_used = response["metadata"]["model_used"]
        expected_model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        
        self.assertEqual(model_used, expected_model,
                        f"Telegram channel should use {expected_model}, "
                        f"but used {model_used}")
        
        print(f"✓ Telegram channel correctly routed to {model_used}")
    
    def test_unknown_channel_uses_default(self):
        """
        Task 9.5: Test default channel routing
        
        Send message with channel="unknown"
        Verify model_used is default model
        """
        print("\n=== Task 9.5: Testing unknown channel routing ===")
        
        response = self.invoke_runtime(channel="unknown")
        
        # Verify response has metadata
        self.assertIn("metadata", response, "Response should contain metadata")
        
        # Verify model_used field exists
        self.assertIn("model_used", response["metadata"],
                     "Response metadata should contain model_used")
        
        # Verify default model was used
        model_used = response["metadata"]["model_used"]
        expected_model = "us.amazon.nova-lite-v1:0"  # DEFAULT_MODEL
        
        self.assertEqual(model_used, expected_model,
                        f"Unknown channel should use default model {expected_model}, "
                        f"but used {model_used}")
        
        print(f"✓ Unknown channel correctly fell back to default model {model_used}")
    
    def test_missing_channel_uses_default(self):
        """
        Task 9.6: Test missing channel routing
        
        Send message without channel field
        Verify model_used is default model
        """
        print("\n=== Task 9.6: Testing missing channel routing ===")
        
        import uuid
        
        # Send payload without channel field
        payload = {
            "message": "Hello, this is a test message"
        }
        
        try:
            session_id = str(uuid.uuid4())
            
            response = self.agentcore_client.invoke_agent_runtime(
                agentRuntimeArn=self.runtime_arn,
                runtimeSessionId=session_id,
                payload=json.dumps(payload).encode()
            )
            
            # Read the response stream
            if 'response' in response:
                content = b''
                for event in response['response']:
                    content += event
                
                full_response = content.decode('utf-8')
                result = json.loads(full_response)
            else:
                self.fail("No response body from AgentCore Runtime")
            
        except Exception as e:
            self.fail(f"Failed to invoke AgentCore Runtime: {e}")
        
        # Verify response has metadata
        self.assertIn("metadata", result, "Response should contain metadata")
        
        # Verify model_used field exists
        self.assertIn("model_used", result["metadata"],
                     "Response metadata should contain model_used")
        
        # Verify default model was used
        model_used = result["metadata"]["model_used"]
        expected_model = "us.amazon.nova-lite-v1:0"  # DEFAULT_MODEL
        
        self.assertEqual(model_used, expected_model,
                        f"Missing channel should use default model {expected_model}, "
                        f"but used {model_used}")
        
        print(f"✓ Missing channel correctly fell back to default model {model_used}")


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
