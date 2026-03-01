# Session Persistence Guide - OpenClaw Personal Edition

Understanding how S3 session persistence works and how to troubleshoot issues.

## Overview

Session persistence ensures your conversation history survives container restarts, updates, and deployments. Without it, every restart would lose all conversation context.

### How It Works

```
Container Startup
    ↓
Restore sessions from S3 → /tmp/openclaw/sessions
    ↓
Start HTTP server
    ↓
Background thread syncs every 5 minutes
    ↓
S3 Bucket (versioned, lifecycle managed)
```

## Architecture

### Components

1. **Local Session Storage**: `/tmp/openclaw/sessions/`
   - Ephemeral storage in container
   - Fast read/write access
   - Lost on container restart

2. **S3 Backup Bucket**: `openclaw-personal-sessions-XXXXX`
   - Persistent storage
   - Versioning enabled
   - Lifecycle policies for cleanup

3. **Sync Mechanism**: Background thread in `server.py`
   - Runs every 5 minutes
   - Uploads changed session files
   - Logs success/failure

### Data Flow

**On Container Startup**:
```python
def restore_sessions_from_s3():
    # 1. List all session files in S3
    # 2. Download each file to /tmp/openclaw/sessions/
    # 3. Log success/failure
```

**During Operation**:
```python
def sync_sessions_to_s3():
    # 1. List all session files in /tmp/openclaw/sessions/
    # 2. Upload each file to S3
    # 3. Run every 5 minutes in background thread
```

## Configuration

### S3 Bucket Setup

Created automatically by CloudFormation:

```yaml
SessionBackupBucket:
  Type: AWS::S3::Bucket
  Properties:
    BucketName: !Sub "${AWS::StackName}-sessions-${AWS::AccountId}"
    VersioningConfiguration:
      Status: Enabled
    LifecycleConfiguration:
      Rules:
        - Id: DeleteOldVersions
          Status: Enabled
          NoncurrentVersionExpiration:
            NoncurrentDays: 30
```

### IAM Permissions

Required permissions for AgentCore execution role:

```yaml
- PolicyName: S3SessionAccess
  PolicyDocument:
    Statement:
      - Effect: Allow
        Action:
          - s3:PutObject
          - s3:GetObject
          - s3:ListBucket
        Resource:
          - !GetAtt SessionBackupBucket.Arn
          - !Sub "${SessionBackupBucket.Arn}/*"
```

### Environment Variables

Set in CloudFormation:

```yaml
Environment:
  - Name: SESSION_BACKUP_BUCKET
    Value: !Ref SessionBackupBucket
```

## Implementation Details

### Restore on Startup

```python
def restore_sessions_from_s3():
    """Restore session files from S3 on container startup."""
    bucket_name = os.environ.get('SESSION_BACKUP_BUCKET')
    if not bucket_name:
        logger.warning("SESSION_BACKUP_BUCKET not set, skipping restore")
        return
    
    try:
        s3 = boto3.client('s3')
        local_dir = '/tmp/openclaw/sessions'
        os.makedirs(local_dir, exist_ok=True)
        
        # List all objects in bucket
        response = s3.list_objects_v2(Bucket=bucket_name, Prefix='sessions/')
        
        if 'Contents' not in response:
            logger.info("No sessions to restore from S3")
            return
        
        # Download each file
        for obj in response['Contents']:
            key = obj['Key']
            local_path = os.path.join(local_dir, os.path.basename(key))
            s3.download_file(bucket_name, key, local_path)
            logger.info(f"Restored session: {key}")
        
        logger.info(f"Restored {len(response['Contents'])} sessions from S3")
    
    except Exception as e:
        logger.error(f"Failed to restore sessions from S3: {e}")
        # Continue anyway - first deployment won't have sessions
```

### Periodic Sync

```python
def sync_sessions_to_s3():
    """Sync session files to S3 every 5 minutes."""
    bucket_name = os.environ.get('SESSION_BACKUP_BUCKET')
    if not bucket_name:
        return
    
    try:
        s3 = boto3.client('s3')
        local_dir = '/tmp/openclaw/sessions'
        
        if not os.path.exists(local_dir):
            return
        
        # Upload each session file
        for filename in os.listdir(local_dir):
            local_path = os.path.join(local_dir, filename)
            s3_key = f'sessions/{filename}'
            
            s3.upload_file(local_path, bucket_name, s3_key)
            logger.debug(f"Synced session: {filename}")
        
        logger.info("S3 session sync completed successfully")
    
    except Exception as e:
        logger.error(f"S3 session sync failed: {e}")

def start_sync_thread():
    """Start background thread for periodic S3 sync."""
    def sync_loop():
        while True:
            time.sleep(300)  # 5 minutes
            sync_sessions_to_s3()
    
    thread = threading.Thread(target=sync_loop, daemon=True)
    thread.start()
    logger.info("Started S3 sync thread (every 5 minutes)")
```

### Main Function Integration

```python
def main():
    # 1. Restore sessions from S3
    restore_sessions_from_s3()
    
    # 2. Start openclaw subprocess
    proc = start_openclaw()
    wait_for_openclaw(STARTUP_TIMEOUT)
    
    # 3. Start S3 sync thread
    start_sync_thread()
    
    # 4. Start HTTP server
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), AgentCoreHandler)
    logger.info("Simplified server listening on port %d", port)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
```

## Cost Analysis

### Storage Costs

**S3 Standard Storage**:
- $0.023 per GB per month
- Typical session file: 10-50 KB
- 100 sessions: ~5 MB = $0.0001/month

**S3 Versioning**:
- Old versions kept for 30 days
- Typical: 2-3 versions per session
- 100 sessions × 3 versions × 50 KB = 15 MB = $0.0003/month

**S3 Requests**:
- PUT requests: $0.005 per 1,000 requests
- GET requests: $0.0004 per 1,000 requests
- Sync every 5 minutes: 288 syncs/day × 30 days = 8,640 syncs/month
- Cost: ~$0.04/month

**Total S3 Cost**: ~$0.03-0.05/month

### Comparison

| Approach | Cost | Pros | Cons |
|----------|------|------|------|
| No persistence | $0 | Free | Lose conversations on restart |
| S3 persistence | $0.03/month | Reliable, versioned | Minimal cost |
| EBS volume | $2.40/month | Fast | 80x more expensive |
| RDS database | $15/month | Queryable | 500x more expensive |

## Monitoring

### CloudWatch Logs

**Successful Restore**:
```
INFO: Restoring sessions from S3
INFO: Restored session: sessions/user123.json
INFO: Restored 5 sessions from S3
```

**Successful Sync**:
```
INFO: S3 session sync completed successfully
```

**Failures**:
```
ERROR: Failed to restore sessions from S3: NoSuchBucket
ERROR: S3 session sync failed: AccessDenied
```

### Verification Commands

**Check S3 bucket contents**:
```bash
aws s3 ls s3://openclaw-personal-sessions-XXXXX/sessions/
```

**Check session file**:
```bash
aws s3 cp s3://openclaw-personal-sessions-XXXXX/sessions/user123.json - | jq .
```

**Check versioning**:
```bash
aws s3api list-object-versions \
  --bucket openclaw-personal-sessions-XXXXX \
  --prefix sessions/user123.json
```

## Troubleshooting

### Sessions Not Persisting

**Symptom**: Conversations lost after container restart

**Check Logs**:
```bash
aws logs filter-log-events \
  --log-group-name /aws/bedrock-agentcore/openclaw-personal \
  --filter-pattern "S3 session"
```

**Common Causes**:

1. **S3 Bucket Doesn't Exist**
   ```
   ERROR: Failed to restore sessions from S3: NoSuchBucket
   ```
   **Solution**: Verify bucket was created by CloudFormation

2. **IAM Permissions Missing**
   ```
   ERROR: S3 session sync failed: AccessDenied
   ```
   **Solution**: Check IAM role has S3 permissions

3. **Sync Thread Not Running**
   - No "Started S3 sync thread" in logs
   **Solution**: Verify `start_sync_thread()` is called in `main()`

### S3 Sync Failures

**Symptom**: "S3 session sync failed" in logs

**Debug**:
```bash
# Check IAM role permissions
aws iam get-role-policy \
  --role-name openclaw-personal-AgentCoreExecutionRole \
  --policy-name S3SessionAccess

# Test S3 access manually
aws s3 ls s3://openclaw-personal-sessions-XXXXX/
```

**Solutions**:

1. **Add Missing Permissions**:
   ```yaml
   - Effect: Allow
     Action:
       - s3:PutObject
       - s3:GetObject
       - s3:ListBucket
     Resource:
       - arn:aws:s3:::openclaw-personal-sessions-XXXXX
       - arn:aws:s3:::openclaw-personal-sessions-XXXXX/*
   ```

2. **Verify Bucket Name**:
   ```bash
   echo $SESSION_BACKUP_BUCKET
   # Should match CloudFormation output
   ```

### Sessions Not Restoring on Startup

**Symptom**: Old conversations not available after restart

**Check**:
```bash
# Verify sessions exist in S3
aws s3 ls s3://openclaw-personal-sessions-XXXXX/sessions/

# Check restore logs
aws logs filter-log-events \
  --log-group-name /aws/bedrock-agentcore/openclaw-personal \
  --filter-pattern "restore_sessions_from_s3"
```

**Common Causes**:

1. **First Deployment**
   - No sessions to restore yet
   - **Solution**: Normal behavior, sessions will sync after first use

2. **Restore Function Not Called**
   - No "Restoring sessions from S3" in logs
   - **Solution**: Verify `restore_sessions_from_s3()` is called before starting server

3. **Wrong Bucket Name**
   - Check environment variable matches actual bucket
   - **Solution**: Update CloudFormation with correct bucket name

## Best Practices

### 1. Monitor Sync Success

Set up CloudWatch alarm for sync failures:

```yaml
SyncFailureAlarm:
  Type: AWS::CloudWatch::Alarm
  Properties:
    AlarmName: openclaw-session-sync-failure
    MetricName: Errors
    Namespace: AWS/Logs
    Statistic: Sum
    Period: 300
    EvaluationPeriods: 1
    Threshold: 1
    ComparisonOperator: GreaterThanThreshold
    Dimensions:
      - Name: LogGroupName
        Value: /aws/bedrock-agentcore/openclaw-personal
```

### 2. Test Restore Regularly

```bash
# Restart container to test restore
aws bedrock-agentcore restart-runtime --runtime-id $RUNTIME_ID

# Check logs for successful restore
aws logs tail /aws/bedrock-agentcore/openclaw-personal --follow
```

### 3. Backup S3 Bucket

Enable S3 replication for disaster recovery:

```yaml
ReplicationConfiguration:
  Role: !GetAtt S3ReplicationRole.Arn
  Rules:
    - Id: ReplicateToBackupRegion
      Status: Enabled
      Destination:
        Bucket: arn:aws:s3:::openclaw-backup-bucket
        ReplicationTime:
          Status: Enabled
          Time:
            Minutes: 15
```

### 4. Adjust Sync Frequency

For high-volume usage, sync more frequently:

```python
# Sync every 2 minutes instead of 5
SYNC_INTERVAL_SECONDS = 120
```

For low-volume usage, sync less frequently:

```python
# Sync every 10 minutes
SYNC_INTERVAL_SECONDS = 600
```

### 5. Clean Up Old Sessions

Implement session cleanup:

```python
def cleanup_old_sessions():
    """Delete sessions older than 30 days."""
    local_dir = '/tmp/openclaw/sessions'
    cutoff = time.time() - (30 * 86400)
    
    for filename in os.listdir(local_dir):
        filepath = os.path.join(local_dir, filename)
        if os.path.getmtime(filepath) < cutoff:
            os.remove(filepath)
            logger.info(f"Deleted old session: {filename}")
```

## Advanced Configuration

### Custom Sync Logic

Sync only changed files:

```python
import hashlib

def get_file_hash(filepath):
    """Calculate MD5 hash of file."""
    with open(filepath, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()

def sync_sessions_to_s3_incremental():
    """Sync only changed session files."""
    s3 = boto3.client('s3')
    bucket_name = os.environ.get('SESSION_BACKUP_BUCKET')
    local_dir = '/tmp/openclaw/sessions'
    
    for filename in os.listdir(local_dir):
        local_path = os.path.join(local_dir, filename)
        s3_key = f'sessions/{filename}'
        
        # Get local file hash
        local_hash = get_file_hash(local_path)
        
        # Get S3 file hash (if exists)
        try:
            response = s3.head_object(Bucket=bucket_name, Key=s3_key)
            s3_hash = response['ETag'].strip('"')
            
            if local_hash == s3_hash:
                continue  # Skip unchanged files
        except:
            pass  # File doesn't exist in S3
        
        # Upload changed file
        s3.upload_file(local_path, bucket_name, s3_key)
        logger.info(f"Synced changed session: {filename}")
```

### Compression

Reduce storage costs with compression:

```python
import gzip

def sync_sessions_to_s3_compressed():
    """Sync sessions with gzip compression."""
    s3 = boto3.client('s3')
    bucket_name = os.environ.get('SESSION_BACKUP_BUCKET')
    local_dir = '/tmp/openclaw/sessions'
    
    for filename in os.listdir(local_dir):
        local_path = os.path.join(local_dir, filename)
        s3_key = f'sessions/{filename}.gz'
        
        # Compress and upload
        with open(local_path, 'rb') as f_in:
            with gzip.open('/tmp/compressed.gz', 'wb') as f_out:
                f_out.writelines(f_in)
        
        s3.upload_file('/tmp/compressed.gz', bucket_name, s3_key)
        os.remove('/tmp/compressed.gz')
```

## Summary

### Key Points

- ✅ Sessions automatically backup to S3 every 5 minutes
- ✅ Sessions restore on container startup
- ✅ Versioning enabled for data protection
- ✅ Lifecycle policies clean up old versions
- ✅ Cost: ~$0.03/month

### Verification Checklist

- [ ] S3 bucket exists
- [ ] IAM role has S3 permissions
- [ ] Environment variable set correctly
- [ ] Restore runs on startup
- [ ] Sync thread starts successfully
- [ ] Sessions appear in S3 after 5 minutes
- [ ] Sessions restore after container restart

### Troubleshooting Steps

1. Check CloudWatch logs for errors
2. Verify S3 bucket exists and has correct permissions
3. Test S3 access with AWS CLI
4. Restart container and verify restore
5. Monitor sync success in logs

## Additional Resources

- [AWS S3 Documentation](https://docs.aws.amazon.com/s3/)
- [S3 Versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html)
- [S3 Lifecycle Policies](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html)
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues
- [DEPLOYMENT.md](DEPLOYMENT.md) - Deployment guide
