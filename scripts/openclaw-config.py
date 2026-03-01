#!/usr/bin/env python3
"""
openclaw-config — CLI tool to generate and manage openclaw.json skills configuration.

Curates a set of recommended skills for the OpenClaw Personal Edition
(AWS-hosted via Bedrock AgentCore) and writes the skills section into openclaw.json.

Usage:
    python openclaw-config.py list                  # Show all available skills
    python openclaw-config.py list --category aws   # Filter by category
    python openclaw-config.py enable <skill>        # Enable a skill
    python openclaw-config.py disable <skill>       # Disable a skill
    python openclaw-config.py set-key <skill> <key> # Set API key for a skill
    python openclaw-config.py apply                 # Write config to openclaw.json
    python openclaw-config.py show                  # Show current skills config
    python openclaw-config.py preset <name>         # Apply a preset (minimal/standard/full)
"""
import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ─── Skill catalog ───────────────────────────────────────────────────────────

@dataclass
class Skill:
    name: str
    description: str
    category: str
    requires_api_key: Optional[str] = None  # env var name if API key needed
    requires_bins: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    config: dict[str, str] = field(default_factory=dict)
    notes: str = ""
    container_compatible: bool = True  # works inside AgentCore container
    cost_impact: str = "none"  # none, low, medium, high


# Skills curated for a personal AWS-hosted deployment
SKILL_CATALOG: dict[str, Skill] = {
    # ── Bundled / Zero-config skills ──
    "web-search": Skill(
        name="web-search",
        description="Search the web and fetch page content (uses Tavily Search API)",
        category="search",
        requires_api_key="TAVILY_API_KEY",
        notes="Free tier: 1000 queries/month at tavily.com. AI-optimized search results.",
        cost_impact="none",
    ),
    "memory": Skill(
        name="memory",
        description="Persistent memory across sessions via MEMORY.md (bundled, always active)",
        category="core",
        notes="Already handled by S3 sync in server.py. Bundled skill, no config needed.",
        cost_impact="none",
    ),
    "session-logs": Skill(
        name="session-logs",
        description="Search past conversation history with jq + ripgrep",
        category="core",
        requires_bins=["jq", "rg"],
        notes="Needs jq and rg installed in the container. Add to Dockerfile.",
        cost_impact="none",
    ),
    "weather": Skill(
        name="weather",
        description="Current weather and forecasts via wttr.in (no API key needed)",
        category="utility",
        notes="Bundled. Uses wttr.in, zero config.",
        cost_impact="none",
    ),
    "humanizer": Skill(
        name="humanizer",
        description="Rewrites AI-sounding text to be more natural and human",
        category="writing",
        notes="Instruction-only skill, no dependencies. Great for content creation.",
        cost_impact="none",
    ),

    # ── AWS-native skills ──
    "aws-cli": Skill(
        name="aws-cli",
        description="Execute AWS CLI commands (the container already has boto3/AWS credentials via IAM role)",
        category="aws",
        requires_bins=["aws"],
        notes="Container has IAM role. Install awscli in Dockerfile for full CLI access.",
        cost_impact="low",
    ),
    "cloudwatch-logs": Skill(
        name="cloudwatch-logs",
        description="Query and tail CloudWatch log groups directly",
        category="aws",
        notes="Custom skill. Uses boto3 (already installed) to query CW logs.",
        cost_impact="none",
    ),
    "s3-browser": Skill(
        name="s3-browser",
        description="Browse and manage S3 objects (list, read, upload)",
        category="aws",
        notes="Custom skill. Uses boto3 to interact with S3 buckets the IAM role can access.",
        cost_impact="none",
    ),

    # ── Development skills ──
    "github": Skill(
        name="github",
        description="GitHub integration — repos, issues, PRs, code search",
        category="dev",
        requires_api_key="GITHUB_TOKEN",
        notes="Needs a GitHub personal access token. Bundled skill.",
        cost_impact="none",
    ),
    "git": Skill(
        name="git",
        description="Git operations in the workspace (status, diff, log, commit)",
        category="dev",
        requires_bins=["git"],
        notes="Bundled. Needs git in container.",
        cost_impact="none",
    ),

    # ── Productivity skills ──
    "summarize": Skill(
        name="summarize",
        description="Summarize URLs, articles, YouTube videos, and podcasts",
        category="productivity",
        requires_bins=["summarize"],
        notes="Needs the summarize binary (no Linux ARM64 build available).",
        container_compatible=False,
        cost_impact="none",
    ),
    "todoist": Skill(
        name="todoist",
        description="Manage Todoist tasks — create, complete, list, organize",
        category="productivity",
        requires_api_key="TODOIST_API_KEY",
        notes="Pure API skill. Get token from Settings > Integrations > Developer.",
        cost_impact="none",
    ),
    "gog": Skill(
        name="gog",
        description="Google Workspace CLI — Gmail, Calendar, Drive, Contacts, Sheets, Docs",
        category="productivity",
        requires_api_key="GOG_ACCOUNT",
        requires_bins=["gog"],
        notes=(
            "Setup: 1) brew install steipete/tap/gogcli, "
            "2) gog auth credentials /path/to/client_secret.json, "
            "3) gog auth add you@gmail.com --services gmail,calendar,drive,contacts,sheets,docs. "
            "For container: install gog in Dockerfile, sync ~/.gog/ credentials via S3, "
            "set GOG_ACCOUNT env var."
        ),
        container_compatible=True,
        cost_impact="none",
    ),
    "notion": Skill(
        name="notion",
        description="Read and write Notion pages and databases",
        category="productivity",
        requires_api_key="NOTION_API_KEY",
        notes="Pure API skill. Create integration at notion.so/my-integrations.",
        cost_impact="none",
    ),
    "obsidian": Skill(
        name="obsidian",
        description="Read, search, and write Obsidian vault notes",
        category="productivity",
        notes="Needs local vault on disk. Not practical inside a container.",
        container_compatible=False,
        cost_impact="none",
    ),

    # ── Communication skills ──
    "slack": Skill(
        name="slack",
        description="Send and read Slack messages, manage channels",
        category="communication",
        requires_api_key="SLACK_BOT_TOKEN",
        notes="Needs a Slack Bot token with appropriate scopes.",
        cost_impact="none",
    ),
    "telegram": Skill(
        name="telegram",
        description="Send messages and manage Telegram bot interactions",
        category="communication",
        requires_api_key="TELEGRAM_BOT_TOKEN",
        notes="Needs BotFather token. Useful if you add Telegram as a second channel.",
        cost_impact="none",
    ),

    # ── MCP server integrations ──
    "mcp-filesystem": Skill(
        name="mcp-filesystem",
        description="MCP server for safe filesystem operations (read/write/search)",
        category="mcp",
        notes="Useful for giving the agent structured file access beyond the workspace.",
        cost_impact="none",
    ),
    "mcp-fetch": Skill(
        name="mcp-fetch",
        description="MCP server for fetching web content (URLs, APIs)",
        category="mcp",
        notes="Complements web-search by fetching full page content.",
        cost_impact="none",
    ),
    "mcp-sqlite": Skill(
        name="mcp-sqlite",
        description="MCP server for SQLite database operations",
        category="mcp",
        notes="Useful for structured data storage, personal databases.",
        cost_impact="none",
    ),
    "mcp-playwright": Skill(
        name="mcp-playwright",
        description="MCP server for browser automation — scrape, screenshot, interact with web pages",
        category="mcp",
        notes="Headless Chromium via Playwright. Needs npx + playwright installed in container.",
        requires_bins=["npx"],
        cost_impact="none",
    )
}

# ─── Presets ─────────────────────────────────────────────────────────────────

PRESETS = {
    "minimal": {
        "description": "Core skills only — memory, weather, web search",
        "skills": ["memory", "weather", "web-search", "humanizer"],
    },
    "standard": {
        "description": "Recommended for personal use — core + dev + productivity",
        "skills": [
            "memory", "weather", "web-search", "humanizer",
            "session-logs", "github", "git",
            "cloudwatch-logs", "s3-browser",
        ],
    },
    "full": {
        "description": "Everything container-compatible enabled",
        "skills": [
            name for name, skill in SKILL_CATALOG.items()
            if skill.container_compatible
        ],
    },
}

# ─── State management ────────────────────────────────────────────────────────

CONFIG_STATE_FILE = Path(__file__).parent.parent / "agent-container" / ".openclaw-skills-state.json"
OPENCLAW_JSON = Path(__file__).parent.parent / "agent-container" / "openclaw.json"


def load_state() -> dict:
    """Load the current skills state (which skills are enabled + their keys)."""
    if CONFIG_STATE_FILE.exists():
        with open(CONFIG_STATE_FILE) as f:
            return json.load(f)
    return {"enabled": [], "api_keys": {}, "env_overrides": {}}


def save_state(state: dict):
    """Persist skills state to disk."""
    with open(CONFIG_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    print(f"  State saved to {CONFIG_STATE_FILE.name}")


def load_openclaw_json() -> dict:
    """Load the current openclaw.json."""
    with open(OPENCLAW_JSON) as f:
        return json.load(f)


def save_openclaw_json(config: dict):
    """Write updated openclaw.json."""
    with open(OPENCLAW_JSON, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    print(f"  Written to {OPENCLAW_JSON}")


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_list(args):
    """List available skills."""
    categories = sorted(set(s.category for s in SKILL_CATALOG.values()))
    state = load_state()
    enabled = set(state.get("enabled", []))

    filter_cat = getattr(args, "category", None)

    print("\n  OpenClaw Skills Catalog")
    print("  " + "=" * 50)

    for cat in categories:
        if filter_cat and cat != filter_cat:
            continue

        skills_in_cat = {k: v for k, v in SKILL_CATALOG.items() if v.category == cat}
        if not skills_in_cat:
            continue

        print(f"\n  [{cat.upper()}]")
        for key, skill in skills_in_cat.items():
            status = "✅" if key in enabled else "  "
            compat = "" if skill.container_compatible else " ⚠️  host-only"
            api = f" 🔑 {skill.requires_api_key}" if skill.requires_api_key else ""
            print(f"    {status} {key:<22} {skill.description[:55]}{api}{compat}")

    print(f"\n  Categories: {', '.join(categories)}")
    print(f"  Enabled: {len(enabled)}/{len(SKILL_CATALOG)}")
    print(f"  Use: openclaw-config enable <skill>")
    print()


def cmd_enable(args):
    """Enable a skill."""
    skill_name = args.skill
    if skill_name not in SKILL_CATALOG:
        print(f"  Unknown skill: {skill_name}")
        print(f"  Available: {', '.join(sorted(SKILL_CATALOG.keys()))}")
        sys.exit(1)

    skill = SKILL_CATALOG[skill_name]
    state = load_state()

    if skill_name not in state["enabled"]:
        state["enabled"].append(skill_name)

    if not skill.container_compatible:
        print(f"  ⚠️  '{skill_name}' is marked host-only — may not work inside AgentCore container")

    if skill.requires_api_key:
        current_key = state.get("api_keys", {}).get(skill_name, "")
        if not current_key:
            print(f"  🔑 This skill needs {skill.requires_api_key}")
            print(f"     Set it with: openclaw-config set-key {skill_name} <your-key>")

    if skill.requires_bins:
        print(f"  📦 Requires binaries: {', '.join(skill.requires_bins)}")
        print(f"     Make sure these are installed in the container (Dockerfile)")

    save_state(state)
    print(f"  ✅ Enabled: {skill_name}")


def cmd_disable(args):
    """Disable a skill."""
    state = load_state()
    if args.skill in state["enabled"]:
        state["enabled"].remove(args.skill)
        save_state(state)
        print(f"  Disabled: {args.skill}")
    else:
        print(f"  '{args.skill}' was not enabled")


def cmd_set_key(args):
    """Set an API key for a skill."""
    skill_name = args.skill
    if skill_name not in SKILL_CATALOG:
        print(f"  Unknown skill: {skill_name}")
        sys.exit(1)

    skill = SKILL_CATALOG[skill_name]
    if not skill.requires_api_key:
        print(f"  '{skill_name}' doesn't require an API key")
        sys.exit(1)

    state = load_state()
    if "api_keys" not in state:
        state["api_keys"] = {}
    state["api_keys"][skill_name] = args.key
    save_state(state)
    print(f"  🔑 Set {skill.requires_api_key} for {skill_name}")


def cmd_preset(args):
    """Apply a preset configuration."""
    preset_name = args.preset
    if preset_name not in PRESETS:
        print(f"  Unknown preset: {preset_name}")
        print(f"  Available: {', '.join(PRESETS.keys())}")
        for name, preset in PRESETS.items():
            print(f"    {name}: {preset['description']}")
        sys.exit(1)

    preset = PRESETS[preset_name]
    state = load_state()
    state["enabled"] = list(preset["skills"])
    save_state(state)

    print(f"  Applied preset: {preset_name}")
    print(f"  {preset['description']}")
    print(f"  Enabled {len(preset['skills'])} skills: {', '.join(preset['skills'])}")

    # Check for missing API keys
    missing_keys = []
    for skill_name in preset["skills"]:
        skill = SKILL_CATALOG.get(skill_name)
        if skill and skill.requires_api_key and skill_name not in state.get("api_keys", {}):
            missing_keys.append((skill_name, skill.requires_api_key))

    if missing_keys:
        print(f"\n  🔑 Missing API keys:")
        for name, env_var in missing_keys:
            print(f"     {name}: set-key {name} <{env_var}>")


def cmd_show(args):
    """Show current skills configuration."""
    state = load_state()
    enabled = state.get("enabled", [])
    api_keys = state.get("api_keys", {})

    print("\n  Current Skills Configuration")
    print("  " + "=" * 40)

    if not enabled:
        print("  No skills enabled. Run: openclaw-config preset standard")
    else:
        for name in enabled:
            skill = SKILL_CATALOG.get(name)
            if not skill:
                print(f"    ⚠️  {name} (unknown skill)")
                continue
            key_status = ""
            if skill.requires_api_key:
                has_key = name in api_keys and api_keys[name]
                key_status = " 🔑 set" if has_key else f" 🔑 MISSING ({skill.requires_api_key})"
            print(f"    ✅ {name}{key_status}")

    print()


def cmd_apply(args):
    """Write the skills configuration into openclaw.json.

    API keys are written as ${ENV_VAR} references, not raw values.
    The actual secrets go into CloudFormation EnvironmentVariables
    and get substituted at container startup by server.py.
    """
    state = load_state()
    enabled = state.get("enabled", [])
    api_keys = state.get("api_keys", {})

    if not enabled:
        print("  No skills enabled. Run: openclaw-config preset standard")
        sys.exit(1)

    config = load_openclaw_json()

    # Build skills entries
    entries = {}
    env_vars_needed = {}  # env var name -> value (for CloudFormation)

    for skill_name in enabled:
        skill = SKILL_CATALOG.get(skill_name)
        if not skill:
            continue

        entry: dict = {"enabled": True}

        # API keys use env var references — actual values go to CloudFormation
        if skill.requires_api_key:
            env_var = skill.requires_api_key
            entry["env"] = {env_var: f"${{{env_var}}}"}

            if skill_name in api_keys:
                env_vars_needed[env_var] = api_keys[skill_name]
            else:
                env_vars_needed[env_var] = ""

        # Add any static env vars
        if skill.env:
            if "env" not in entry:
                entry["env"] = {}
            entry["env"].update(skill.env)

        # Add any config overrides
        if skill.config:
            entry["config"] = skill.config

        entries[skill_name] = entry

    # Build the skills section
    skills_config = {
        "load": {
            "watch": True,
            "watchDebounceMs": 250,
        },
        "entries": entries,
    }

    config["skills"] = skills_config

    save_openclaw_json(config)

    print(f"\n  Applied {len(entries)} skills to openclaw.json")
    print(f"  Skills: {', '.join(entries.keys())}")

    # Write API keys to CloudFormation EnvironmentVariables
    # (container picks them up as env vars, server.py substitutes ${VAR} in openclaw.json)
    if env_vars_needed:
        _update_cloudformation_env_vars(env_vars_needed)
        # Also update .env for local docker testing
        _update_env_file(env_vars_needed)

    # Remind about container rebuild
    print(f"\n  Next steps:")
    print(f"    1. Deploy: ./scripts/deploy.sh")
    print()


def _update_env_file(env_vars: dict[str, str]):
    """Add skill API keys to agent-container/.env."""
    env_path = Path(__file__).parent.parent / "agent-container" / ".env"
    if not env_path.exists():
        return

    content = env_path.read_text()
    added = []

    for var_name, var_value in env_vars.items():
        if not var_value:
            continue
        # Check if already present (as VAR_NAME= at start of line)
        if f"\n{var_name}=" in content or content.startswith(f"{var_name}="):
            # Update existing value
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if line.startswith(f"{var_name}="):
                    lines[i] = f"{var_name}={var_value}"
                    break
            content = "\n".join(lines) + "\n"
            added.append(f"{var_name} (updated)")
        else:
            # Append new var
            if not content.endswith("\n"):
                content += "\n"
            content += f"{var_name}={var_value}\n"
            added.append(var_name)

    if added:
        env_path.write_text(content)
        print(f"\n  ✅ Added to .env: {', '.join(added)}")


def _update_cloudformation_env_vars(env_vars: dict[str, str]):
    """Add skill API keys to CloudFormation EnvironmentVariables (for deployed container)."""
    cfn_path = Path(__file__).parent.parent / "openclaw-simplified.yaml"
    if not cfn_path.exists():
        return

    content = cfn_path.read_text()
    added = []

    for var_name, var_value in env_vars.items():
        if not var_value:
            continue
        if var_name in content:
            continue  # already present

        # Insert after OPENCLAW_AUTH_TOKEN line in EnvironmentVariables
        anchor = '        OPENCLAW_AUTH_TOKEN:'
        if anchor in content:
            idx = content.index(anchor)
            line_end = content.index('\n', idx)
            new_line = f'        {var_name}: "{var_value}"\n'
            content = content[:line_end + 1] + new_line + content[line_end + 1:]
            added.append(var_name)

    if added:
        cfn_path.write_text(content)
        print(f"  ✅ Added to CloudFormation EnvironmentVariables: {', '.join(added)}")


# ─── CLI entry point ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="openclaw-config",
        description="Manage OpenClaw skills configuration for Personal Edition",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = sub.add_parser("list", help="List available skills")
    p_list.add_argument("--category", "-c", help="Filter by category")
    p_list.set_defaults(func=cmd_list)

    # enable
    p_enable = sub.add_parser("enable", help="Enable a skill")
    p_enable.add_argument("skill", help="Skill name")
    p_enable.set_defaults(func=cmd_enable)

    # disable
    p_disable = sub.add_parser("disable", help="Disable a skill")
    p_disable.add_argument("skill", help="Skill name")
    p_disable.set_defaults(func=cmd_disable)

    # set-key
    p_key = sub.add_parser("set-key", help="Set API key for a skill")
    p_key.add_argument("skill", help="Skill name")
    p_key.add_argument("key", help="API key value")
    p_key.set_defaults(func=cmd_set_key)

    # preset
    p_preset = sub.add_parser("preset", help="Apply a preset (minimal/standard/full)")
    p_preset.add_argument("preset", help="Preset name")
    p_preset.set_defaults(func=cmd_preset)

    # show
    p_show = sub.add_parser("show", help="Show current skills config")
    p_show.set_defaults(func=cmd_show)

    # apply
    p_apply = sub.add_parser("apply", help="Write skills config to openclaw.json")
    p_apply.set_defaults(func=cmd_apply)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
