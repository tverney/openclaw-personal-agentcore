"""
Unit tests for the simplified CloudFormation template.

Tests verify that the template:
- Validates successfully
- Contains required resources (ECR, AgentCore, Budget, SNS, CloudWatch, S3)
- Does NOT contain removed resources (EC2, VPC, networking)
- Has correct configuration for all resources
"""
import json
import subprocess
import yaml
import pytest


def load_template():
    """Load the CloudFormation template."""
    with open("openclaw-simplified.yaml", "r") as f:
        return yaml.safe_load(f)


def test_template_validates_successfully():
    """Test that the CloudFormation template validates successfully."""
    result = subprocess.run(
        [
            "aws", "cloudformation", "validate-template",
            "--template-body", "file://openclaw-simplified.yaml"
        ],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, f"Template validation failed: {result.stderr}"
    
    # Parse the validation output
    validation_output = json.loads(result.stdout)
    assert "Parameters" in validation_output
    assert len(validation_output["Parameters"]) == 3  # AdminEmail, MonthlyBudgetLimit, DefaultModelId


def test_ecr_repository_exists():
    """Test that ECR repository resource exists with correct configuration."""
    template = load_template()
    
    assert "OpenClawECR" in template["Resources"]
    ecr = template["Resources"]["OpenClawECR"]
    
    assert ecr["Type"] == "AWS::ECR::Repository"
    assert ecr["Properties"]["RepositoryName"] == "openclaw-personal"
    assert ecr["Properties"]["ImageScanningConfiguration"]["ScanOnPush"] is True
    assert "LifecyclePolicy" in ecr["Properties"]


def test_agentcore_runtime_exists():
    """Test that AgentCore Runtime resource exists with correct configuration."""
    template = load_template()
    
    assert "AgentCoreRuntime" in template["Resources"]
    runtime = template["Resources"]["AgentCoreRuntime"]
    
    assert runtime["Type"] == "AWS::BedrockAgentCore::Runtime"
    assert "AgentRuntimeArtifact" in runtime["Properties"]
    assert "ContainerConfiguration" in runtime["Properties"]["AgentRuntimeArtifact"]
    assert "RoleArn" in runtime["Properties"]
    assert runtime["Properties"]["NetworkConfiguration"]["NetworkMode"] == "PUBLIC"
    
    # Check environment variables
    env_vars = runtime["Properties"]["Environment"]
    env_names = [var["Name"] for var in env_vars]
    assert "AWS_REGION" in env_names
    assert "BEDROCK_MODEL_ID" in env_names
    assert "SESSION_BACKUP_BUCKET" in env_names


def test_budget_exists_with_correct_limit():
    """Test that AWS Budget resource exists with correct configuration."""
    template = load_template()
    
    assert "MonthlyBudget" in template["Resources"]
    budget = template["Resources"]["MonthlyBudget"]
    
    assert budget["Type"] == "AWS::Budgets::Budget"
    assert budget["Properties"]["Budget"]["TimeUnit"] == "MONTHLY"
    assert budget["Properties"]["Budget"]["BudgetType"] == "COST"
    
    # Check budget limit references parameter
    assert "Ref" in budget["Properties"]["Budget"]["BudgetLimit"]["Amount"]
    assert budget["Properties"]["Budget"]["BudgetLimit"]["Amount"]["Ref"] == "MonthlyBudgetLimit"
    
    # Check notifications
    notifications = budget["Properties"]["NotificationsWithSubscribers"]
    assert len(notifications) == 2
    
    thresholds = [n["Notification"]["Threshold"] for n in notifications]
    assert 80 in thresholds
    assert 100 in thresholds


def test_sns_topic_exists():
    """Test that SNS topic resource exists for budget alerts."""
    template = load_template()
    
    assert "BudgetAlertTopic" in template["Resources"]
    sns = template["Resources"]["BudgetAlertTopic"]
    
    assert sns["Type"] == "AWS::SNS::Topic"
    assert sns["Properties"]["DisplayName"] == "OpenClaw Budget Alerts"
    assert "Subscription" in sns["Properties"]
    
    # Check email subscription
    subscription = sns["Properties"]["Subscription"][0]
    assert subscription["Protocol"] == "email"
    assert "Ref" in subscription["Endpoint"]
    assert subscription["Endpoint"]["Ref"] == "AdminEmail"


def test_cloudwatch_alarm_exists():
    """Test that CloudWatch alarm resource exists for cost monitoring."""
    template = load_template()
    
    assert "CostAlarm" in template["Resources"]
    alarm = template["Resources"]["CostAlarm"]
    
    assert alarm["Type"] == "AWS::CloudWatch::Alarm"
    assert alarm["Properties"]["MetricName"] == "EstimatedCharges"
    assert alarm["Properties"]["Namespace"] == "AWS/Billing"
    assert alarm["Properties"]["ComparisonOperator"] == "GreaterThanThreshold"
    
    # Check threshold references parameter
    assert "Ref" in alarm["Properties"]["Threshold"]
    assert alarm["Properties"]["Threshold"]["Ref"] == "MonthlyBudgetLimit"


def test_no_ec2_resources_exist():
    """Test that no EC2 instance resources exist in the template."""
    template = load_template()
    
    for resource_name, resource in template["Resources"].items():
        assert resource["Type"] != "AWS::EC2::Instance", \
            f"Found EC2 instance resource: {resource_name}"


def test_no_vpc_resources_exist():
    """Test that no VPC resources exist in the template."""
    template = load_template()
    
    vpc_resource_types = [
        "AWS::EC2::VPC",
        "AWS::EC2::Subnet",
        "AWS::EC2::InternetGateway",
        "AWS::EC2::RouteTable",
        "AWS::EC2::Route",
        "AWS::EC2::VPCGatewayAttachment",
        "AWS::EC2::SubnetRouteTableAssociation",
        "AWS::EC2::VPCEndpoint"
    ]
    
    for resource_name, resource in template["Resources"].items():
        assert resource["Type"] not in vpc_resource_types, \
            f"Found VPC resource: {resource_name} ({resource['Type']})"


def test_iam_execution_role_exists():
    """Test that IAM execution role exists with correct policies."""
    template = load_template()
    
    assert "AgentCoreExecutionRole" in template["Resources"]
    role = template["Resources"]["AgentCoreExecutionRole"]
    
    assert role["Type"] == "AWS::IAM::Role"
    assert "Policies" in role["Properties"]
    
    # Check policy names
    policy_names = [p["PolicyName"] for p in role["Properties"]["Policies"]]
    assert "BedrockAccess" in policy_names
    assert "ECRAccess" in policy_names
    assert "CloudWatchLogs" in policy_names
    assert "S3SessionAccess" in policy_names


def test_s3_session_bucket_exists():
    """Test that S3 bucket for session persistence exists."""
    template = load_template()
    
    assert "SessionBackupBucket" in template["Resources"]
    bucket = template["Resources"]["SessionBackupBucket"]
    
    assert bucket["Type"] == "AWS::S3::Bucket"
    assert bucket["Properties"]["VersioningConfiguration"]["Status"] == "Enabled"
    
    # Check lifecycle policy
    lifecycle_rules = bucket["Properties"]["LifecycleConfiguration"]["Rules"]
    assert len(lifecycle_rules) == 1
    assert lifecycle_rules[0]["NoncurrentVersionExpirationInDays"] == 30


def test_s3_permissions_in_iam_role():
    """Test that IAM role has S3 permissions for session bucket."""
    template = load_template()
    
    role = template["Resources"]["AgentCoreExecutionRole"]
    policies = role["Properties"]["Policies"]
    
    # Find S3 policy
    s3_policy = None
    for policy in policies:
        if policy["PolicyName"] == "S3SessionAccess":
            s3_policy = policy
            break
    
    assert s3_policy is not None, "S3SessionAccess policy not found"
    
    statements = s3_policy["PolicyDocument"]["Statement"]
    actions = []
    for statement in statements:
        actions.extend(statement["Action"])
    
    assert "s3:PutObject" in actions
    assert "s3:GetObject" in actions
    assert "s3:ListBucket" in actions


def test_template_parameters():
    """Test that template has required parameters."""
    template = load_template()
    
    assert "Parameters" in template
    params = template["Parameters"]
    
    assert "AdminEmail" in params
    assert "MonthlyBudgetLimit" in params
    assert "DefaultModelId" in params
    
    # Check default values
    assert params["MonthlyBudgetLimit"]["Default"] == 10
    assert params["DefaultModelId"]["Default"] == "us.amazon.nova-lite-v1:0"


def test_template_outputs():
    """Test that template has required outputs."""
    template = load_template()
    
    assert "Outputs" in template
    outputs = template["Outputs"]
    
    assert "ECRRepositoryUri" in outputs
    assert "AgentCoreRuntimeId" in outputs
    assert "BudgetAlertTopicArn" in outputs
    assert "SessionBackupBucketName" in outputs
    assert "SessionBackupBucketArn" in outputs


def test_no_security_groups():
    """Test that no security group resources exist."""
    template = load_template()
    
    for resource_name, resource in template["Resources"].items():
        assert resource["Type"] != "AWS::EC2::SecurityGroup", \
            f"Found security group resource: {resource_name}"


def test_budget_cost_filters():
    """Test that budget has correct cost filters."""
    template = load_template()
    
    budget = template["Resources"]["MonthlyBudget"]
    cost_filters = budget["Properties"]["Budget"]["CostFilters"]
    
    assert "Service" in cost_filters
    services = cost_filters["Service"]
    
    assert "Amazon Bedrock" in services
    assert "Amazon Elastic Container Registry" in services
    assert "Amazon CloudWatch" in services
    assert "Amazon Simple Storage Service" in services


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
