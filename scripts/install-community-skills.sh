#!/bin/bash
# Install community skills from community-skills.json into agent-container/skills/
# Runs during deploy.sh BEFORE Docker build.
#
# Two-tier approach:
#   - If agent-container/skills/<name>/ already exists → skip (custom/local skill)
#   - Otherwise → install from ClawHub registry
#
# Usage: bash scripts/install-community-skills.sh

set -e

SKILLS_JSON="agent-container/community-skills.json"
SKILLS_DIR="agent-container/skills"
OPENCLAW_JSON="agent-container/openclaw.json"

if [ ! -f "$SKILLS_JSON" ]; then
    echo "   ⚠️  No community-skills.json found — skipping community skill installation"
    exit 0
fi

# Parse skill names from JSON
SKILLS=$(python3 -c "
import json
with open('$SKILLS_JSON') as f:
    data = json.load(f)
for s in data.get('skills', []):
    print(s)
")

if [ -z "$SKILLS" ]; then
    echo "   ℹ️  No community skills configured"
    exit 0
fi

INSTALLED=0
SKIPPED=0
FAILED=0

for SKILL_NAME in $SKILLS; do
    if [ -d "$SKILLS_DIR/$SKILL_NAME" ] && [ -f "$SKILLS_DIR/$SKILL_NAME/SKILL.md" ]; then
        echo "   ⏭️  $SKILL_NAME — already exists locally (custom skill)"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    echo -n "   📦 Installing $SKILL_NAME... "

    # Try clawhub CLI first
    if command -v clawhub &> /dev/null; then
        mkdir -p "$SKILLS_DIR/$SKILL_NAME"
        if clawhub install "$SKILL_NAME" --target "$SKILLS_DIR/$SKILL_NAME" 2>/dev/null; then
            echo "✅ (clawhub)"
            INSTALLED=$((INSTALLED + 1))
            continue
        fi
    fi

    # Fallback: try npx clawhub
    if command -v npx &> /dev/null; then
        mkdir -p "$SKILLS_DIR/$SKILL_NAME"
        if npx -y clawhub install "$SKILL_NAME" --target "$SKILLS_DIR/$SKILL_NAME" 2>/dev/null; then
            echo "✅ (npx clawhub)"
            INSTALLED=$((INSTALLED + 1))
            continue
        fi
    fi

    # Fallback: try downloading from common ClawHub raw URLs
    SKILL_URL="https://raw.githubusercontent.com/clawhub/skills/main/${SKILL_NAME}/SKILL.md"
    mkdir -p "$SKILLS_DIR/$SKILL_NAME"
    if curl -fsSL "$SKILL_URL" -o "$SKILLS_DIR/$SKILL_NAME/SKILL.md" 2>/dev/null; then
        echo "✅ (github)"
        INSTALLED=$((INSTALLED + 1))
        continue
    fi

    # If all methods fail, warn but don't break the build
    rmdir "$SKILLS_DIR/$SKILL_NAME" 2>/dev/null || true
    echo "⚠️  not found (create locally in $SKILLS_DIR/$SKILL_NAME/SKILL.md)"
    FAILED=$((FAILED + 1))
done

# Auto-register skills in openclaw.json
echo ""
echo "   📝 Registering skills in openclaw.json..."
python3 -c "
import json, os

with open('$OPENCLAW_JSON') as f:
    config = json.load(f)

entries = config.setdefault('skills', {}).setdefault('entries', {})

with open('$SKILLS_JSON') as f:
    community = json.load(f)

changed = 0
for skill_name in community.get('skills', []):
    skill_dir = os.path.join('$SKILLS_DIR', skill_name)
    if os.path.isdir(skill_dir) and os.path.isfile(os.path.join(skill_dir, 'SKILL.md')):
        if skill_name not in entries:
            entries[skill_name] = {'enabled': True}
            changed += 1
            print(f'   ✅ Registered: {skill_name}')
        else:
            print(f'   ⏭️  Already registered: {skill_name}')

if changed > 0:
    with open('$OPENCLAW_JSON', 'w') as f:
        json.dump(config, f, indent=2)
        f.write('\n')
    print(f'   📝 Added {changed} new skill(s) to openclaw.json')
else:
    print(f'   ℹ️  All skills already registered')
"

echo ""
echo "   📊 Community skills: $INSTALLED installed, $SKIPPED skipped (local), $FAILED failed"
