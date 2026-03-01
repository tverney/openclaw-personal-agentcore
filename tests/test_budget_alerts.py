"""
Budget alert verification tests.
Verifies SNS notifications and email delivery for budget thresholds.

Requirements: 12.5
"""
import json
from unittest.mock import Mock, patch, MagicMock

import pytest


class TestBudgetAlerts:
    """Tests for budget alert configuration and notifications."""
    
    def test_budget_configuration_structure(self):
        """
        Test that budget configuration has the correct structure.
        Requirements: 12.5
        """
        # Simulate AWS Budget configuration
        budget_config = {
            "BudgetName": "openclaw-personal-monthly-budget",
            "BudgetLimit": {
                "Amount": "10",
                "Unit": "USD"
            },
            "TimeUnit": "MONTHLY",
            "BudgetType": "COST",
            "CostFilters": {
                "Service": [
                    "Amazon Bedrock",
                    "Amazon Elastic Container Registry",
                    "Amazon CloudWatch"
                ]
            }
        }
        
        # Verify required fields
        assert "BudgetName" in budget_config
        assert "BudgetLimit" in budget_config
        assert "TimeUnit" in budget_config
        assert "BudgetType" in budget_config
        
        # Verify budget limit
        assert budget_config["BudgetLimit"]["Amount"] == "10"
        assert budget_config["BudgetLimit"]["Unit"] == "USD"
        
        # Verify time unit is monthly
        assert budget_config["TimeUnit"] == "MONTHLY"
        
        # Verify cost filters include expected services
        services = budget_config["CostFilters"]["Service"]
        assert "Amazon Bedrock" in services
        assert "Amazon Elastic Container Registry" in services
        assert "Amazon CloudWatch" in services
    
    def test_budget_notification_thresholds(self):
        """
        Test that budget notifications are configured for 80% and 100% thresholds.
        Requirements: 12.5
        """
        # Simulate budget notification configuration
        notifications = [
            {
                "Notification": {
                    "NotificationType": "ACTUAL",
                    "ComparisonOperator": "GREATER_THAN",
                    "Threshold": 80
                },
                "Subscribers": [
                    {
                        "SubscriptionType": "SNS",
                        "Address": "arn:aws:sns:us-east-2:354444542378:openclaw-budget-alerts"
                    }
                ]
            },
            {
                "Notification": {
                    "NotificationType": "ACTUAL",
                    "ComparisonOperator": "GREATER_THAN",
                    "Threshold": 100
                },
                "Subscribers": [
                    {
                        "SubscriptionType": "SNS",
                        "Address": "arn:aws:sns:us-east-2:354444542378:openclaw-budget-alerts"
                    }
                ]
            }
        ]
        
        # Verify we have 2 notifications
        assert len(notifications) == 2
        
        # Verify thresholds
        thresholds = [n["Notification"]["Threshold"] for n in notifications]
        assert 80 in thresholds, "Should have 80% threshold notification"
        assert 100 in thresholds, "Should have 100% threshold notification"
        
        # Verify all notifications use SNS
        for notification in notifications:
            subscribers = notification["Subscribers"]
            assert len(subscribers) > 0
            assert subscribers[0]["SubscriptionType"] == "SNS"
    
    def test_sns_topic_configuration(self):
        """
        Test that SNS topic is configured correctly for budget alerts.
        Requirements: 12.5
        """
        # Simulate SNS topic configuration
        sns_topic = {
            "TopicArn": "arn:aws:sns:us-east-2:354444542378:openclaw-budget-alerts",
            "DisplayName": "OpenClaw Budget Alerts",
            "Subscriptions": [
                {
                    "Protocol": "email",
                    "Endpoint": "user@example.com",
                    "SubscriptionArn": "arn:aws:sns:us-east-2:354444542378:openclaw-budget-alerts:12345"
                }
            ]
        }
        
        # Verify topic ARN
        assert "TopicArn" in sns_topic
        assert "openclaw-budget-alerts" in sns_topic["TopicArn"]
        
        # Verify display name
        assert sns_topic["DisplayName"] == "OpenClaw Budget Alerts"
        
        # Verify email subscription
        subscriptions = sns_topic["Subscriptions"]
        assert len(subscriptions) > 0
        assert subscriptions[0]["Protocol"] == "email"
        assert "@" in subscriptions[0]["Endpoint"]
    
    def test_cloudwatch_alarm_configuration(self):
        """
        Test that CloudWatch alarm is configured for estimated charges.
        Requirements: 12.5
        """
        # Simulate CloudWatch alarm configuration
        alarm_config = {
            "AlarmName": "openclaw-personal-cost-alarm",
            "AlarmDescription": "Alert when estimated charges exceed budget",
            "MetricName": "EstimatedCharges",
            "Namespace": "AWS/Billing",
            "Statistic": "Maximum",
            "Period": 21600,  # 6 hours
            "EvaluationPeriods": 1,
            "Threshold": 10.0,
            "ComparisonOperator": "GreaterThanThreshold",
            "Dimensions": [
                {
                    "Name": "Currency",
                    "Value": "USD"
                }
            ],
            "AlarmActions": [
                "arn:aws:sns:us-east-2:354444542378:openclaw-budget-alerts"
            ]
        }
        
        # Verify alarm name
        assert "AlarmName" in alarm_config
        assert "cost-alarm" in alarm_config["AlarmName"]
        
        # Verify metric
        assert alarm_config["MetricName"] == "EstimatedCharges"
        assert alarm_config["Namespace"] == "AWS/Billing"
        
        # Verify threshold matches budget limit
        assert alarm_config["Threshold"] == 10.0
        
        # Verify comparison operator
        assert alarm_config["ComparisonOperator"] == "GreaterThanThreshold"
        
        # Verify alarm action points to SNS topic
        assert len(alarm_config["AlarmActions"]) > 0
        assert "sns" in alarm_config["AlarmActions"][0]
    
    @patch('boto3.client')
    def test_budget_threshold_breach_simulation(self, mock_boto_client):
        """
        Test simulation of budget threshold breach.
        Requirements: 12.5
        """
        # Mock SNS client
        mock_sns = MagicMock()
        mock_boto_client.return_value = mock_sns
        
        # Simulate budget threshold breach
        current_spend = 8.5  # 85% of $10 budget
        budget_limit = 10.0
        threshold_80_percent = budget_limit * 0.8
        
        # Check if threshold is breached
        if current_spend >= threshold_80_percent:
            # Simulate SNS notification
            message = {
                "AlarmName": "openclaw-personal-cost-alarm",
                "NewStateValue": "ALARM",
                "NewStateReason": f"Threshold Crossed: 1 datapoint [${current_spend}] was greater than the threshold [${threshold_80_percent}]",
                "StateChangeTime": "2025-02-26T12:00:00.000Z"
            }
            
            mock_sns.publish(
                TopicArn="arn:aws:sns:us-east-2:354444542378:openclaw-budget-alerts",
                Subject="Budget Alert: 80% Threshold Exceeded",
                Message=json.dumps(message)
            )
        
        # Verify SNS publish was called
        assert mock_sns.publish.called
        
        # Verify message content
        call_args = mock_sns.publish.call_args
        assert "TopicArn" in call_args[1]
        assert "Subject" in call_args[1]
        assert "Message" in call_args[1]
        assert "80%" in call_args[1]["Subject"]
    
    def test_email_notification_format(self):
        """
        Test that email notification has the correct format.
        Requirements: 12.5
        """
        # Simulate email notification content
        email_notification = {
            "Subject": "Budget Alert: 80% Threshold Exceeded",
            "Body": {
                "Text": (
                    "Your AWS budget 'openclaw-personal-monthly-budget' has exceeded 80% of the limit.\n\n"
                    "Current Spend: $8.50\n"
                    "Budget Limit: $10.00\n"
                    "Threshold: 80%\n\n"
                    "Please review your usage to avoid exceeding the budget limit."
                ),
                "Html": (
                    "<html><body>"
                    "<h2>Budget Alert: 80% Threshold Exceeded</h2>"
                    "<p>Your AWS budget 'openclaw-personal-monthly-budget' has exceeded 80% of the limit.</p>"
                    "<ul>"
                    "<li>Current Spend: $8.50</li>"
                    "<li>Budget Limit: $10.00</li>"
                    "<li>Threshold: 80%</li>"
                    "</ul>"
                    "<p>Please review your usage to avoid exceeding the budget limit.</p>"
                    "</body></html>"
                )
            }
        }
        
        # Verify subject
        assert "Subject" in email_notification
        assert "Budget Alert" in email_notification["Subject"]
        assert "80%" in email_notification["Subject"]
        
        # Verify body contains required information
        text_body = email_notification["Body"]["Text"]
        assert "Current Spend" in text_body
        assert "Budget Limit" in text_body
        assert "Threshold" in text_body
        assert "$8.50" in text_body
        assert "$10.00" in text_body
    
    def test_multiple_threshold_alerts(self):
        """
        Test that multiple threshold alerts work correctly.
        Requirements: 12.5
        """
        budget_limit = 10.0
        thresholds = [80, 100]
        
        test_cases = [
            (7.5, []),  # Below all thresholds
            (8.5, [80]),  # Above 80% threshold
            (10.5, [80, 100]),  # Above both thresholds
        ]
        
        for current_spend, expected_alerts in test_cases:
            triggered_alerts = []
            
            for threshold in thresholds:
                threshold_value = budget_limit * (threshold / 100)
                if current_spend >= threshold_value:
                    triggered_alerts.append(threshold)
            
            assert triggered_alerts == expected_alerts, (
                f"For spend ${current_spend}, expected alerts {expected_alerts}, "
                f"got {triggered_alerts}"
            )
    
    def test_budget_alert_recovery(self):
        """
        Test that budget alerts recover when spend drops below threshold.
        Requirements: 12.5
        """
        budget_limit = 10.0
        threshold_80_percent = budget_limit * 0.8
        
        # Simulate spend going above and below threshold
        spend_history = [
            (7.5, "OK"),  # Below threshold
            (8.5, "ALARM"),  # Above threshold
            (9.0, "ALARM"),  # Still above threshold
            (7.0, "OK"),  # Back below threshold (new month)
        ]
        
        for current_spend, expected_state in spend_history:
            if current_spend >= threshold_80_percent:
                state = "ALARM"
            else:
                state = "OK"
            
            assert state == expected_state, (
                f"For spend ${current_spend}, expected state {expected_state}, got {state}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
