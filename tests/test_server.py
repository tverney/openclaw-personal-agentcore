"""
Unit tests for simplified server.py
"""
import json
import os
import unittest
from unittest.mock import Mock, patch, MagicMock, call
import sys

# Add agent-container directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'agent-container'))

from server import (
    validate_inference_profile_id,
    select_model_for_channel,
    restore_sessions_from_s3,
    sync_sessions_to_s3,
    CHANNEL_MODEL_ROUTING,
    DEFAULT_MODEL,
)


class TestInferenceProfileValidation(unittest.TestCase):
    """Test inference profile ID validation"""
    
    def test_valid_us_prefix(self):
        """Test that US region prefix is valid"""
        self.assertTrue(validate_inference_profile_id("us.amazon.nova-lite-v1:0"))
        self.assertTrue(validate_inference_profile_id("us.anthropic.claude-sonnet-4-5-20250929-v1:0"))
    
    def test_valid_eu_prefix(self):
        """Test that EU region prefix is valid"""
        self.assertTrue(validate_inference_profile_id("eu.amazon.nova-lite-v1:0"))
    
    def test_valid_global_prefix(self):
        """Test that global prefix is valid"""
        self.assertTrue(validate_inference_profile_id("global.anthropic.claude-opus-4-5-20251101-v1:0"))
    
    def test_invalid_direct_model_id(self):
        """Test that direct model IDs without region prefix are invalid"""
        self.assertFalse(validate_inference_profile_id("anthropic.claude-sonnet-4-5-v2:0"))
        self.assertFalse(validate_inference_profile_id("amazon.nova-lite-v1:0"))
    
    def test_invalid_empty_string(self):
        """Test that empty string is invalid"""
        self.assertFalse(validate_inference_profile_id(""))


class TestChannelRouting(unittest.TestCase):
    """Test channel-based model routing"""
    
    def test_discord_general_routes_to_nova(self):
        """Test Discord general channel routes to Nova Lite"""
        model = select_model_for_channel("discord_general")
        self.assertEqual(model, "us.amazon.nova-lite-v1:0")
    
    def test_discord_technical_routes_to_claude(self):
        """Test Discord technical channel routes to Claude Sonnet"""
        model = select_model_for_channel("discord_technical")
        self.assertEqual(model, "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    
    def test_whatsapp_routes_to_nova(self):
        """Test WhatsApp channel routes to Nova Lite"""
        model = select_model_for_channel("whatsapp")
        self.assertEqual(model, "us.amazon.nova-lite-v1:0")
    
    def test_telegram_routes_to_claude(self):
        """Test Telegram channel routes to Claude Sonnet"""
        model = select_model_for_channel("telegram")
        self.assertEqual(model, "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    
    def test_unknown_channel_uses_default(self):
        """Test unknown channel falls back to default model"""
        model = select_model_for_channel("unknown_channel")
        self.assertEqual(model, DEFAULT_MODEL)
    
    def test_default_channel_uses_default(self):
        """Test default channel uses default model"""
        model = select_model_for_channel("default")
        self.assertEqual(model, DEFAULT_MODEL)


class TestS3SessionPersistence(unittest.TestCase):
    """Test S3 session backup and restore"""
    
    @patch.dict(os.environ, {}, clear=True)
    @patch('server.logger')
    def test_restore_without_bucket_env_var(self, mock_logger):
        """Test restore gracefully handles missing bucket environment variable"""
        restore_sessions_from_s3()
        mock_logger.info.assert_called_with("SESSION_BACKUP_BUCKET not set, skipping session restore")
    
    @patch.dict(os.environ, {"SESSION_BACKUP_BUCKET": "test-bucket"})
    @patch('server.boto3.client')
    @patch('server.logger')
    def test_restore_handles_missing_bucket(self, mock_logger, mock_boto_client):
        """Test restore gracefully handles missing S3 bucket (first deployment)"""
        mock_s3 = Mock()
        mock_boto_client.return_value = mock_s3
        mock_s3.head_bucket.side_effect = Exception("NoSuchBucket")
        
        restore_sessions_from_s3()
        
        mock_logger.info.assert_called()
        self.assertTrue(any("not accessible" in str(call) for call in mock_logger.info.call_args_list))
    
    @patch.dict(os.environ, {"SESSION_BACKUP_BUCKET": "test-bucket"})
    @patch('server.boto3.client')
    @patch('server.os.makedirs')
    @patch('server.logger')
    def test_restore_with_no_files(self, mock_logger, mock_makedirs, mock_boto_client):
        """Test restore handles empty bucket"""
        mock_s3 = Mock()
        mock_boto_client.return_value = mock_s3
        mock_s3.head_bucket.return_value = {}
        mock_s3.list_objects_v2.return_value = {}  # No Contents key
        
        restore_sessions_from_s3()
        
        mock_logger.info.assert_called()
        self.assertTrue(any("No session files" in str(call) for call in mock_logger.info.call_args_list))
    
    @patch.dict(os.environ, {"SESSION_BACKUP_BUCKET": "test-bucket"})
    @patch('server.boto3.client')
    @patch('server.os.makedirs')
    @patch('server.logger')
    def test_restore_downloads_files(self, mock_logger, mock_makedirs, mock_boto_client):
        """Test restore downloads session files from S3"""
        mock_s3 = Mock()
        mock_boto_client.return_value = mock_s3
        mock_s3.head_bucket.return_value = {}
        mock_s3.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "sessions/session1.json"},
                {"Key": "sessions/session2.json"},
            ]
        }
        
        restore_sessions_from_s3()
        
        self.assertEqual(mock_s3.download_file.call_count, 2)
        mock_logger.info.assert_called()
        self.assertTrue(any("Successfully restored 2" in str(call) for call in mock_logger.info.call_args_list))
    
    @patch.dict(os.environ, {}, clear=True)
    def test_sync_without_bucket_env_var(self):
        """Test sync gracefully handles missing bucket environment variable"""
        # Should return early without error
        sync_sessions_to_s3()
    
    @patch.dict(os.environ, {"SESSION_BACKUP_BUCKET": "test-bucket"})
    @patch('server.os.path.exists')
    def test_sync_without_sessions_dir(self, mock_exists):
        """Test sync handles missing sessions directory"""
        mock_exists.return_value = False
        # Should return early without error
        sync_sessions_to_s3()
    
    @patch.dict(os.environ, {"SESSION_BACKUP_BUCKET": "test-bucket"})
    @patch('server.boto3.client')
    @patch('server.os.path.exists')
    @patch('server.os.walk')
    @patch('server.logger')
    def test_sync_uploads_files(self, mock_logger, mock_walk, mock_exists, mock_boto_client):
        """Test sync uploads session files to S3"""
        mock_exists.return_value = True
        mock_walk.return_value = [
            ("/tmp/openclaw/sessions", [], ["session1.json", "session2.json"])
        ]
        mock_s3 = Mock()
        mock_boto_client.return_value = mock_s3
        
        sync_sessions_to_s3()
        
        self.assertEqual(mock_s3.upload_file.call_count, 2)
        mock_logger.info.assert_called()
        self.assertTrue(any("Successfully synced 2" in str(call) for call in mock_logger.info.call_args_list))
    
    @patch.dict(os.environ, {"SESSION_BACKUP_BUCKET": "test-bucket"})
    @patch('server.boto3.client')
    @patch('server.os.path.exists')
    @patch('server.logger')
    def test_sync_handles_errors(self, mock_logger, mock_exists, mock_boto_client):
        """Test sync handles S3 errors gracefully"""
        mock_exists.return_value = True
        mock_boto_client.side_effect = Exception("S3 error")
        
        sync_sessions_to_s3()
        
        mock_logger.error.assert_called()
        self.assertTrue(any("Failed to sync" in str(call) for call in mock_logger.error.call_args_list))


class TestHTTPEndpoints(unittest.TestCase):
    """Test HTTP endpoint behavior"""
    
    @patch('server.requests.post')
    def test_ping_endpoint(self, mock_post):
        """Test /ping endpoint returns status ok"""
        from server import AgentCoreHandler
        from io import BytesIO
        
        # Create a mock request
        mock_request = Mock()
        mock_request.makefile = Mock(side_effect=lambda *args, **kwargs: BytesIO(b"GET /ping HTTP/1.1\r\n\r\n"))
        
        # Create handler with proper mocking
        with patch.object(AgentCoreHandler, '__init__', lambda self, request, client_address, server: None):
            handler = AgentCoreHandler(None, None, None)
            handler.path = "/ping"
            handler.wfile = BytesIO()
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            
            handler.do_GET()
            
            handler.send_response.assert_called_with(200)
            # Check that response was written
            self.assertGreater(len(handler.wfile.getvalue()), 0)
            response_data = json.loads(handler.wfile.getvalue())
            self.assertEqual(response_data["status"], "ok")
    
    @patch('server.requests.post')
    def test_invocations_with_valid_payload(self, mock_post):
        """Test /invocations endpoint with valid payload"""
        from server import AgentCoreHandler
        from io import BytesIO
        
        # Mock openclaw response
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello!"}}]
        }
        mock_post.return_value = mock_response
        
        # Create handler with proper mocking
        with patch.object(AgentCoreHandler, '__init__', lambda self, request, client_address, server: None):
            handler = AgentCoreHandler(None, None, None)
            handler.path = "/invocations"
            handler.headers = {"Content-Length": "50"}
            
            payload = json.dumps({"message": "test", "channel": "discord_general"})
            handler.rfile = BytesIO(payload.encode())
            handler.wfile = BytesIO()
            
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            
            handler.do_POST()
            
            handler.send_response.assert_called_with(200)
            # Verify openclaw was called
            mock_post.assert_called()
    
    def test_invocations_with_invalid_json(self):
        """Test /invocations endpoint with invalid JSON"""
        from server import AgentCoreHandler
        from io import BytesIO
        
        # Create handler with proper mocking
        with patch.object(AgentCoreHandler, '__init__', lambda self, request, client_address, server: None):
            handler = AgentCoreHandler(None, None, None)
            handler.path = "/invocations"
            handler.headers = {"Content-Length": "20"}
            handler.rfile = BytesIO(b"invalid json")
            handler.wfile = BytesIO()
            
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            
            handler.do_POST()
            
            # Should send error response
            handler.send_response.assert_called_with(400)
        handler.send_response.assert_called_with(400)


if __name__ == "__main__":
    unittest.main()
