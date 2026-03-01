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
    
    This preserves conversation history and memory files across container restarts.
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


def sync_sessions_to_s3() -> None:
    """Sync openclaw state (sessions + workspace) to S3.
    Uploads session files and workspace files (memory, identity, etc.)
    so they persist across container restarts.
    
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
    
    def log_openclaw_output():
        for line in proc.stdout:
            decoded = line.decode().rstrip()
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
        
        # Support status check via invocations
        if payload.get("action") == "status":
            bot_alive = discord_bot_proc and hasattr(discord_bot_proc, 'is_alive') and discord_bot_proc.is_alive()
            self._respond(200, {
                "status": "ok",
                "discord_bot": "running" if bot_alive else "dead",
                "deployment_version": os.environ.get("DEPLOYMENT_VERSION", "unknown")
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
            
            messages = [{"role": "user", "content": effective_message}]
            
            logger.info(
                f"Sending request to openclaw: model={selected_model}, "
                f"message_length={len(effective_message)}, channel={channel}, "
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
    os.makedirs(OPENCLAW_DIR, exist_ok=True)
    
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
