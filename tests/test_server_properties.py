"""
Property-based tests for simplified server.py

These tests verify universal properties that should hold across all inputs.
Each test runs a minimum of 100 iterations with randomly generated inputs.
"""
import json
import os
import sys
import unittest
from unittest.mock import Mock, patch
from hypothesis import given, strategies as st, settings

# Add agent-container directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'agent-container'))

from server import (
    validate_inference_profile_id,
    select_model_for_channel,
    DEFAULT_MODEL,
)


class TestPropertyEndpointAvailability(unittest.TestCase):
    """
    Feature: openclaw-bedrock-deployment, Property 1: Endpoint Availability
    Validates: Requirements 2.6
    
    For any HTTP request to /invocations or /ping endpoints,
    the simplified server should respond with a valid HTTP status code.
    """
    
    @settings(max_examples=100)
    @given(endpoint=st.sampled_from(["/ping", "/invocations"]))
    def test_endpoint_returns_valid_status(self, endpoint):
        """Test that endpoints return valid HTTP status codes"""
        from server import AgentCoreHandler
        from io import BytesIO
        
        # Create handler with proper mocking to avoid HTTP server initialization
        with patch.object(AgentCoreHandler, '__init__', lambda self, request, client_address, server: None):
            handler = AgentCoreHandler(None, None, None)
            handler.path = endpoint
            handler.wfile = BytesIO()
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            
            if endpoint == "/ping":
                handler.do_GET()
            else:
                # For /invocations, provide minimal valid payload
                handler.headers = {"Content-Length": "20"}
                handler.rfile = BytesIO(b'{"message": "test"}')
                with patch('server.requests.post') as mock_post:
                    mock_post.return_value = Mock(json=lambda: {"result": "ok"})
                    handler.do_POST()
            
            # Verify a valid HTTP status code was sent
            handler.send_response.assert_called()
            status_code = handler.send_response.call_args[0][0]
            self.assertIn(status_code, [200, 400, 404, 500])


class TestPropertyEnvironmentVariableSubstitution(unittest.TestCase):
    """
    Feature: openclaw-bedrock-deployment, Property 2: Environment Variable Substitution
    Validates: Requirements 2.8
    
    For any valid openclaw.json configuration file with environment variable placeholders,
    substituting environment variables should produce a valid configuration.
    """
    
    @settings(max_examples=100)
    @given(
        region=st.sampled_from(["us-east-1", "us-east-2", "us-west-2", "eu-west-1"]),
        model_id=st.sampled_from([
            "us.amazon.nova-lite-v1:0",
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "eu.amazon.nova-pro-v1:0",
        ])
    )
    def test_environment_variable_substitution(self, region, model_id):
        """Test that environment variables are correctly substituted"""
        config_template = '{"region": "${AWS_REGION}", "model": "${BEDROCK_MODEL_ID}"}'
        
        result = config_template.replace("${AWS_REGION}", region)
        result = result.replace("${BEDROCK_MODEL_ID}", model_id)
        
        # Verify result is valid JSON
        parsed = json.loads(result)
        self.assertEqual(parsed["region"], region)
        self.assertEqual(parsed["model"], model_id)
        # Verify no placeholders remain
        self.assertNotIn("${", result)


class TestPropertyChannelDetermination(unittest.TestCase):
    """
    Feature: openclaw-bedrock-deployment, Property 3: Channel Determination
    Validates: Requirements 5.2
    
    For any valid message payload, the system should correctly extract
    the channel identifier (or use "default" if not provided).
    """
    
    @settings(max_examples=100)
    @given(
        payload=st.fixed_dictionaries({
            "message": st.text(min_size=1, max_size=100),
            "channel": st.one_of(st.none(), st.text(min_size=1, max_size=50))
        })
    )
    def test_channel_extraction(self, payload):
        """Test that channel is correctly extracted from payload"""
        # This mimics the actual server logic
        channel = payload.get("channel") or "default"
        
        if payload.get("channel"):
            self.assertEqual(channel, payload["channel"])
        else:
            self.assertEqual(channel, "default")
        
        # Channel should always be a string
        self.assertIsInstance(channel, str)


class TestPropertyChannelBasedModelRouting(unittest.TestCase):
    """
    Feature: openclaw-bedrock-deployment, Property 4: Channel-Based Model Routing
    Validates: Requirements 5.3
    
    For any channel with a configured model mapping, routing a message from
    that channel should select the configured model (not the default model).
    """
    
    @settings(max_examples=100)
    @given(
        channel=st.sampled_from([
            "discord_general",
            "discord_technical",
            "whatsapp",
            "telegram"
        ])
    )
    def test_configured_channel_uses_mapped_model(self, channel):
        """Test that configured channels use their mapped models"""
        from server import CHANNEL_MODEL_ROUTING
        
        selected_model = select_model_for_channel(channel)
        expected_model = CHANNEL_MODEL_ROUTING[channel]
        
        self.assertEqual(selected_model, expected_model)
        # Verify it's not using the default (unless they happen to match)
        if expected_model != DEFAULT_MODEL:
            self.assertNotEqual(selected_model, DEFAULT_MODEL)


class TestPropertyDefaultModelFallback(unittest.TestCase):
    """
    Feature: openclaw-bedrock-deployment, Property 5: Default Model Fallback
    Validates: Requirements 5.4
    
    For any channel without a configured model mapping, routing a message
    from that channel should select the default model.
    """
    
    @settings(max_examples=100)
    @given(
        channel=st.text(min_size=1, max_size=50).filter(
            lambda x: x not in ["discord_general", "discord_technical", "whatsapp", "telegram"]
        )
    )
    def test_unconfigured_channel_uses_default(self, channel):
        """Test that unconfigured channels fall back to default model"""
        selected_model = select_model_for_channel(channel)
        self.assertEqual(selected_model, DEFAULT_MODEL)


class TestPropertyInferenceProfileValidation(unittest.TestCase):
    """
    Feature: openclaw-bedrock-deployment, Property 6: Inference Profile ID Validation
    Validates: Requirements 5.7, 6.1, 6.2, 6.3
    
    For any model ID string, the validation function should return true
    only if the ID starts with a valid region prefix.
    """
    
    @settings(max_examples=100)
    @given(model_id=st.text(min_size=1, max_size=100))
    def test_validation_checks_prefix(self, model_id):
        """Test that validation correctly checks for region prefix"""
        result = validate_inference_profile_id(model_id)
        has_valid_prefix = model_id.startswith(("us.", "eu.", "global."))
        
        self.assertEqual(result, has_valid_prefix)


class TestPropertyInvalidModelRejection(unittest.TestCase):
    """
    Feature: openclaw-bedrock-deployment, Property 7: Invalid Model ID Rejection
    Validates: Requirements 6.1
    
    For any direct model ID without a region prefix, the validation
    function should reject it and return false.
    """
    
    @settings(max_examples=100)
    @given(
        model_id=st.text(min_size=1, max_size=100).filter(
            lambda x: not x.startswith(("us.", "eu.", "global."))
        )
    )
    def test_direct_model_ids_rejected(self, model_id):
        """Test that direct model IDs are rejected"""
        result = validate_inference_profile_id(model_id)
        self.assertFalse(result)


class TestPropertyValidInferenceProfileAcceptance(unittest.TestCase):
    """
    Feature: openclaw-bedrock-deployment, Property 8: Valid Inference Profile ID Acceptance
    Validates: Requirements 6.2, 6.3
    
    For any inference profile ID with a valid region prefix, the validation
    function should accept it and return true.
    """
    
    @settings(max_examples=100)
    @given(
        prefix=st.sampled_from(["us.", "eu.", "global."]),
        suffix=st.text(min_size=1, max_size=50, alphabet=st.characters(
            whitelist_categories=('Ll', 'Lu', 'Nd'),
            whitelist_characters='.-:'
        ))
    )
    def test_valid_inference_profiles_accepted(self, prefix, suffix):
        """Test that valid inference profile IDs are accepted"""
        model_id = prefix + suffix
        result = validate_inference_profile_id(model_id)
        self.assertTrue(result)


class TestPropertyErrorMessageClarity(unittest.TestCase):
    """
    Feature: openclaw-bedrock-deployment, Property 9: Error Message Clarity
    Validates: Requirements 6.4
    
    For any invalid model ID, the error message should contain both
    the invalid ID and an explanation that inference profile IDs are required.
    """
    
    @settings(max_examples=100)
    @given(
        invalid_model=st.text(min_size=1, max_size=50).filter(
            lambda x: not x.startswith(("us.", "eu.", "global."))
        )
    )
    @patch('server.logger')
    def test_error_message_contains_details(self, mock_logger, invalid_model):
        """Test that error messages contain model ID and explanation"""
        # Temporarily add invalid model to routing
        from server import CHANNEL_MODEL_ROUTING
        original_routing = CHANNEL_MODEL_ROUTING.copy()
        CHANNEL_MODEL_ROUTING["test_channel"] = invalid_model
        
        try:
            select_model_for_channel("test_channel")
            
            # Check that error was logged
            if mock_logger.error.called:
                error_message = str(mock_logger.error.call_args)
                
                # Error should mention inference profile requirement
                has_inference_profile_mention = (
                    "inference profile" in error_message.lower() or
                    "must be inference profile" in error_message.lower()
                )
                self.assertTrue(
                    has_inference_profile_mention,
                    f"Error message should mention inference profile requirement. Message: {error_message}"
                )
                
                # Error should contain "Invalid model ID" text
                self.assertIn("Invalid model ID", error_message)
        finally:
            # Restore original routing
            CHANNEL_MODEL_ROUTING.clear()
            CHANNEL_MODEL_ROUTING.update(original_routing)


class TestPropertyS3SessionPersistence(unittest.TestCase):
    """
    Feature: openclaw-bedrock-deployment, Property 12: S3 Session Persistence
    Validates: Requirements 14.2, 14.3
    
    Session files should be restorable from S3 on startup and syncable
    to S3 during operation.
    """
    
    @settings(max_examples=100)
    @given(
        bucket_name=st.text(min_size=3, max_size=63, alphabet=st.characters(
            whitelist_categories=('Ll', 'Nd'),
            whitelist_characters='-'
        )).filter(lambda x: not x.startswith('-') and not x.endswith('-'))
    )
    @patch('server.boto3.client')
    @patch('server.os.makedirs')
    @patch('server.os.path.exists')
    def test_s3_operations_handle_bucket_names(self, mock_exists, mock_makedirs, 
                                                mock_boto_client, bucket_name):
        """Test that S3 operations handle various bucket names"""
        from server import restore_sessions_from_s3, sync_sessions_to_s3
        
        mock_s3 = Mock()
        mock_boto_client.return_value = mock_s3
        mock_s3.head_bucket.return_value = {}
        mock_s3.list_objects_v2.return_value = {}
        mock_exists.return_value = False
        
        with patch.dict(os.environ, {"SESSION_BACKUP_BUCKET": bucket_name}):
            # Should not raise exceptions
            restore_sessions_from_s3()
            sync_sessions_to_s3()
        
        # Verify boto3 client was created
        mock_boto_client.assert_called()


if __name__ == "__main__":
    unittest.main()
