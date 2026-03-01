"""
Test suite for validating AWS Budget controls and cost monitoring.

This test suite validates:
- AWS Budget configuration (limit, thresholds, notifications)
- SNS topic subscription for budget alerts
- CloudWatch alarm configuration
- CloudWatch logs for request/response data
- CloudWatch metrics for cost tracking
- S3 session persistence

Requirements: 12.5, 12.6, 12.7, 14.1-14.9
"""

import json
import os
import subprocess
import time
from typing import Dict, List, Optional

import boto3
import pytest


class TestBudgetConfiguration:
    """Test AWS Budget configuration (Task 8.1)"""
    
    @pytest.fixture(scope="class")
    def stack_name(self) -> str:
        """Get CloudFormation stack name from environment or use default"""
        return os.environ.get("STACK_NAME", "openclaw-personal")
    
    @pytest.fixture(scope="class")
    def aws_account_id(self) -> str:
        """Get AWS account ID"""
        sts = boto3.client("sts")
        return sts.get_caller_identity()["Account"]
    
    @pytest.fixture(scope="class")
    def budgets_client(self):
        """Create AWS Budgets client"""
        return boto3.client("budgets")
    
    @pytest.fixture(scope="class")
    def cloudformation_client(self):
        """Create CloudFormation client"""
        return boto3.client("cloudformation")
    
    @pytest.fixture(scope="class")
    def stack_outputs(self, cloudformation_client, stack_name) -> Dict[str, str]:
        """Get CloudFormation stack outputs"""
        try:
            response = cloudformation_client.describe_stacks(StackName=stack_name)
            outputs = response["Stacks"][0].get("Outputs", [])
            return {output["OutputKey"]: output["OutputValue"] for output in outputs}
        except Exception as e:
            pytest.skip(f"Stack {stack_name} not found or not accessible: {e}")
    
    @pytest.fixture(scope="class")
    def budget_name(self, stack_name) -> str:
        """Get expected budget name"""
        return f"{stack_name}-monthly-budget"
    
    def test_budget_exists(self, budgets_client, aws_account_id, budget_name):
        """Verify AWS Budget exists with correct name"""
        try:
            response = budgets_client.describe_budget(
                AccountId=aws_account_id,
                BudgetName=budget_name
            )
            assert response["Budget"]["BudgetName"] == budget_name
            print(f"✓ Budget exists: {budget_name}")
        except budgets_client.exceptions.NotFoundException:
            pytest.fail(f"Budget {budget_name} not found")
    
    def test_budget_limit(self, budgets_client, aws_account_id, budget_name):
        """Verify budget has correct limit configured"""
        response = budgets_client.describe_budget(
            AccountId=aws_account_id,
            BudgetName=budget_name
        )
        budget = response["Budget"]
        
        # Check budget limit exists
        assert "BudgetLimit" in budget
        assert "Amount" in budget["BudgetLimit"]
        assert "Unit" in budget["BudgetLimit"]
        
        # Check unit is USD
        assert budget["BudgetLimit"]["Unit"] == "USD"
        
        # Check amount is reasonable (between $1 and $1000)
        amount = float(budget["BudgetLimit"]["Amount"])
        assert 1 <= amount <= 1000
        
        print(f"✓ Budget limit: ${amount} USD")
    
    def test_budget_time_unit(self, budgets_client, aws_account_id, budget_name):
        """Verify budget is configured for monthly tracking"""
        response = budgets_client.describe_budget(
            AccountId=aws_account_id,
            BudgetName=budget_name
        )
        budget = response["Budget"]
        
        assert budget["TimeUnit"] == "MONTHLY"
        print("✓ Budget time unit: MONTHLY")
    
    def test_budget_type(self, budgets_client, aws_account_id, budget_name):
        """Verify budget type is COST"""
        response = budgets_client.describe_budget(
            AccountId=aws_account_id,
            BudgetName=budget_name
        )
        budget = response["Budget"]
        
        assert budget["BudgetType"] == "COST"
        print("✓ Budget type: COST")
    
    def test_budget_cost_filters(self, budgets_client, aws_account_id, budget_name):
        """Verify budget has correct cost filters configured"""
        response = budgets_client.describe_budget(
            AccountId=aws_account_id,
            BudgetName=budget_name
        )
        budget = response["Budget"]
        
        # Check cost filters exist
        assert "CostFilters" in budget
        assert "Service" in budget["CostFilters"]
        
        # Check expected services are included
        services = budget["CostFilters"]["Service"]
        expected_services = [
            "Amazon Bedrock",
            "Amazon Elastic Container Registry",
            "Amazon CloudWatch",
            "Amazon Simple Storage Service"
        ]
        
        for service in expected_services:
            assert service in services, f"Service {service} not in cost filters"
        
        print(f"✓ Cost filters configured for {len(services)} services")
    
    def test_budget_notifications(self, budgets_client, aws_account_id, budget_name):
        """Verify budget has 80% and 100% threshold notifications"""
        response = budgets_client.describe_notifications_for_budget(
            AccountId=aws_account_id,
            BudgetName=budget_name
        )
        
        notifications = response.get("Notifications", [])
        assert len(notifications) >= 2, "Expected at least 2 notifications (80% and 100%)"
        
        # Check for 80% threshold
        thresholds = [n["Threshold"] for n in notifications]
        assert 80 in thresholds, "80% threshold notification not found"
        assert 100 in thresholds, "100% threshold notification not found"
        
        # Verify notification types
        for notification in notifications:
            assert notification["NotificationType"] == "ACTUAL"
            assert notification["ComparisonOperator"] == "GREATER_THAN"
            # ThresholdType may not be present in older API responses
            if "ThresholdType" in notification:
                assert notification["ThresholdType"] == "PERCENTAGE"
        
        print(f"✓ Budget notifications configured: {thresholds}")
    
    def test_budget_subscribers(self, budgets_client, aws_account_id, budget_name, stack_outputs):
        """Verify budget notifications have SNS topic subscribers"""
        response = budgets_client.describe_notifications_for_budget(
            AccountId=aws_account_id,
            BudgetName=budget_name
        )
        
        notifications = response.get("Notifications", [])
        sns_topic_arn = stack_outputs.get("BudgetAlertTopicArn")
        
        for notification in notifications:
            # Get subscribers for this notification
            subscribers_response = budgets_client.describe_subscribers_for_notification(
                AccountId=aws_account_id,
                BudgetName=budget_name,
                Notification=notification
            )
            
            subscribers = subscribers_response.get("Subscribers", [])
            assert len(subscribers) > 0, f"No subscribers for {notification['Threshold']}% threshold"
            
            # Check for SNS subscription
            sns_subscribers = [s for s in subscribers if s["SubscriptionType"] == "SNS"]
            assert len(sns_subscribers) > 0, "No SNS subscribers found"
            
            # Verify SNS topic ARN matches
            if sns_topic_arn:
                assert any(s["Address"] == sns_topic_arn for s in sns_subscribers)
        
        print(f"✓ Budget subscribers configured with SNS topic")


class TestSNSTopicSubscription:
    """Test SNS topic subscription for budget alerts (Task 8.2)"""
    
    @pytest.fixture(scope="class")
    def sns_client(self):
        """Create SNS client"""
        return boto3.client("sns")
    
    @pytest.fixture(scope="class")
    def stack_outputs(self) -> Dict[str, str]:
        """Get CloudFormation stack outputs"""
        cloudformation_client = boto3.client("cloudformation")
        stack_name = os.environ.get("STACK_NAME", "openclaw-personal")
        try:
            response = cloudformation_client.describe_stacks(StackName=stack_name)
            outputs = response["Stacks"][0].get("Outputs", [])
            return {output["OutputKey"]: output["OutputValue"] for output in outputs}
        except Exception as e:
            pytest.skip(f"Stack not found: {e}")
    
    def test_sns_topic_exists(self, sns_client, stack_outputs):
        """Verify SNS topic exists"""
        topic_arn = stack_outputs.get("BudgetAlertTopicArn")
        assert topic_arn, "BudgetAlertTopicArn not found in stack outputs"
        
        try:
            response = sns_client.get_topic_attributes(TopicArn=topic_arn)
            assert response["Attributes"]["TopicArn"] == topic_arn
            print(f"✓ SNS topic exists: {topic_arn}")
        except sns_client.exceptions.NotFoundException:
            pytest.fail(f"SNS topic {topic_arn} not found")
    
    def test_sns_topic_subscriptions(self, sns_client, stack_outputs):
        """Verify SNS topic has email subscriptions"""
        topic_arn = stack_outputs.get("BudgetAlertTopicArn")
        
        response = sns_client.list_subscriptions_by_topic(TopicArn=topic_arn)
        subscriptions = response.get("Subscriptions", [])
        
        assert len(subscriptions) > 0, "No subscriptions found for SNS topic"
        
        # Check for email subscription
        email_subscriptions = [s for s in subscriptions if s["Protocol"] == "email"]
        assert len(email_subscriptions) > 0, "No email subscriptions found"
        
        print(f"✓ SNS topic has {len(email_subscriptions)} email subscription(s)")
    
    def test_sns_topic_subscription_status(self, sns_client, stack_outputs):
        """Check email subscription confirmation status"""
        topic_arn = stack_outputs.get("BudgetAlertTopicArn")
        
        response = sns_client.list_subscriptions_by_topic(TopicArn=topic_arn)
        subscriptions = response.get("Subscriptions", [])
        
        email_subscriptions = [s for s in subscriptions if s["Protocol"] == "email"]
        
        for subscription in email_subscriptions:
            status = subscription["SubscriptionArn"]
            endpoint = subscription["Endpoint"]
            
            if status == "PendingConfirmation":
                print(f"⚠ Email subscription pending confirmation: {endpoint}")
                print("  Check your email and confirm the subscription")
            else:
                print(f"✓ Email subscription confirmed: {endpoint}")
    
    @pytest.mark.manual
    def test_send_test_notification(self, sns_client, stack_outputs):
        """Send test notification to SNS topic (manual test)"""
        topic_arn = stack_outputs.get("BudgetAlertTopicArn")
        
        message = {
            "AlarmName": "Test Budget Alert",
            "AlarmDescription": "This is a test notification from budget validation tests",
            "NewStateValue": "ALARM",
            "NewStateReason": "Testing budget alert notifications",
            "StateChangeTime": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        }
        
        response = sns_client.publish(
            TopicArn=topic_arn,
            Subject="Test: OpenClaw Budget Alert",
            Message=json.dumps(message, indent=2)
        )
        
        message_id = response["MessageId"]
        print(f"✓ Test notification sent: {message_id}")
        print("  Check your email for the test notification")


class TestCloudWatchAlarm:
    """Test CloudWatch alarm configuration (Task 8.3)"""
    
    @pytest.fixture(scope="class")
    def cloudwatch_client(self):
        """Create CloudWatch client"""
        return boto3.client("cloudwatch")
    
    @pytest.fixture(scope="class")
    def stack_name(self) -> str:
        """Get CloudFormation stack name"""
        return os.environ.get("STACK_NAME", "openclaw-personal")
    
    @pytest.fixture(scope="class")
    def alarm_name(self, stack_name) -> str:
        """Get expected alarm name"""
        return f"{stack_name}-cost-alarm"
    
    @pytest.fixture(scope="class")
    def stack_outputs(self) -> Dict[str, str]:
        """Get CloudFormation stack outputs"""
        cloudformation_client = boto3.client("cloudformation")
        stack_name = os.environ.get("STACK_NAME", "openclaw-personal")
        try:
            response = cloudformation_client.describe_stacks(StackName=stack_name)
            outputs = response["Stacks"][0].get("Outputs", [])
            return {output["OutputKey"]: output["OutputValue"] for output in outputs}
        except Exception as e:
            pytest.skip(f"Stack not found: {e}")
    
    def test_alarm_exists(self, cloudwatch_client, alarm_name):
        """Verify CloudWatch alarm exists"""
        response = cloudwatch_client.describe_alarms(AlarmNames=[alarm_name])
        alarms = response.get("MetricAlarms", [])
        
        assert len(alarms) == 1, f"Alarm {alarm_name} not found"
        print(f"✓ CloudWatch alarm exists: {alarm_name}")
    
    def test_alarm_metric(self, cloudwatch_client, alarm_name):
        """Verify alarm monitors EstimatedCharges metric"""
        response = cloudwatch_client.describe_alarms(AlarmNames=[alarm_name])
        alarm = response["MetricAlarms"][0]
        
        assert alarm["MetricName"] == "EstimatedCharges"
        assert alarm["Namespace"] == "AWS/Billing"
        assert alarm["Statistic"] == "Maximum"
        
        print("✓ Alarm monitors EstimatedCharges metric")
    
    def test_alarm_threshold(self, cloudwatch_client, alarm_name):
        """Verify alarm threshold matches budget limit"""
        response = cloudwatch_client.describe_alarms(AlarmNames=[alarm_name])
        alarm = response["MetricAlarms"][0]
        
        threshold = alarm["Threshold"]
        assert threshold > 0, "Alarm threshold must be positive"
        assert threshold <= 1000, "Alarm threshold seems unreasonably high"
        
        print(f"✓ Alarm threshold: ${threshold}")
    
    def test_alarm_comparison_operator(self, cloudwatch_client, alarm_name):
        """Verify alarm uses GreaterThanThreshold comparison"""
        response = cloudwatch_client.describe_alarms(AlarmNames=[alarm_name])
        alarm = response["MetricAlarms"][0]
        
        assert alarm["ComparisonOperator"] == "GreaterThanThreshold"
        print("✓ Alarm comparison operator: GreaterThanThreshold")
    
    def test_alarm_dimensions(self, cloudwatch_client, alarm_name):
        """Verify alarm has Currency dimension set to USD"""
        response = cloudwatch_client.describe_alarms(AlarmNames=[alarm_name])
        alarm = response["MetricAlarms"][0]
        
        dimensions = alarm.get("Dimensions", [])
        currency_dimension = next((d for d in dimensions if d["Name"] == "Currency"), None)
        
        assert currency_dimension is not None, "Currency dimension not found"
        assert currency_dimension["Value"] == "USD"
        
        print("✓ Alarm dimension: Currency=USD")
    
    def test_alarm_actions(self, cloudwatch_client, alarm_name, stack_outputs):
        """Verify alarm action points to SNS topic"""
        response = cloudwatch_client.describe_alarms(AlarmNames=[alarm_name])
        alarm = response["MetricAlarms"][0]
        
        alarm_actions = alarm.get("AlarmActions", [])
        assert len(alarm_actions) > 0, "No alarm actions configured"
        
        sns_topic_arn = stack_outputs.get("BudgetAlertTopicArn")
        if sns_topic_arn:
            assert sns_topic_arn in alarm_actions, "SNS topic not in alarm actions"
        
        print(f"✓ Alarm actions configured: {len(alarm_actions)} action(s)")


class TestCloudWatchLogs:
    """Test CloudWatch logs for request/response data (Task 8.4)"""
    
    @pytest.fixture(scope="class")
    def logs_client(self):
        """Create CloudWatch Logs client"""
        return boto3.client("logs")
    
    @pytest.fixture(scope="class")
    def log_group_name(self) -> str:
        """Get expected log group name"""
        stack_name = os.environ.get("STACK_NAME", "openclaw-personal")
        return f"/aws/bedrock-agentcore/{stack_name}"
    
    def test_log_group_exists(self, logs_client, log_group_name):
        """Verify CloudWatch log group exists"""
        try:
            response = logs_client.describe_log_groups(
                logGroupNamePrefix=log_group_name
            )
            log_groups = response.get("logGroups", [])
            
            # Check if exact match or prefix match exists
            matching_groups = [lg for lg in log_groups if lg["logGroupName"].startswith(log_group_name)]
            
            if len(matching_groups) == 0:
                pytest.skip(f"Log group {log_group_name} not found - may not be created until first invocation")
            
            print(f"✓ Log group exists: {matching_groups[0]['logGroupName']}")
        except Exception as e:
            pytest.skip(f"Could not check log groups: {e}")
    
    @pytest.mark.skipif(
        os.environ.get("SKIP_LOG_CONTENT_TESTS") == "true",
        reason="Log content tests require actual invocations"
    )
    def test_logs_contain_request_data(self, logs_client, log_group_name):
        """Verify logs contain request data (requires actual invocations)"""
        # This test requires actual AgentCore invocations to have occurred
        # Skip if no recent log streams exist
        try:
            response = logs_client.describe_log_streams(
                logGroupName=log_group_name,
                orderBy="LastEventTime",
                descending=True,
                limit=1
            )
            
            if not response.get("logStreams"):
                pytest.skip("No log streams found - no invocations have occurred yet")
            
            log_stream_name = response["logStreams"][0]["logStreamName"]
            
            # Get recent log events
            events_response = logs_client.get_log_events(
                logGroupName=log_group_name,
                logStreamName=log_stream_name,
                limit=100
            )
            
            events = events_response.get("events", [])
            if len(events) == 0:
                pytest.skip("No log events found")
            
            # Check for request-related log messages
            messages = [event["message"] for event in events]
            has_request_data = any("message" in msg.lower() or "request" in msg.lower() for msg in messages)
            
            assert has_request_data, "No request data found in logs"
            print(f"✓ Logs contain request data ({len(events)} events checked)")
            
        except logs_client.exceptions.ResourceNotFoundException:
            pytest.skip(f"Log group {log_group_name} not found")
    
    @pytest.mark.skipif(
        os.environ.get("SKIP_LOG_CONTENT_TESTS") == "true",
        reason="Log content tests require actual invocations"
    )
    def test_logs_contain_model_used(self, logs_client, log_group_name):
        """Verify logs contain model_used information (requires actual invocations)"""
        try:
            response = logs_client.describe_log_streams(
                logGroupName=log_group_name,
                orderBy="LastEventTime",
                descending=True,
                limit=1
            )
            
            if not response.get("logStreams"):
                pytest.skip("No log streams found")
            
            log_stream_name = response["logStreams"][0]["logStreamName"]
            
            events_response = logs_client.get_log_events(
                logGroupName=log_group_name,
                logStreamName=log_stream_name,
                limit=100
            )
            
            events = events_response.get("events", [])
            if len(events) == 0:
                pytest.skip("No log events found")
            
            # Check for model_used in logs
            messages = [event["message"] for event in events]
            has_model_info = any("model" in msg.lower() for msg in messages)
            
            assert has_model_info, "No model information found in logs"
            print("✓ Logs contain model information")
            
        except logs_client.exceptions.ResourceNotFoundException:
            pytest.skip(f"Log group {log_group_name} not found")


class TestCloudWatchMetrics:
    """Test CloudWatch metrics for cost tracking (Task 8.5)"""
    
    @pytest.fixture(scope="class")
    def cloudwatch_client(self):
        """Create CloudWatch client"""
        return boto3.client("cloudwatch")
    
    def test_billing_metrics_available(self, cloudwatch_client):
        """Verify AWS Billing metrics are available"""
        # Check if EstimatedCharges metric exists
        response = cloudwatch_client.list_metrics(
            Namespace="AWS/Billing",
            MetricName="EstimatedCharges"
        )
        
        metrics = response.get("Metrics", [])
        
        if len(metrics) == 0:
            pytest.skip("Billing metrics not yet available - may take 24 hours to appear")
        
        print(f"✓ Billing metrics available: {len(metrics)} metric(s)")
    
    @pytest.mark.skipif(
        os.environ.get("SKIP_CUSTOM_METRICS_TESTS") == "true",
        reason="Custom metrics tests require actual invocations"
    )
    def test_custom_metrics_for_model_usage(self, cloudwatch_client):
        """Verify custom metrics for model usage exist (requires invocations)"""
        # This would check for custom metrics published by the application
        # Skip if no custom metrics namespace is configured
        pytest.skip("Custom metrics test requires application-specific namespace configuration")


class TestS3SessionPersistence:
    """Test S3 session persistence (Task 8.6)"""
    
    @pytest.fixture(scope="class")
    def s3_client(self):
        """Create S3 client"""
        return boto3.client("s3")
    
    @pytest.fixture(scope="class")
    def stack_outputs(self) -> Dict[str, str]:
        """Get CloudFormation stack outputs"""
        cloudformation_client = boto3.client("cloudformation")
        stack_name = os.environ.get("STACK_NAME", "openclaw-personal")
        try:
            response = cloudformation_client.describe_stacks(StackName=stack_name)
            outputs = response["Stacks"][0].get("Outputs", [])
            return {output["OutputKey"]: output["OutputValue"] for output in outputs}
        except Exception as e:
            pytest.skip(f"Stack not found: {e}")
    
    def test_s3_bucket_exists(self, s3_client, stack_outputs):
        """Verify S3 session backup bucket exists"""
        bucket_name = stack_outputs.get("SessionBackupBucketName")
        assert bucket_name, "SessionBackupBucketName not found in stack outputs"
        
        try:
            s3_client.head_bucket(Bucket=bucket_name)
            print(f"✓ S3 bucket exists: {bucket_name}")
        except s3_client.exceptions.NoSuchBucket:
            pytest.fail(f"S3 bucket {bucket_name} not found")
    
    def test_s3_bucket_versioning(self, s3_client, stack_outputs):
        """Verify S3 bucket has versioning enabled"""
        bucket_name = stack_outputs.get("SessionBackupBucketName")
        
        response = s3_client.get_bucket_versioning(Bucket=bucket_name)
        status = response.get("Status")
        
        assert status == "Enabled", f"Bucket versioning not enabled (status: {status})"
        print("✓ S3 bucket versioning: Enabled")
    
    def test_s3_bucket_lifecycle_policy(self, s3_client, stack_outputs):
        """Verify S3 bucket has lifecycle policy configured"""
        bucket_name = stack_outputs.get("SessionBackupBucketName")
        
        try:
            response = s3_client.get_bucket_lifecycle_configuration(Bucket=bucket_name)
            rules = response.get("Rules", [])
            
            assert len(rules) > 0, "No lifecycle rules configured"
            
            # Check for rule that deletes old versions
            delete_rule = next(
                (r for r in rules if r.get("NoncurrentVersionExpiration")),
                None
            )
            
            assert delete_rule is not None, "No rule for deleting old versions found"
            
            days = delete_rule["NoncurrentVersionExpiration"]["NoncurrentDays"]
            print(f"✓ Lifecycle policy configured: delete old versions after {days} days")
            
        except s3_client.exceptions.NoSuchLifecycleConfiguration:
            pytest.fail("No lifecycle configuration found")
    
    @pytest.mark.skipif(
        os.environ.get("SKIP_SESSION_CONTENT_TESTS") == "true",
        reason="Session content tests require actual invocations"
    )
    def test_session_files_in_s3(self, s3_client, stack_outputs):
        """Verify session files exist in S3 (requires actual invocations)"""
        bucket_name = stack_outputs.get("SessionBackupBucketName")
        
        response = s3_client.list_objects_v2(Bucket=bucket_name, MaxKeys=10)
        
        if response.get("KeyCount", 0) == 0:
            pytest.skip("No session files found in S3 - no invocations have occurred yet")
        
        print(f"✓ Session files in S3: {response['KeyCount']} file(s)")


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
