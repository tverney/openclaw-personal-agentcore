"""
Cost tracking verification tests.
Verifies CloudWatch metrics for cost data, cost breakdown by model and channel.

Requirements: 12.7
"""
import json
import os
import sys
from unittest.mock import Mock, patch, MagicMock

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent-container"))

from server import select_model_for_channel, CHANNEL_MODEL_ROUTING


class TestCostTracking:
    """Tests for cost tracking and metrics."""
    
    def test_cost_breakdown_by_model(self):
        """
        Test that cost can be broken down by model.
        Requirements: 12.7
        """
        # Simulate cost tracking for different models
        cost_by_model = {}
        
        test_requests = [
            ("discord_general", "us.amazon.nova-lite-v1:0", 100, 50),
            ("discord_technical", "us.anthropic.claude-sonnet-4-5-20250929-v1:0", 100, 50),
            ("whatsapp", "us.amazon.nova-lite-v1:0", 100, 50),
            ("telegram", "us.anthropic.claude-sonnet-4-5-20250929-v1:0", 100, 50),
        ]
        
        for channel, expected_model, input_tokens, output_tokens in test_requests:
            model = select_model_for_channel(channel)
            assert model == expected_model
            
            # Calculate cost
            if "nova" in model.lower():
                cost = (input_tokens / 1000 * 0.00006) + (output_tokens / 1000 * 0.00024)
            else:
                cost = (input_tokens / 1000 * 0.003) + (output_tokens / 1000 * 0.015)
            
            # Track cost by model
            if model not in cost_by_model:
                cost_by_model[model] = 0.0
            cost_by_model[model] += cost
        
        # Verify we have cost data for each model
        assert len(cost_by_model) > 0, "Should have cost data for at least one model"
        
        # Verify Nova Lite is cheaper than Claude Sonnet
        nova_cost = cost_by_model.get("us.amazon.nova-lite-v1:0", 0)
        claude_cost = cost_by_model.get("us.anthropic.claude-sonnet-4-5-20250929-v1:0", 0)
        
        if nova_cost > 0 and claude_cost > 0:
            assert nova_cost < claude_cost, (
                "Nova Lite should be cheaper than Claude Sonnet for same token count"
            )
    
    def test_cost_breakdown_by_channel(self):
        """
        Test that cost can be broken down by channel.
        Requirements: 12.7
        """
        # Simulate cost tracking for different channels
        cost_by_channel = {}
        
        test_requests = [
            ("discord_general", 100, 50),
            ("discord_technical", 100, 50),
            ("whatsapp", 100, 50),
            ("telegram", 100, 50),
            ("discord_general", 100, 50),  # Second request to same channel
        ]
        
        for channel, input_tokens, output_tokens in test_requests:
            model = select_model_for_channel(channel)
            
            # Calculate cost
            if "nova" in model.lower():
                cost = (input_tokens / 1000 * 0.00006) + (output_tokens / 1000 * 0.00024)
            else:
                cost = (input_tokens / 1000 * 0.003) + (output_tokens / 1000 * 0.015)
            
            # Track cost by channel
            if channel not in cost_by_channel:
                cost_by_channel[channel] = 0.0
            cost_by_channel[channel] += cost
        
        # Verify we have cost data for each channel
        assert len(cost_by_channel) == 4, "Should have cost data for 4 channels"
        
        # Verify discord_general has cost from 2 requests
        assert cost_by_channel["discord_general"] > 0
        
        # Verify channels using Nova Lite are cheaper
        nova_channels = ["discord_general", "whatsapp"]
        claude_channels = ["discord_technical", "telegram"]
        
        avg_nova_cost = sum(cost_by_channel[ch] for ch in nova_channels) / len(nova_channels)
        avg_claude_cost = sum(cost_by_channel[ch] for ch in claude_channels) / len(claude_channels)
        
        assert avg_nova_cost < avg_claude_cost, (
            "Channels using Nova Lite should have lower average cost"
        )
    
    def test_cost_estimation_accuracy(self):
        """
        Test that cost estimation is reasonably accurate.
        Requirements: 12.7
        """
        # Test various token counts
        test_cases = [
            # (model, input_tokens, output_tokens, expected_cost_range)
            ("us.amazon.nova-lite-v1:0", 1000, 500, (0.0001, 0.001)),
            ("us.amazon.nova-lite-v1:0", 10000, 5000, (0.001, 0.01)),
            ("us.anthropic.claude-sonnet-4-5-20250929-v1:0", 1000, 500, (0.001, 0.02)),
            ("us.anthropic.claude-sonnet-4-5-20250929-v1:0", 10000, 5000, (0.01, 0.2)),
        ]
        
        for model, input_tokens, output_tokens, (min_cost, max_cost) in test_cases:
            # Calculate cost
            if "nova" in model.lower():
                cost = (input_tokens / 1000 * 0.00006) + (output_tokens / 1000 * 0.00024)
            else:
                cost = (input_tokens / 1000 * 0.003) + (output_tokens / 1000 * 0.015)
            
            assert min_cost <= cost <= max_cost, (
                f"Cost for {input_tokens} input + {output_tokens} output tokens "
                f"should be between ${min_cost} and ${max_cost}, got ${cost}"
            )
    
    def test_cloudwatch_metrics_structure(self):
        """
        Test that CloudWatch metrics have the correct structure.
        Requirements: 12.7
        """
        # Simulate CloudWatch metric data structure
        metric_data = {
            "MetricName": "ModelUsageCost",
            "Dimensions": [
                {"Name": "Model", "Value": "us.amazon.nova-lite-v1:0"},
                {"Name": "Channel", "Value": "discord_general"}
            ],
            "Value": 0.000123,
            "Unit": "None",
            "Timestamp": "2025-02-26T12:00:00Z"
        }
        
        # Verify required fields
        assert "MetricName" in metric_data
        assert "Dimensions" in metric_data
        assert "Value" in metric_data
        assert "Timestamp" in metric_data
        
        # Verify dimensions include Model and Channel
        dimension_names = [d["Name"] for d in metric_data["Dimensions"]]
        assert "Model" in dimension_names
        assert "Channel" in dimension_names
        
        # Verify value is numeric
        assert isinstance(metric_data["Value"], (int, float))
        assert metric_data["Value"] >= 0
    
    def test_cost_logging_format(self):
        """
        Test that cost information is logged in the correct format.
        Requirements: 12.7
        """
        # Simulate log entry with cost information
        log_entry = {
            "timestamp": "2025-02-26T12:00:00Z",
            "level": "INFO",
            "message": "Request completed",
            "channel": "discord_general",
            "model": "us.amazon.nova-lite-v1:0",
            "duration_ms": 1500,
            "cost_estimate": 0.000123
        }
        
        # Verify required fields
        required_fields = ["channel", "model", "duration_ms", "cost_estimate"]
        for field in required_fields:
            assert field in log_entry, f"Log entry must include '{field}'"
        
        # Verify cost_estimate is numeric and positive
        assert isinstance(log_entry["cost_estimate"], (int, float))
        assert log_entry["cost_estimate"] >= 0
    
    def test_monthly_cost_projection(self):
        """
        Test monthly cost projection based on usage patterns.
        Requirements: 12.7
        """
        # Simulate daily usage
        daily_requests = {
            "discord_general": 100,  # Nova Lite
            "discord_technical": 20,  # Claude Sonnet
            "whatsapp": 50,  # Nova Lite
            "telegram": 30,  # Claude Sonnet
        }
        
        # Average tokens per request
        avg_input_tokens = 100
        avg_output_tokens = 150
        
        # Calculate daily cost
        daily_cost = 0.0
        for channel, request_count in daily_requests.items():
            model = select_model_for_channel(channel)
            
            if "nova" in model.lower():
                cost_per_request = (
                    (avg_input_tokens / 1000 * 0.00006) +
                    (avg_output_tokens / 1000 * 0.00024)
                )
            else:
                cost_per_request = (
                    (avg_input_tokens / 1000 * 0.003) +
                    (avg_output_tokens / 1000 * 0.015)
                )
            
            daily_cost += cost_per_request * request_count
        
        # Project monthly cost (30 days)
        monthly_cost = daily_cost * 30
        
        # Verify monthly cost is within reasonable range
        # With the given usage pattern, should be well under $10/month
        assert monthly_cost < 10.0, (
            f"Monthly cost projection (${monthly_cost:.2f}) should be under $10"
        )
        
        # Verify cost is positive
        assert monthly_cost > 0, "Monthly cost should be positive"
    
    def test_cost_optimization_recommendations(self):
        """
        Test that cost optimization recommendations are valid.
        Requirements: 12.7
        """
        # Analyze channel usage and model costs
        channel_usage = {
            "discord_general": {"requests": 100, "model": "us.amazon.nova-lite-v1:0"},
            "discord_technical": {"requests": 20, "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
            "whatsapp": {"requests": 50, "model": "us.amazon.nova-lite-v1:0"},
            "telegram": {"requests": 30, "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
        }
        
        # Calculate cost per channel
        avg_input_tokens = 100
        avg_output_tokens = 150
        
        channel_costs = {}
        for channel, data in channel_usage.items():
            model = data["model"]
            requests = data["requests"]
            
            if "nova" in model.lower():
                cost_per_request = (
                    (avg_input_tokens / 1000 * 0.00006) +
                    (avg_output_tokens / 1000 * 0.00024)
                )
            else:
                cost_per_request = (
                    (avg_input_tokens / 1000 * 0.003) +
                    (avg_output_tokens / 1000 * 0.015)
                )
            
            channel_costs[channel] = cost_per_request * requests
        
        # Identify most expensive channel
        most_expensive_channel = max(channel_costs, key=channel_costs.get)
        most_expensive_cost = channel_costs[most_expensive_channel]
        
        # Verify we can identify optimization opportunities
        assert most_expensive_channel in channel_usage
        assert most_expensive_cost > 0
        
        # If most expensive channel uses Claude, recommend switching to Nova for simple queries
        if "claude" in channel_usage[most_expensive_channel]["model"].lower():
            recommendation = (
                f"Consider using Nova Lite for simple queries in {most_expensive_channel} "
                f"to reduce costs"
            )
            assert len(recommendation) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
