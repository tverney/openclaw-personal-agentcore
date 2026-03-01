#!/usr/bin/env python3
"""
Discord Bot for OpenClaw Personal.
Calls AgentCore Runtime via boto3 invoke-agent-runtime.
"""
import asyncio
import base64
import json
import os
import re
import sys
import logging

import boto3
from botocore.config import Config
import discord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
AGENT_RUNTIME_ARN = os.environ["AGENTCORE_RUNTIME_ARN"]
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Track channels currently being processed to prevent overlapping responses
_processing = set()

bedrock_client = boto3.client(
    "bedrock-agentcore",
    region_name=AWS_REGION,
    config=Config(
        read_timeout=120,
        connect_timeout=10,
        retries={"max_attempts": 2},
    ),
)


def invoke_runtime(message: str, channel: str = "discord_general") -> str:
    """Invoke AgentCore runtime and return the AI response text.
    Retries once on 502 (container cold-start) errors.
    """
    payload = json.dumps({"message": message, "channel": channel})
    last_err = None

    for attempt in range(2):
        try:
            resp = bedrock_client.invoke_agent_runtime(
                agentRuntimeArn=AGENT_RUNTIME_ARN,
                payload=payload.encode("utf-8"),
                contentType="application/json",
            )

            stream = resp.get("response")
            if hasattr(stream, "read"):
                if hasattr(stream, "_raw_stream") and hasattr(stream._raw_stream, "settimeout"):
                    stream._raw_stream.settimeout(90)
                body = stream.read().decode("utf-8")
            else:
                body = str(stream)

            logger.info(f"Raw response length: {len(body)}")

            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse response: {body[:500]}")
                return f"Got response but couldn't parse it: {body[:200]}"

            if data.get("choices"):
                return data["choices"][0].get("message", {}).get("content", "No response")
            if data.get("message"):
                return data["message"]
            return json.dumps(data, indent=2)

        except Exception as e:
            last_err = e
            err_str = str(e)
            if "502" in err_str and attempt == 0:
                logger.warning(f"Got 502 on attempt {attempt+1}, retrying in 3s...")
                import time
                time.sleep(3)
                continue
            raise

    raise last_err


@client.event
async def on_ready():
    logger.info(f"Logged in as {client.user} (id={client.user.id})")
    logger.info(f"Guilds: {[g.name for g in client.guilds]}")
    logger.info(f"Runtime ARN: {AGENT_RUNTIME_ARN}")


@client.event
async def on_message(message):
    # Ignore all bots AND our own messages (belt and suspenders)
    if message.author.bot or message.author.id == client.user.id:
        return

    bot_id = str(client.user.id)
    is_mentioned = (
        client.user in message.mentions
        or f"<@{bot_id}>" in message.content
        or f"<@!{bot_id}>" in message.content
    )
    is_dm = isinstance(message.channel, discord.DMChannel)

    if not is_mentioned and not is_dm:
        return

    clean = message.content
    if is_mentioned:
        clean = re.sub(r"<@!?\d+>", "", clean).strip()

    if not clean:
        await message.channel.send("Hey! Send me a message and I'll respond.")
        return

    logger.info(f"Message from {message.author}: {clean[:100]}")

    # Prevent concurrent processing per channel (avoids cascading responses)
    chan_id = message.channel.id
    if chan_id in _processing:
        logger.warning(f"Already processing in channel {chan_id}, skipping")
        return
    _processing.add(chan_id)

    # React to show we got the message
    try:
        await message.add_reaction("🐾")
    except Exception:
        pass

    # Send first typing indicator immediately, then keep refreshing every 8s
    # discord.py 2.x removed trigger_typing(); use the HTTP route directly
    try:
        await client.http.send_typing(message.channel.id)
        logger.info("Typing indicator sent")
    except Exception as e:
        logger.warning(f"Failed to send typing: {e}")

    typing_flag = [True]

    async def keep_typing():
        await asyncio.sleep(8)  # first one already sent above
        while typing_flag[0]:
            try:
                await client.http.send_typing(message.channel.id)
            except Exception:
                pass
            await asyncio.sleep(8)

    typing_task = asyncio.create_task(keep_typing())

    try:
        ai_text = await asyncio.wait_for(
            asyncio.to_thread(invoke_runtime, clean),
            timeout=180,
        )

        if len(ai_text) <= 2000:
            await message.channel.send(ai_text)
        else:
            for i in range(0, len(ai_text), 2000):
                await message.channel.send(ai_text[i : i + 2000])

        logger.info(f"Reply sent ({len(ai_text)} chars)")

    except asyncio.TimeoutError:
        logger.error("invoke_runtime timed out after 180s")
        await message.channel.send("The AI took too long to respond. Try again?")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await message.channel.send("Sorry, something went wrong processing your request.")
    finally:
        typing_flag[0] = False
        typing_task.cancel()
        try:
            await message.remove_reaction("🐾", client.user)
        except Exception:
            pass
        _processing.discard(chan_id)


client.run(DISCORD_BOT_TOKEN)
