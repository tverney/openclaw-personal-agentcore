"""
Simple validation script for CloudFormation template.
Runs basic checks without requiring pytest.
"""
import yaml
import sys


# Add CloudFormation intrinsic function constructors
def cfn_constructor(loader, node):
    """Handle CloudFormation intrinsic functions."""
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)


# Register CloudFormation intrinsic functions
yaml.SafeLoader.add_constructor('!Ref', cfn_constructor)
yaml.SafeLoader.add_constructor('!GetAtt', cfn_constructor)
yaml.SafeLoader.add_constructor('!Sub', cfn_constructor)
yaml.SafeLoader.add_constructor('!Join', cfn_constructor)


def load_template():
    """Load the CloudFormation template."""
    with open("openclaw-simplified.yaml", "r") as f:
        return yaml.safe_load(f)


def validate_template():
    """Run all validation checks."""
    print("Loading CloudFormation template...")
    template = load_template()
    
    errors = []
    
    # Check required resources
    required_resources = {
        "OpenClawECR": "AWS::ECR::Repository",
        "AgentCoreRuntime": "AWS::BedrockAgentCore::Runtime",
        "AgentCoreExecutionRole": "AWS::IAM::Role",
        "MonthlyBudget": "AWS::Budgets::Budget",
        "BudgetAlertTopic": "AWS::SNS::Topic",
        "CostAlarm": "AWS::CloudWatch::Alarm",
        "SessionBackupBucket": "AWS::S3::Bucket"
    }
    
    print("\nChecking required resources...")
    for resource_name, resource_type in required_resources.items():
        if resource_name not in template["Resources"]:
            errors.append(f"Missing resource: {resource_name}")
        elif template["Resources"][resource_name]["Type"] != resource_type:
            errors.append(
                f"Wrong type for {resource_name}: "
                f"expected {resource_type}, "
                f"got {template['Resources'][resource_name]['Type']}"
            )
        else:
            print(f"  ✓ {resource_name} ({resource_type})")
    
    # Check no EC2 resources
    print("\nChecking for removed resources...")
    for resource_name, resource in template["Resources"].items():
        if resource["Type"] == "AWS::EC2::Instance":
            errors.append(f"Found EC2 instance: {resource_name}")
        elif resource["Type"].startswith("AWS::EC2::VPC"):
            errors.append(f"Found VPC resource: {resource_name}")
        elif resource["Type"] == "AWS::EC2::SecurityGroup":
            errors.append(f"Found security group: {resource_name}")
    
    if not errors:
        print("  ✓ No EC2, VPC, or security group resources found")
    
    # Check parameters
    print("\nChecking parameters...")
    required_params = ["AdminEmail", "MonthlyBudgetLimit", "DefaultModelId"]
    for param in required_params:
        if param not in template["Parameters"]:
            errors.append(f"Missing parameter: {param}")
        else:
            print(f"  ✓ {param}")
    
    # Check outputs
    print("\nChecking outputs...")
    required_outputs = [
        "ECRRepositoryUri",
        "AgentCoreRuntimeId",
        "BudgetAlertTopicArn",
        "SessionBackupBucketName",
        "SessionBackupBucketArn"
    ]
    for output in required_outputs:
        if output not in template["Outputs"]:
            errors.append(f"Missing output: {output}")
        else:
            print(f"  ✓ {output}")
    
    # Check IAM role policies
    print("\nChecking IAM role policies...")
    role = template["Resources"]["AgentCoreExecutionRole"]
    policy_names = [p["PolicyName"] for p in role["Properties"]["Policies"]]
    required_policies = ["BedrockAccess", "ECRAccess", "CloudWatchLogs", "S3SessionAccess"]
    for policy in required_policies:
        if policy not in policy_names:
            errors.append(f"Missing IAM policy: {policy}")
        else:
            print(f"  ✓ {policy}")
    
    # Check AgentCore environment variables
    print("\nChecking AgentCore environment variables...")
    runtime = template["Resources"]["AgentCoreRuntime"]
    env_vars = runtime["Properties"]["Environment"]
    env_names = [var["Name"] for var in env_vars]
    required_env = ["AWS_REGION", "BEDROCK_MODEL_ID", "SESSION_BACKUP_BUCKET"]
    for env in required_env:
        if env not in env_names:
            errors.append(f"Missing environment variable: {env}")
        else:
            print(f"  ✓ {env}")
    
    # Check S3 bucket configuration
    print("\nChecking S3 bucket configuration...")
    bucket = template["Resources"]["SessionBackupBucket"]
    if bucket["Properties"]["VersioningConfiguration"]["Status"] != "Enabled":
        errors.append("S3 bucket versioning not enabled")
    else:
        print("  ✓ Versioning enabled")
    
    lifecycle_rules = bucket["Properties"]["LifecycleConfiguration"]["Rules"]
    if len(lifecycle_rules) != 1:
        errors.append("S3 bucket should have exactly 1 lifecycle rule")
    elif lifecycle_rules[0]["NoncurrentVersionExpirationInDays"] != 30:
        errors.append("S3 lifecycle rule should expire old versions after 30 days")
    else:
        print("  ✓ Lifecycle policy configured (30 days)")
    
    # Check budget notifications
    print("\nChecking budget notifications...")
    budget = template["Resources"]["MonthlyBudget"]
    notifications = budget["Properties"]["NotificationsWithSubscribers"]
    thresholds = [n["Notification"]["Threshold"] for n in notifications]
    if 80 not in thresholds:
        errors.append("Missing 80% budget threshold")
    if 100 not in thresholds:
        errors.append("Missing 100% budget threshold")
    if not errors:
        print("  ✓ 80% and 100% thresholds configured")
    
    # Summary
    print("\n" + "="*60)
    if errors:
        print("VALIDATION FAILED")
        print("\nErrors found:")
        for error in errors:
            print(f"  ✗ {error}")
        return False
    else:
        print("VALIDATION PASSED")
        print("\nAll checks passed successfully!")
        return True


if __name__ == "__main__":
    success = validate_template()
    sys.exit(0 if success else 1)
