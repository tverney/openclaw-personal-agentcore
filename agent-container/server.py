"""
OpenClaw Agent Container - Personal Edition

Simplified HTTP server that wraps the openclaw CLI as a subprocess,
providing a REST API for agent invocations via Amazon Bedrock AgentCore.

Environment Variables (required):
    BEDROCK_MODEL_ID  - Inference profile ID (e.g., us.anthropic.claude-*)
    AWS_REGION        - AWS region for Bedrock and S3
    OPENCLAW_AUTH_TOKEN - Authentication token for openclaw gateway

Environment Variables (optional):
    SESSION_BACKUP_BUCKET  - S3 bucket for session persistence
    SYNC_INTERVAL_SECONDS  - S3 sync interval (default: 300)
    PORT                   - HTTP server port (default: 8080)
"""
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import boto3
import requests
from botocore.exceptions import ClientError

# Configure logging with CloudWatch handler
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
    force=True
)
logger = logging.getLogger(__name__)

# Also log to a file for debugging
try:
    file_handler = logging.FileHandler('/tmp/openclaw-errors.log')
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(file_handler)
except (OSError, PermissionError) as e:
    logger.error(f"Failed to create log file handler: {e}")

# Try to add CloudWatch Logs handler
try:
    import watchtower
    cw_handler = watchtower.CloudWatchLogHandler(
        log_group='/aws/bedrock-agentcore/openclaw-personal',
        stream_name='container-logs',
        use_queues=False,
        send_interval=5,
        create_log_group=True
    )
    cw_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(cw_handler)
    logger.info("CloudWatch logging enabled")
except ImportError:
    logger.info("watchtower not installed, CloudWatch logging disabled")
except Exception as e:
    logger.warning(f"CloudWatch logging unavailable: {e}")

# Ensure logs are flushed immediately
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

OPENCLAW_PORT = 18789
OPENCLAW_URL = f"http://localhost:{OPENCLAW_PORT}"
OPENCLAW_AUTH_TOKEN = os.environ.get("OPENCLAW_AUTH_TOKEN")
if not OPENCLAW_AUTH_TOKEN:
    # Fallback for local dev only — production MUST set the env var
    OPENCLAW_AUTH_TOKEN = "openclaw-static-token-12345"
    logger.warning(
        "OPENCLAW_AUTH_TOKEN not set — using insecure default. "
        "Set OPENCLAW_AUTH_TOKEN env var for production use."
    )
STARTUP_TIMEOUT = 30
SESSIONS_DIR = "/root/.openclaw/agents/main/sessions"
WORKSPACE_DIR = "/root/.openclaw/workspace"
CRON_DIR = "/root/.openclaw/agents/main/cron"
OPENCLAW_DIR = "/root/.openclaw"
SYNC_INTERVAL_SECONDS = 300  # 5 minutes
AUTO_APPROVE_INTERVAL = 10  # Check for pairing requests every 10 seconds

# Global reference to Discord bot subprocess
discord_bot_proc = None

# Graceful shutdown flag
_shutdown_requested = threading.Event()

# Get model from environment
DEFAULT_MODEL = os.environ.get(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-3-5-haiku-20241022-v1:0"
)

# Channel-to-model routing configuration - uses DEFAULT_MODEL for all channels
CHANNEL_MODEL_ROUTING = {
    "discord_general": DEFAULT_MODEL,
    "discord_technical": DEFAULT_MODEL,
    "whatsapp": DEFAULT_MODEL,
    "telegram": DEFAULT_MODEL,
}


def validate_inference_profile_id(model_id: str) -> tuple[bool, str]:
    """Validate that model_id is an inference profile ID, not a direct model ID.
    
    Returns:
        (is_valid, error_message)
    """
    if not model_id:
        return False, "Model ID cannot be empty"
    
    if model_id.startswith(("us.", "eu.", "global.")):
        return True, ""
    
    if model_id.startswith(("anthropic.", "amazon.", "meta.", "ai21.")):
        return False, (
            f"Direct model ID detected: '{model_id}'. "
            f"Use inference profile ID instead (e.g., 'us.{model_id}')"
        )
    
    return False, f"Invalid model ID format: '{model_id}'. Expected prefix: us., eu., or global."


# Validate DEFAULT_MODEL at startup — fail fast on misconfiguration
_valid, _err = validate_inference_profile_id(DEFAULT_MODEL)
if not _valid:
    raise ValueError(f"Invalid DEFAULT_MODEL configuration: {_err}")


def select_model_for_channel(channel: str) -> str:
    """Select Bedrock model based on channel configuration."""
    model = CHANNEL_MODEL_ROUTING.get(channel, DEFAULT_MODEL)
    
    is_valid, error_msg = validate_inference_profile_id(model)
    if not is_valid:
        logger.error(
            f"Invalid model for channel '{channel}': {error_msg}. "
            f"Using default model: {DEFAULT_MODEL}"
        )
        return DEFAULT_MODEL
    
    return model


def restore_sessions_from_s3() -> None:
    """Restore openclaw state (sessions + workspace) from S3.
    
    Syncs two prefixes:
      - openclaw-sessions/  → /root/.openclaw/agents/main/sessions/
      - openclaw-workspace/ → /root/.openclaw/workspace/
      - openclaw-cron/      → /root/.openclaw/agents/main/cron/
    
    This preserves conversation history, memory files, and cron jobs across container restarts.
    """
    bucket_name = os.environ.get("SESSION_BACKUP_BUCKET")
    if not bucket_name:
        logger.info("SESSION_BACKUP_BUCKET not set, skipping restore")
        return
    
    try:
        s3_client = boto3.client("s3")
        
        try:
            s3_client.head_bucket(Bucket=bucket_name)
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.warning(f"S3 bucket '{bucket_name}' not accessible: {error_code}")
            return
        
        total_restored = 0
        
        for s3_prefix, local_dir in [
            ("openclaw-sessions/", SESSIONS_DIR),
            ("openclaw-workspace/", WORKSPACE_DIR),
            ("openclaw-cron/", CRON_DIR),
        ]:
            os.makedirs(local_dir, exist_ok=True)
            
            # Use paginator to handle large directories
            paginator = s3_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=s3_prefix)
            
            for page in page_iterator:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("/"):
                        continue
                    
                    filename = key[len(s3_prefix):]
                    if not filename:
                        continue
                    
                    # Prevent path traversal attacks
                    if ".." in filename or filename.startswith("/"):
                        logger.warning(f"Skipping suspicious filename: {filename}")
                        continue
                    
                    local_path = os.path.join(local_dir, filename)
                    
                    # Ensure resolved path stays within expected directory
                    if not os.path.abspath(local_path).startswith(os.path.abspath(local_dir)):
                        logger.warning(f"Path traversal attempt blocked: {filename}")
                        continue
                    
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    
                    for attempt in range(3):
                        try:
                            s3_client.download_file(bucket_name, key, local_path)
                            total_restored += 1
                            break
                        except ClientError as e:
                            if attempt == 2:
                                logger.error(f"Failed to download {key} after 3 attempts: {e}")
                            else:
                                time.sleep(2 ** attempt)
        
        logger.info(f"Restored {total_restored} files from S3")
    
    except ClientError as e:
        logger.error(f"S3 client error during restore: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during S3 restore: {e}", exc_info=True)

GOG_CONFIG_DIR = "/root/.config/gogcli"
GOG_S3_PREFIX = "gog-credentials/"


def restore_gog_credentials_from_s3() -> None:
    """Restore GOG (Google Workspace CLI) credentials from S3.

    Downloads:
      - gog-credentials/credentials.json → GOG OAuth client credentials
      - gog-credentials/token.json       → GOG refresh token

    After downloading, imports the token into GOG's file-based keyring
    so the CLI can authenticate without a browser.
    """
    bucket_name = os.environ.get("SESSION_BACKUP_BUCKET")
    gog_account = os.environ.get("GOG_ACCOUNT")
    if not bucket_name:
        return
    if not gog_account:
        logger.info("GOG_ACCOUNT not set, skipping GOG credential restore")
        return

    try:
        s3_client = boto3.client("s3")
        os.makedirs(GOG_CONFIG_DIR, exist_ok=True)

        # Download credentials.json (OAuth client ID/secret)
        creds_key = f"{GOG_S3_PREFIX}credentials.json"
        creds_path = os.path.join(GOG_CONFIG_DIR, "credentials.json")
        try:
            s3_client.download_file(bucket_name, creds_key, creds_path)
            logger.info("Downloaded GOG credentials.json from S3")
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                logger.info("No GOG credentials.json in S3, skipping")
                return
            raise

        # Download token.json (refresh token export)
        token_key = f"{GOG_S3_PREFIX}token.json"
        token_path = "/tmp/gog-token-import.json"
        try:
            s3_client.download_file(bucket_name, token_key, token_path)
            logger.info("Downloaded GOG token.json from S3")
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                logger.info("No GOG token in S3, skipping token import")
                return
            raise

        # Configure GOG to use file-based keyring (no macOS Keychain in container)
        # GOG_KEYRING_PASSWORD is REQUIRED for file keyring in non-interactive context
        if not os.environ.get("GOG_KEYRING_PASSWORD"):
            os.environ["GOG_KEYRING_PASSWORD"] = "openclaw-gog-keyring-2024"
            logger.info("Set GOG_KEYRING_PASSWORD for file-based keyring")

        result = subprocess.run(
            ["gog", "auth", "keyring", "file"],
            capture_output=True, text=True, timeout=10,
        )
        logger.info(f"GOG keyring file: rc={result.returncode} stdout={result.stdout.strip()} stderr={result.stderr.strip()}")

        # The credentials.json from S3 is already in gog's internal format
        # (flat {client_id, client_secret}), NOT Google's download format
        # ({installed: {client_id, ...}}). So we just place it in gog's config dir.
        logger.info(f"GOG credentials.json placed at {creds_path}")

        # Import the refresh token
        result = subprocess.run(
            ["gog", "auth", "tokens", "import", token_path],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "GOG_KEYRING_PASSWORD": os.environ.get("GOG_KEYRING_PASSWORD", "openclaw-gog-keyring-2024")},
        )
        logger.info(f"GOG tokens import: rc={result.returncode} stdout={result.stdout.strip()} stderr={result.stderr.strip()}")
        if result.returncode == 0:
            logger.info(f"GOG credentials restored for {gog_account}")
        else:
            logger.warning(f"GOG token import failed: {result.stderr}")

        # Verify credentials were stored
        verify = subprocess.run(
            ["gog", "auth", "list"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "GOG_KEYRING_PASSWORD": os.environ.get("GOG_KEYRING_PASSWORD", "openclaw-gog-keyring-2024")},
        )
        logger.info(f"GOG auth list after restore: {verify.stdout.strip()}")

        # Set default account
        os.environ["GOG_ACCOUNT"] = gog_account

        # Cleanup temp file
        try:
            os.remove(token_path)
        except OSError:
            pass

    except ClientError as e:
        logger.error(f"S3 error restoring GOG credentials: {e}")
    except Exception as e:
        logger.error(f"Failed to restore GOG credentials: {e}", exc_info=True)


def restore_system_crontab_from_s3() -> None:
    """Restore system crontab from S3.
    
    Openclaw writes cron jobs via the system crontab command, not to files
    in the cron directory. We back up the raw crontab content to S3 and
    restore it on container restart so scheduled jobs survive.
    """
    bucket_name = os.environ.get("SESSION_BACKUP_BUCKET")
    if not bucket_name:
        return
    
    try:
        s3_client = boto3.client("s3")
        crontab_key = "openclaw-system-crontab/crontab.txt"
        
        try:
            response = s3_client.get_object(Bucket=bucket_name, Key=crontab_key)
            crontab_content = response["Body"].read().decode("utf-8")
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.info("No saved crontab in S3, skipping restore")
                return
            raise
        
        if not crontab_content.strip():
            logger.info("Saved crontab is empty, skipping restore")
            return
        
        # Write crontab content to a temp file and load it
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".crontab", delete=False) as f:
            f.write(crontab_content)
            tmp_path = f.name
        
        try:
            result = subprocess.run(
                ["crontab", tmp_path],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                logger.info(f"Restored system crontab from S3 ({len(crontab_content)} bytes)")
            else:
                logger.warning(f"Failed to restore crontab: {result.stderr}")
        finally:
            os.remove(tmp_path)
    
    except ClientError as e:
        logger.error(f"S3 error restoring crontab: {e}")
    except Exception as e:
        logger.error(f"Failed to restore system crontab: {e}", exc_info=True)


def sync_system_crontab_to_s3() -> None:
    """Back up the current system crontab to S3."""
    bucket_name = os.environ.get("SESSION_BACKUP_BUCKET")
    if not bucket_name:
        return
    
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True, text=True, timeout=10,
        )
        
        # crontab -l returns exit code 1 with "no crontab for root" when empty
        if result.returncode != 0 and "no crontab" in result.stderr.lower():
            return
        
        crontab_content = result.stdout.strip()
        if not crontab_content:
            return
        
        s3_client = boto3.client("s3")
        s3_client.put_object(
            Bucket=bucket_name,
            Key="openclaw-system-crontab/crontab.txt",
            Body=crontab_content.encode("utf-8"),
        )
        logger.info(f"Backed up system crontab to S3 ({len(crontab_content)} bytes)")
    
    except Exception as e:
        logger.error(f"Failed to back up system crontab: {e}")


# ---------------------------------------------------------------------------
# EventBridge Scheduler helpers — create/delete schedules that wake AgentCore
# at the right time to execute cron jobs reliably.
# ---------------------------------------------------------------------------

def _sanitize_schedule_name(name: str) -> str:
    """Convert a cron job name to a valid EventBridge schedule name."""
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    prefix = "openclaw-cron-"
    # EventBridge schedule names max 64 chars
    return (prefix + sanitized)[:64]


def _cron_to_eventbridge(cron_expr: str) -> str:
    """Convert a standard 5-field cron expression to EventBridge schedule expression.
    
    Standard cron: minute hour day-of-month month day-of-week (0-6, 0=Sun)
    EventBridge:   cron(minute hour day-of-month month day-of-week year)
                   day-of-week: SUN-SAT or 1-7 (1=SUN)
    """
    # Map standard cron day-of-week (0=Sun) to EventBridge names
    DOW_MAP = {"0": "SUN", "1": "MON", "2": "TUE", "3": "WED",
               "4": "THU", "5": "FRI", "6": "SAT", "7": "SUN"}
    
    parts = cron_expr.strip().split()
    if len(parts) == 5:
        dom, dow = parts[2], parts[4]
        
        # Convert numeric day-of-week to EventBridge names
        if dow != "*" and dow != "?":
            # Handle ranges like 1-5, lists like 0,6
            converted = []
            for segment in dow.split(","):
                if "-" in segment:
                    start, end = segment.split("-", 1)
                    converted.append(f"{DOW_MAP.get(start, start)}-{DOW_MAP.get(end, end)}")
                else:
                    converted.append(DOW_MAP.get(segment, segment))
            parts[4] = ",".join(converted)
            dow = parts[4]
        
        # EventBridge requires '?' in either day-of-month or day-of-week
        if dom != "*" and dow not in ("*", "?"):
            parts[4] = "?"
        elif dom == "*" and dow in ("*",):
            parts[4] = "?"
        elif dom != "*":
            parts[4] = "?"
        else:
            parts[2] = "?"
        
        return f"cron({parts[0]} {parts[1]} {parts[2]} {parts[3]} {parts[4]} *)"
    elif len(parts) == 6:
        return f"cron({cron_expr})"
    else:
        logger.warning(f"Unexpected cron format ({len(parts)} fields): {cron_expr}")
        return f"cron({cron_expr})"


_cached_runtime_arn: str | None = None


def _discover_runtime_arn() -> str:
    """Discover our own AgentCore runtime ARN.
    
    Since CloudFormation can't self-reference the runtime resource in its
    own environment variables, we find it by listing runtimes via the
    control-plane API and matching on the name pattern.
    Result is cached for the container's lifetime.
    """
    global _cached_runtime_arn
    if _cached_runtime_arn:
        return _cached_runtime_arn
    
    region = os.environ.get("AWS_REGION", "us-east-2")
    
    try:
        client = boto3.client("bedrock-agentcore-control", region_name=region)
        # list_agent_runtimes may not support pagination in all SDK versions
        try:
            paginator = client.get_paginator("list_agent_runtimes")
            pages = paginator.paginate()
        except Exception:
            # Fallback: call directly without paginator
            logger.info("Paginator not available, calling list_agent_runtimes directly")
            resp = client.list_agent_runtimes()
            pages = [resp]
        
        for page in pages:
            for runtime in page.get("agentRuntimes", page.get("agentRuntimeSummaries", [])):
                name = runtime.get("agentRuntimeName", "")
                logger.info(f"Runtime discovery: found '{name}'")
                if "openclawpersonal" in name.lower().replace("-", "").replace("_", ""):
                    _cached_runtime_arn = runtime["agentRuntimeArn"]
                    logger.info(f"Discovered runtime ARN: {_cached_runtime_arn}")
                    return _cached_runtime_arn
        logger.warning("Could not find openclaw runtime in account")
        return ""
    except Exception as e:
        logger.error(f"Failed to discover runtime ARN: {e}", exc_info=True)
        return ""


def _create_eventbridge_schedule(
    job_name: str,
    cron_expr: str,
    cron_message: str,
    tz: str = "UTC",
) -> str:
    """Create an EventBridge Scheduler schedule that invokes the cron Lambda.
    Returns 'created', 'updated', or an error description string."""
    schedule_name = _sanitize_schedule_name(job_name)
    scheduler_role_arn = os.environ.get("CRON_SCHEDULER_ROLE_ARN", "")
    lambda_arn = os.environ.get("CRON_INVOKER_FUNCTION_ARN", "")
    
    if not lambda_arn or not scheduler_role_arn:
        msg = (
            f"missing env: CRON_INVOKER_FUNCTION_ARN={'set' if lambda_arn else 'MISSING'}, "
            f"CRON_SCHEDULER_ROLE_ARN={'set' if scheduler_role_arn else 'MISSING'}"
        )
        logger.warning(f"EventBridge skipped: {msg}")
        return msg
    
    # Discover our runtime ARN so the Lambda knows where to forward
    runtime_arn = _discover_runtime_arn()
    if not runtime_arn:
        logger.warning("EventBridge cron scheduling skipped: could not discover runtime ARN")
        return "runtime ARN discovery failed"
    
    logger.info(
        f"Creating EventBridge schedule: lambda={lambda_arn}, "
        f"role_arn={scheduler_role_arn}, cron={cron_expr}, tz={tz}"
    )
    
    try:
        scheduler = boto3.client("scheduler", region_name=os.environ.get("AWS_REGION", "us-east-2"))
        schedule_expr = _cron_to_eventbridge(cron_expr)
        
        payload = json.dumps({
            "action": "run-cron-job",
            "name": job_name,
            "cron_message": cron_message,
            "runtime_arn": runtime_arn,
        })
        
        scheduler.create_schedule(
            Name=schedule_name,
            GroupName="openclaw-cron",
            ScheduleExpression=schedule_expr,
            ScheduleExpressionTimezone=tz,
            FlexibleTimeWindow={"Mode": "OFF"},
            Target={
                "Arn": lambda_arn,
                "RoleArn": scheduler_role_arn,
                "Input": payload,
            },
            State="ENABLED",
            Description=f"OpenClaw cron: {job_name}",
        )
        logger.info(
            f"Created EventBridge schedule '{schedule_name}' "
            f"({schedule_expr}, tz={tz})"
        )
        return "created"
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConflictException":
            # Schedule already exists — update it
            try:
                scheduler.update_schedule(
                    Name=schedule_name,
                    GroupName="openclaw-cron",
                    ScheduleExpression=schedule_expr,
                    ScheduleExpressionTimezone=tz,
                    FlexibleTimeWindow={"Mode": "OFF"},
                    Target={
                        "Arn": lambda_arn,
                        "RoleArn": scheduler_role_arn,
                        "Input": payload,
                    },
                    State="ENABLED",
                    Description=f"OpenClaw cron: {job_name}",
                )
                logger.info(f"Updated existing EventBridge schedule '{schedule_name}'")
                return "updated"
            except Exception as ue:
                logger.error(f"Failed to update EventBridge schedule: {ue}")
                return f"update failed: {ue}"
        logger.error(f"Failed to create EventBridge schedule: {e}")
        return f"create failed: {e}"
    except Exception as e:
        logger.error(f"EventBridge schedule creation error: {e}", exc_info=True)
        return f"error: {e}"


def _delete_eventbridge_schedule(job_id: str) -> bool:
    """Delete an EventBridge Scheduler schedule for a cron job."""
    schedule_name = _sanitize_schedule_name(job_id)
    try:
        scheduler = boto3.client("scheduler")
        scheduler.delete_schedule(
            Name=schedule_name,
            GroupName="openclaw-cron",
        )
        logger.info(f"Deleted EventBridge schedule '{schedule_name}'")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.info(f"EventBridge schedule '{schedule_name}' not found (already deleted)")
            return True
        logger.error(f"Failed to delete EventBridge schedule: {e}")
        return False
    except Exception as e:
        logger.error(f"EventBridge schedule deletion error: {e}", exc_info=True)
        return False


def sync_sessions_to_s3() -> None:
    """Sync openclaw state (sessions + workspace + cron) to S3.
    Uploads session files, workspace files (memory, identity, etc.),
    and cron jobs so they persist across container restarts.
    
    For MEMORY.md specifically, we only upload if the local version is
    LARGER than the S3 version, to avoid overwriting richer persisted
    content with openclaw's default/truncated version.
    """
    bucket_name = os.environ.get("SESSION_BACKUP_BUCKET")
    if not bucket_name:
        return
    
    try:
        s3_client = boto3.client("s3")
        synced_count = 0
        
        # Get the size of MEMORY.md on S3 for comparison
        s3_memory_size = 0
        try:
            resp = s3_client.head_object(
                Bucket=bucket_name,
                Key="openclaw-workspace/MEMORY.md"
            )
            s3_memory_size = resp.get("ContentLength", 0)
        except ClientError as e:
            if e.response['Error']['Code'] != '404':
                logger.warning(f"Error checking MEMORY.md in S3: {e}")
        
        for local_dir, s3_prefix in [
            (SESSIONS_DIR, "openclaw-sessions/"),
            (WORKSPACE_DIR, "openclaw-workspace/"),
            (CRON_DIR, "openclaw-cron/"),
        ]:
            if not os.path.exists(local_dir):
                continue
            
            for root, dirs, files in os.walk(local_dir):
                for file in files:
                    if file.endswith(".lock"):
                        continue
                    local_path = os.path.join(root, file)
                    relative_path = os.path.relpath(local_path, local_dir)
                    s3_key = f"{s3_prefix}{relative_path}"
                    
                    # For MEMORY.md: only upload if local is larger than S3
                    if file == "MEMORY.md" and s3_prefix == "openclaw-workspace/":
                        local_size = os.path.getsize(local_path)
                        if local_size <= s3_memory_size:
                            logger.info(
                                f"Skipping MEMORY.md upload: local={local_size}b <= S3={s3_memory_size}b"
                            )
                            continue
                        else:
                            logger.info(
                                f"Uploading MEMORY.md: local={local_size}b > S3={s3_memory_size}b"
                            )
                    
                    try:
                        s3_client.upload_file(local_path, bucket_name, s3_key)
                        synced_count += 1
                    except ClientError as upload_error:
                        logger.error(f"Failed to upload {s3_key}: {upload_error}")
        
        if synced_count > 0:
            logger.info(f"Synced {synced_count} files to S3")
        
        # Also back up system crontab (openclaw writes cron jobs here)
        sync_system_crontab_to_s3()
    
    except ClientError as e:
        logger.error(f"S3 client error during sync: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during S3 sync: {e}", exc_info=True)


def sync_sessions_async() -> None:
    """Sync sessions to S3 in a background thread (non-blocking)."""
    threading.Thread(target=sync_sessions_to_s3, daemon=True).start()


def load_memory_from_s3() -> str:
    """Load MEMORY.md content directly from S3 for injection into messages.
    
    Since openclaw caches workspace files in memory and overwrites them on
    startup, we can't rely on the filesystem. Instead, we read MEMORY.md
    directly from S3 and inject it as context in each request.
    
    Returns the memory content string, or empty string if unavailable.
    """
    bucket_name = os.environ.get("SESSION_BACKUP_BUCKET")
    if not bucket_name:
        return ""
    
    try:
        s3_client = boto3.client("s3")
        response = s3_client.get_object(
            Bucket=bucket_name,
            Key="openclaw-workspace/MEMORY.md"
        )
        content = response["Body"].read().decode("utf-8")
        logger.info(f"Loaded MEMORY.md from S3 ({len(content)} bytes)")
        return content
    except Exception as e:
        logger.warning(f"Failed to load MEMORY.md from S3: {e}")
        return ""


def start_sync_thread() -> None:
    """Start background thread for periodic S3 sync."""
    def sync_loop():
        while not _shutdown_requested.is_set():
            _shutdown_requested.wait(timeout=SYNC_INTERVAL_SECONDS)
            if _shutdown_requested.is_set():
                break
            try:
                sync_sessions_to_s3()
            except Exception as e:
                logger.error(f"Error in periodic S3 sync: {e}", exc_info=True)
        logger.info("S3 sync thread stopped")
    
    thread = threading.Thread(target=sync_loop, daemon=True, name="S3SyncThread")
    thread.start()
    logger.info(f"Started S3 sync thread (interval: {SYNC_INTERVAL_SECONDS}s)")


# Discord pairing is handled by separate Discord bot
# See discord-bot/ directory for Discord integration


def start_openclaw() -> subprocess.Popen:
    """Start openclaw subprocess with environment configuration."""
    config_src = "/app/openclaw.json"
    config_dir = "/root/.openclaw"
    config_dst = f"{config_dir}/openclaw.json"
    
    # Create config directory
    os.makedirs(config_dir, exist_ok=True)
    
    # Read config file and substitute environment variables
    with open(config_src) as f:
        config_content = f.read()
    
    # Substitute environment variables in the format ${VAR_NAME}
    import re
    def replace_env_var(match):
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))
    
    config_content = re.sub(r'\$\{([^}]+)\}', replace_env_var, config_content)
    
    with open(config_dst, "w") as f:
        f.write(config_content)
    
    env = os.environ.copy()
    env["OPENCLAW_SKIP_ONBOARDING"] = "1"
    env["OPENCLAW_CONFIG_PATH"] = config_dst
    
    proc = subprocess.Popen(
        ["openclaw", "gateway", "run", "--allow-unconfigured"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    
    # Write openclaw output to a log file for debugging
    openclaw_log_path = "/tmp/openclaw-subprocess.log"
    
    def log_openclaw_output():
        with open(openclaw_log_path, "w") as logf:
            for line in proc.stdout:
                decoded = line.decode().rstrip()
                logf.write(decoded + "\n")
                logf.flush()
                # Log all openclaw output, including errors
                if "error" in decoded.lower() or "exception" in decoded.lower() or "failed" in decoded.lower():
                    logger.error(f"[openclaw] {decoded}")
                else:
                    logger.info(f"[openclaw] {decoded}")
    
    threading.Thread(target=log_openclaw_output, daemon=True).start()
    
    return proc


def wait_for_openclaw(timeout: int = STARTUP_TIMEOUT) -> None:
    """Wait for openclaw to be ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{OPENCLAW_URL}/health",
                headers={"Authorization": f"Bearer {OPENCLAW_AUTH_TOKEN}"},
                timeout=2,
            )
            if r.status_code == 200:
                logger.info("openclaw ready (status=%d)", r.status_code)
                return
        except requests.exceptions.ConnectionError:
            pass
        except Exception as e:
            # Try alternative health check
            try:
                r = requests.post(
                    f"{OPENCLAW_URL}/v1/chat/completions",
                    json={
                        "model": "probe",
                        "messages": [],
                        "user": "healthcheck"
                    },
                    headers={"Authorization": f"Bearer {OPENCLAW_AUTH_TOKEN}"},
                    timeout=2,
                )
                if r.status_code < 500:
                    logger.info("openclaw ready (status=%d)", r.status_code)
                    return
            except:
                pass
        time.sleep(1)
    
    logger.info("openclaw may not be fully ready, but continuing...")
    # Don't exit - let the service start anyway


class AgentCoreHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info(format, *args)
    
    def do_GET(self):
        if self.path == "/ping" or self.path == "/health":
            # Check if openclaw is responsive
            try:
                r = requests.get(
                    f"{OPENCLAW_URL}/health",
                    headers={"Authorization": f"Bearer {OPENCLAW_AUTH_TOKEN}"},
                    timeout=2,
                )
                openclaw_status = "healthy" if r.status_code == 200 else f"unhealthy (status={r.status_code})"
            except Exception as e:
                openclaw_status = f"unreachable ({str(e)})"
            
            self._respond(200, {
                "status": "ok",
                "openclaw": openclaw_status,
                "model": DEFAULT_MODEL,
                "discord_bot": "running" if discord_bot_proc and (hasattr(discord_bot_proc, 'is_alive') and discord_bot_proc.is_alive() or hasattr(discord_bot_proc, 'poll') and discord_bot_proc.poll() is None) else "dead",
                "deployment_version": os.environ.get("DEPLOYMENT_VERSION", "unknown")
            })
        elif self.path == "/errors":
            # Return recent errors from log file
            try:
                errors = ""
                try:
                    with open('/tmp/openclaw-errors.log', 'r') as f:
                        errors = ''.join(f.readlines()[-50:])
                except FileNotFoundError:
                    errors = "No error log"
                
                bot_log = ""
                try:
                    with open('/tmp/discord-bot.log', 'r') as f:
                        bot_log = ''.join(f.readlines()[-50:])
                except FileNotFoundError:
                    bot_log = "No discord bot log"
                
                self._respond(200, {"errors": errors, "discord_bot_log": bot_log})
            except Exception as e:
                self._respond(500, {"error": str(e)})
        else:
            self._respond(404, {"error": "not found"})
    
    def do_POST(self):
        if self.path != "/invocations":
            self._respond(404, {"error": "not found"})
            return
        
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid json"})
            return
        
        message = payload.get("message", "")
        channel = payload.get("channel", "default")
        history = payload.get("history")  # Optional conversation history from Discord threads
        
        # Support status check via invocations
        if payload.get("action") == "status":
            bot_alive = discord_bot_proc and hasattr(discord_bot_proc, 'is_alive') and discord_bot_proc.is_alive()
            self._respond(200, {
                "status": "ok",
                "discord_bot": "running" if bot_alive else "dead",
                "deployment_version": os.environ.get("DEPLOYMENT_VERSION", "unknown")
            })
            return
        
        # Diagnostic action — returns debug info about each subsystem
        if payload.get("action") == "diagnose":
            diag = {"deployment_version": os.environ.get("DEPLOYMENT_VERSION", "unknown")}
            # Check openclaw health
            try:
                r = requests.get(
                    f"{OPENCLAW_URL}/health",
                    headers={"Authorization": f"Bearer {OPENCLAW_AUTH_TOKEN}"},
                    timeout=5,
                )
                diag["openclaw_health"] = f"status={r.status_code}"
            except Exception as e:
                diag["openclaw_health"] = f"error: {e}"
            # Check S3 access
            try:
                s3 = boto3.client("s3")
                bucket = os.environ.get("SESSION_BACKUP_BUCKET", "")
                if bucket:
                    s3.head_bucket(Bucket=bucket)
                    diag["s3_bucket"] = f"ok ({bucket})"
                else:
                    diag["s3_bucket"] = "not configured"
            except Exception as e:
                diag["s3_bucket"] = f"error: {e}"
            # Check memory load
            try:
                mem = load_memory_from_s3()
                diag["memory_load"] = f"ok ({len(mem)} bytes)"
            except Exception as e:
                diag["memory_load"] = f"error: {e}"
            # Check openclaw chat endpoint
            try:
                r = requests.post(
                    f"{OPENCLAW_URL}/v1/chat/completions",
                    json={"model": DEFAULT_MODEL, "messages": [{"role": "user", "content": "ping"}]},
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {OPENCLAW_AUTH_TOKEN}"},
                    timeout=30,
                )
                diag["openclaw_chat"] = f"status={r.status_code}, body={r.text[:300]}"
            except Exception as e:
                diag["openclaw_chat"] = f"error: {e}"
            # Check error log
            try:
                with open('/tmp/openclaw-errors.log', 'r') as f:
                    diag["error_log"] = ''.join(f.readlines()[-20:])
            except FileNotFoundError:
                diag["error_log"] = "no log file"
            # Check skills directory
            try:
                import glob
                diag["skills_dir"] = str(glob.glob("/app/skills/**/*", recursive=True))
            except Exception as e:
                diag["skills_dir"] = f"error: {e}"
            # Check resolved openclaw.json (after env var substitution)
            try:
                with open('/root/.openclaw/openclaw.json', 'r') as f:
                    resolved = f.read()
                diag["resolved_config"] = resolved[:1000]
            except Exception as e:
                diag["resolved_config"] = f"error: {e}"
            # Check openclaw process status
            try:
                import subprocess as sp
                ps = sp.run(["ps", "aux"], capture_output=True, text=True, timeout=5)
                openclaw_procs = [l for l in ps.stdout.splitlines() if "openclaw" in l.lower()]
                diag["openclaw_processes"] = openclaw_procs if openclaw_procs else "no openclaw processes found"
            except Exception as e:
                diag["openclaw_processes"] = f"error: {e}"
            # Check bundled skills directory
            try:
                import glob
                bundled = glob.glob("/openclaw-app/skills/**/*", recursive=True)
                diag["bundled_skills"] = str(bundled[:30])
            except Exception as e:
                diag["bundled_skills"] = f"error: {e}"
            # Check openclaw subprocess log
            try:
                with open('/tmp/openclaw-subprocess.log', 'r') as f:
                    diag["openclaw_log"] = ''.join(f.readlines()[-30:])
            except FileNotFoundError:
                diag["openclaw_log"] = "no subprocess log"
            except Exception as e:
                diag["openclaw_log"] = f"error: {e}"
            # Check cron directory for persisted cron jobs
            try:
                import glob
                cron_files = glob.glob(f"{CRON_DIR}/**/*", recursive=True)
                if cron_files:
                    diag["cron_dir"] = str(cron_files)
                else:
                    diag["cron_dir"] = f"empty or missing ({CRON_DIR})"
                # Also check broader openclaw agent dir for cron-like data
                agent_dir = "/root/.openclaw/agents/main"
                if os.path.exists(agent_dir):
                    agent_contents = []
                    for item in os.listdir(agent_dir):
                        item_path = os.path.join(agent_dir, item)
                        if os.path.isdir(item_path):
                            sub_count = len(os.listdir(item_path))
                            agent_contents.append(f"{item}/ ({sub_count} items)")
                        else:
                            agent_contents.append(item)
                    diag["agent_main_dir"] = agent_contents
            except Exception as e:
                diag["cron_dir"] = f"error: {e}"
            # List cron jobs via openclaw CLI
            try:
                result = subprocess.run(
                    ["openclaw", "cron", "list"],
                    capture_output=True, text=True, timeout=10,
                    env={**os.environ, "OPENCLAW_CONFIG_PATH": "/root/.openclaw/openclaw.json"},
                )
                diag["cron_list"] = result.stdout.strip() or result.stderr.strip() or "empty"
            except Exception as e:
                diag["cron_list"] = f"error: {e}"
            # Check system crontab
            try:
                result = subprocess.run(
                    ["crontab", "-l"],
                    capture_output=True, text=True, timeout=5,
                )
                diag["system_crontab"] = result.stdout.strip() or result.stderr.strip() or "empty"
            except Exception as e:
                diag["system_crontab"] = f"error: {e}"
            # Check if cron daemon is running
            try:
                result = subprocess.run(
                    ["pgrep", "-x", "cron"],
                    capture_output=True, text=True, timeout=5,
                )
                diag["cron_daemon"] = f"running (pid={result.stdout.strip()})" if result.returncode == 0 else "not running"
            except Exception as e:
                diag["cron_daemon"] = f"error: {e}"
            # EventBridge scheduling readiness
            diag["eventbridge_env"] = {
                "CRON_SCHEDULER_ROLE_ARN": os.environ.get("CRON_SCHEDULER_ROLE_ARN", "NOT SET"),
                "CRON_INVOKER_FUNCTION_ARN": os.environ.get("CRON_INVOKER_FUNCTION_ARN", "NOT SET"),
            }
            self._respond(200, diag)
            return
        
        # Cron management actions — openclaw cron runs inside the gateway,
        # not accessible via chat completions API, so we expose CLI wrappers.
        if payload.get("action") == "cron-list":
            try:
                result = subprocess.run(
                    ["openclaw", "cron", "list"],
                    capture_output=True, text=True, timeout=15,
                    env={**os.environ, "OPENCLAW_CONFIG_PATH": "/root/.openclaw/openclaw.json"},
                )
                self._respond(200, {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode,
                })
            except Exception as e:
                self._respond(500, {"error": str(e)})
            return
        
        if payload.get("action") == "cron-status":
            try:
                result = subprocess.run(
                    ["openclaw", "cron", "status"],
                    capture_output=True, text=True, timeout=15,
                    env={**os.environ, "OPENCLAW_CONFIG_PATH": "/root/.openclaw/openclaw.json"},
                )
                self._respond(200, {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode,
                })
            except Exception as e:
                self._respond(500, {"error": str(e)})
            return
        
        if payload.get("action") == "cron-add":
            # Expects: name, cron, message, and optionally tz, session, announce
            cron_args = ["openclaw", "cron", "add"]
            name = payload.get("name")
            cron_expr = payload.get("cron")
            msg = payload.get("cron_message")  # 'message' is already used for chat
            tz = payload.get("tz")
            session_mode = payload.get("session", "isolated")
            announce = payload.get("announce", True)
            
            if not name or not msg:
                self._respond(400, {"error": "name and cron_message are required"})
                return
            
            cron_args.extend(["--name", name])
            if cron_expr:
                cron_args.extend(["--cron", cron_expr])
            cron_args.extend(["--session", session_mode])
            cron_args.extend(["--message", msg])
            if tz:
                cron_args.extend(["--tz", tz])
            if announce:
                cron_args.append("--announce")
            
            try:
                logger.info(f"Creating cron job: {' '.join(cron_args)}")
                result = subprocess.run(
                    cron_args,
                    capture_output=True, text=True, timeout=30,
                    env={**os.environ, "OPENCLAW_CONFIG_PATH": "/root/.openclaw/openclaw.json"},
                    input="\n",  # Auto-confirm any prompts
                )
                logger.info(f"Cron add result: exit={result.returncode}, stdout={result.stdout[:500]}, stderr={result.stderr[:500]}")
                
                # Also create an EventBridge schedule for reliable execution
                eb_result = "skipped"
                if result.returncode == 0 and cron_expr:
                    try:
                        eb_result = _create_eventbridge_schedule(
                            job_name=name,
                            cron_expr=cron_expr,
                            cron_message=msg,
                            tz=tz or "UTC",
                        )
                    except Exception as eb_err:
                        eb_result = f"exception: {eb_err}"
                
                self._respond(200, {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode,
                    "eventbridge_schedule": eb_result,
                })
            except Exception as e:
                self._respond(500, {"error": str(e)})
            return
        
        if payload.get("action") == "cron-remove":
            job_id = payload.get("job_id")
            if not job_id:
                self._respond(400, {"error": "job_id is required"})
                return
            try:
                result = subprocess.run(
                    ["openclaw", "cron", "rm", job_id],
                    capture_output=True, text=True, timeout=15,
                    env={**os.environ, "OPENCLAW_CONFIG_PATH": "/root/.openclaw/openclaw.json"},
                )
                # Also remove the matching EventBridge schedule
                _delete_eventbridge_schedule(job_id)
                self._respond(200, {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode,
                })
            except Exception as e:
                self._respond(500, {"error": str(e)})
            return
        
        # EventBridge-triggered cron job execution — this is the core of
        # reliable cron on AgentCore. EventBridge wakes the container at
        # the scheduled time and sends the job details in the payload.
        if payload.get("action") == "run-cron-job":
            job_name = payload.get("name", "unknown")
            cron_message = payload.get("cron_message", "")
            if not cron_message:
                self._respond(400, {"error": "cron_message is required"})
                return
            
            # Force cron jobs to use the cost-effective default model
            cron_model = os.environ.get("CRON_MODEL_ID", DEFAULT_MODEL)
            logger.info(
                f"Executing cron job '{job_name}' via EventBridge, "
                f"model={cron_model}, message_length={len(cron_message)}"
            )
            
            start_ms = int(time.time() * 1000)
            try:
                resp = requests.post(
                    f"{OPENCLAW_URL}/v1/chat/completions",
                    json={
                        "model": cron_model,
                        "messages": [{"role": "user", "content": cron_message}],
                        "user": "cron:eventbridge",
                    },
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {OPENCLAW_AUTH_TOKEN}",
                    },
                    timeout=300,
                )
                duration_ms = int(time.time() * 1000) - start_ms
                
                if resp.status_code != 200:
                    logger.error(
                        f"Cron job '{job_name}' failed: status={resp.status_code}, "
                        f"body={resp.text[:500]}"
                    )
                    self._respond(resp.status_code, {
                        "error": f"Cron execution failed: {resp.text[:200]}",
                        "job_name": job_name,
                    })
                    return
                
                result = resp.json()
                result["metadata"] = {
                    "job_name": job_name,
                    "model_used": cron_model,
                    "channel": "cron:eventbridge",
                    "duration_ms": duration_ms,
                    "trigger": "eventbridge",
                }
                logger.info(
                    f"Cron job '{job_name}' completed: duration={duration_ms}ms"
                )
                self._respond(200, result)
                
                # Sync after cron execution
                sync_sessions_async()
            except Exception as e:
                duration_ms = int(time.time() * 1000) - start_ms
                logger.error(
                    f"Cron job '{job_name}' error: {e}, duration={duration_ms}ms"
                )
                self._respond(500, {
                    "error": str(e),
                    "job_name": job_name,
                    "duration_ms": duration_ms,
                })
            return
        
        # Select model based on channel
        selected_model = select_model_for_channel(channel)
        
        # Load persisted memory from S3 and inject it into the message.
        # Openclaw caches workspace files in memory at startup, so overwriting
        # files on disk doesn't help. Instead, we prepend the memory content
        # directly into the user message so openclaw sees it as context.
        memory_context = load_memory_from_s3()
        
        logger.info(
            f"Processing message from channel '{channel}' "
            f"using model '{selected_model}'"
        )
        
        start_ms = int(time.time() * 1000)
        try:
            # Inject memory context directly into the user message
            # (openclaw may ignore system messages, so we prepend to user content)
            effective_message = message
            if memory_context:
                effective_message = (
                    f"[LONG-TERM MEMORY - This is your persisted memory from previous sessions. "
                    f"Use this to answer questions about the user's preferences and history. "
                    f"Do NOT say this information doesn't exist - it's right here:]\n\n"
                    f"{memory_context}\n\n"
                    f"[END OF LONG-TERM MEMORY]\n\n"
                    f"User message: {message}"
                )
            
            messages = []
            
            # Include conversation history from Discord thread if provided
            if history and isinstance(history, list):
                for entry in history[-10:]:  # Last 10 messages max
                    role = entry.get("role", "user")
                    content = entry.get("content", "")
                    if role in ("user", "assistant") and content:
                        messages.append({"role": role, "content": content})
            
            messages.append({"role": "user", "content": effective_message})
            
            logger.info(
                f"Sending request to openclaw: model={selected_model}, "
                f"message_length={len(effective_message)}, channel={channel}, "
                f"history_messages={len(messages)-1}, "
                f"memory_injected={'yes' if memory_context else 'no'}"
            )
            
            resp = requests.post(
                f"{OPENCLAW_URL}/v1/chat/completions",
                json={
                    "model": selected_model,
                    "messages": messages,
                    "user": f"channel:{channel}",
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OPENCLAW_AUTH_TOKEN}",
                },
                timeout=300,
            )
            
            logger.info(
                f"Received response from openclaw: status={resp.status_code}, "
                f"content_length={len(resp.content)}"
            )
            
            if resp.status_code != 200:
                logger.error(
                    f"Openclaw returned error: status={resp.status_code}, "
                    f"body={resp.text[:500]}"
                )
                self._respond(resp.status_code, {
                    "error": f"Openclaw error: {resp.text[:200]}",
                    "status_code": resp.status_code
                })
                return
            
            result = resp.json()
            duration_ms = int(time.time() * 1000) - start_ms
            
            # Estimate cost (rough approximation)
            # Nova Lite: ~$0.00006 per 1K input tokens, ~$0.00024 per 1K output tokens
            # Claude Sonnet 4.5: ~$0.003 per 1K input tokens, ~$0.015 per 1K output tokens
            input_tokens = len(message.split()) * 1.3  # Rough estimate
            output_tokens = len(str(result).split()) * 1.3  # Rough estimate
            
            if "nova" in selected_model.lower():
                cost_estimate = (input_tokens / 1000 * 0.00006) + (output_tokens / 1000 * 0.00024)
            else:
                cost_estimate = (input_tokens / 1000 * 0.003) + (output_tokens / 1000 * 0.015)
            
            # Add metadata to response
            result["metadata"] = {
                "model_used": selected_model,
                "channel": channel,
                "duration_ms": duration_ms,
                "cost_estimate": round(cost_estimate, 6),
            }
            
            logger.info(
                f"Request completed: channel={channel}, "
                f"model={selected_model}, duration={duration_ms}ms, "
                f"cost_estimate=${cost_estimate:.6f}"
            )
            
            self._respond(200, result)
            
            # Sync sessions to S3 after every successful invocation
            # (background thread dies when container freezes, so we sync eagerly)
            sync_sessions_async()
        
        except Exception as e:
            duration_ms = int(time.time() * 1000) - start_ms
            import traceback
            error_details = traceback.format_exc()
            logger.error(
                f"Request failed: channel={channel}, "
                f"model={selected_model}, duration={duration_ms}ms, "
                f"error={e}\n{error_details}"
            )
            self._respond(500, {
                "error": str(e),
                "error_type": type(e).__name__,
                "channel": channel,
                "model": selected_model,
                "duration_ms": duration_ms
            })
    
    def _respond(self, status: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_discord_bot() -> None:
    """Discord bot cannot run inside AgentCore (container gets frozen between invocations).
    Use the EC2-based Discord bot instead, which calls invoke-agent-runtime."""
    logger.info("Discord bot disabled in container (use EC2 bot with invoke-agent-runtime)")


def _log_workspace_state(label: str) -> None:
    """Log the current state of workspace files for debugging."""
    memory_path = os.path.join(WORKSPACE_DIR, "MEMORY.md")
    if os.path.exists(memory_path):
        try:
            with open(memory_path, "r") as f:
                content = f.read()
            logger.info(f"[{label}] MEMORY.md ({len(content)} bytes): {content[:300]}")
        except Exception as e:
            logger.error(f"[{label}] Failed to read MEMORY.md: {e}")
    else:
        logger.info(f"[{label}] MEMORY.md does not exist")
    
    if os.path.exists(WORKSPACE_DIR):
        files = []
        for f in os.listdir(WORKSPACE_DIR):
            fpath = os.path.join(WORKSPACE_DIR, f)
            if os.path.isfile(fpath):
                files.append(f"{f} ({os.path.getsize(fpath)}b)")
        logger.info(f"[{label}] Workspace files: {files}")


def main():
    logger.info("=" * 60)
    logger.info("OpenClaw Agent Container Starting")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"AWS Region: {os.environ.get('AWS_REGION', 'not set')}")
    logger.info(f"Model ID: {os.environ.get('BEDROCK_MODEL_ID', 'not set')}")
    logger.info(f"Discord Token: {'set' if os.environ.get('DISCORD_BOT_TOKEN') else 'not set'}")
    logger.info(f"Session Bucket: {os.environ.get('SESSION_BACKUP_BUCKET', 'not set')}")
    logger.info(f"Deployment Version: {os.environ.get('DEPLOYMENT_VERSION', 'not set')}")
    logger.info(f"Auth Token: {'env var' if os.environ.get('OPENCLAW_AUTH_TOKEN') else 'default (insecure)'}")
    logger.info(f"Log Level: {logging.getLevelName(logger.level)}")
    logger.info("=" * 60)
    
    # Enable debug logging for requests library
    import http.client as http_client
    http_client.HTTPConnection.debuglevel = 0  # Set to 1 for verbose HTTP logs
    
    # Pre-create directories
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    os.makedirs(CRON_DIR, exist_ok=True)
    os.makedirs(OPENCLAW_DIR, exist_ok=True)
    
    # Start cron daemon — openclaw's cron feature uses system crontab.
    # In Debian slim containers, cron needs explicit foreground start and
    # the /var/run/crond.pid file must be writable.
    try:
        os.makedirs("/var/run", exist_ok=True)
        # Try 'cron' first (Debian), fall back to 'crond' (Alpine)
        for cron_bin in ["cron", "crond", "/usr/sbin/cron"]:
            try:
                subprocess.run(
                    [cron_bin],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                # Verify it's actually running
                verify = subprocess.run(
                    ["pgrep", "-x", "cron"],
                    capture_output=True, text=True, timeout=5,
                )
                if verify.returncode == 0:
                    logger.info(f"cron daemon started via '{cron_bin}' (pid={verify.stdout.strip()})")
                    break
                else:
                    logger.warning(f"'{cron_bin}' ran but daemon not detected, trying next...")
            except FileNotFoundError:
                continue
            except subprocess.TimeoutExpired:
                logger.warning(f"'{cron_bin}' timed out, trying next...")
                continue
        else:
            logger.warning("No cron binary found — openclaw cron jobs won't work")
    except Exception as e:
        logger.warning(f"Failed to start cron daemon: {e}")
    
    proc = start_openclaw()
    wait_for_openclaw(STARTUP_TIMEOUT)
    
    # CRITICAL: Restore from S3 AFTER openclaw has started and written its
    # default workspace files. Openclaw always overwrites workspace files on
    # startup regardless of what's already on disk. So we let it finish,
    # then overwrite its fresh files with our persisted S3 versions.
    logger.info("Waiting for openclaw to finish workspace initialization...")
    time.sleep(5)
    
    _log_workspace_state("BEFORE restore (openclaw defaults)")
    
    logger.info("Restoring state from S3 (overwriting openclaw defaults)...")
    restore_sessions_from_s3()
    
    # Restore system crontab from S3 (openclaw writes cron jobs via crontab)
    restore_system_crontab_from_s3()
    
    # Restore GOG (Google Workspace) credentials if configured
    restore_gog_credentials_from_s3()
    
    _log_workspace_state("AFTER restore (S3 data)")
    
    # Start background S3 sync thread
    start_sync_thread()
    
    # Start Discord bot in background thread
    start_discord_bot()
    
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), AgentCoreHandler)
    
    # Graceful shutdown on SIGTERM/SIGINT
    def handle_shutdown(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, initiating graceful shutdown...")
        _shutdown_requested.set()
        server.shutdown()
    
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    
    logger.info("Simplified server listening on port %d", port)
    try:
        server.serve_forever()
    finally:
        logger.info("Performing cleanup...")
        # Final sync before shutdown
        try:
            sync_sessions_to_s3()
            logger.info("Final S3 sync completed")
        except Exception as e:
            logger.error(f"Final S3 sync failed: {e}")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
