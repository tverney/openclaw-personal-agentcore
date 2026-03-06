---
name: notes-reminders
description: "Manage quick notes and time-based reminders. Use when a user asks to save a note, create a reminder, list notes, or search through saved notes."
metadata: { "openclaw": { "emoji": "📝", "requires": { "bins": ["bash"] } } }
---

# Notes & Reminders

File-based notes and reminders stored in `/openclaw-app/data/notes/`.

## When to Use

✅ **USE this skill when:**

- User asks to save/remember something
- User asks to create a reminder
- User asks to list or search notes
- User says "remind me to...", "note that...", "remember..."

❌ **DON'T use this skill when:**

- User wants calendar events (use Alexa or Google Calendar)
- User wants complex project management

## Storage

Notes are stored as individual files in `/openclaw-app/data/notes/`:
- Notes: `note_YYYYMMDD_HHMMSS.md`
- Reminders: `reminder_YYYYMMDD_HHMMSS.md`

## Commands

### Save a note
```bash
mkdir -p /openclaw-app/data/notes
cat > "/openclaw-app/data/notes/note_$(date +%Y%m%d_%H%M%S).md" << 'EOF'
# Note Title
Date: $(date -u +"%Y-%m-%d %H:%M UTC")

Content goes here.
EOF
```

### Save a reminder
```bash
mkdir -p /openclaw-app/data/notes
cat > "/openclaw-app/data/notes/reminder_$(date +%Y%m%d_%H%M%S).md" << 'EOF'
# Reminder
Due: YYYY-MM-DD HH:MM
Status: pending

Reminder content here.
EOF
```

### List all notes
```bash
ls -lt /openclaw-app/data/notes/note_* 2>/dev/null | head -20
```

### List pending reminders
```bash
grep -l "Status: pending" /openclaw-app/data/notes/reminder_* 2>/dev/null | while read f; do echo "=== $f ==="; cat "$f"; echo; done
```

### Search notes
```bash
grep -ril "search term" /openclaw-app/data/notes/ 2>/dev/null
```

### Read a specific note
```bash
cat /openclaw-app/data/notes/<filename>
```

### Mark reminder as done
```bash
sed -i 's/Status: pending/Status: done/' /openclaw-app/data/notes/<reminder_file>
```

### Delete a note
```bash
rm /openclaw-app/data/notes/<filename>
```

## Notes

- Notes persist across sessions if `/openclaw-app/data/` is mounted or backed up to S3
- Use descriptive content so search works well
- Reminders are passive (checked when asked) — for timed alerts, use cron jobs
