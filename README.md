# claude-code-monitor

A floating always-on-top usage widget for Claude Code. Shows real 5h/7d rate limits, today's token usage, and session stats — works in **VS Code chat mode** (no terminal required).

```
528k $8.14  |  sess 112k 63msg  |  5h ████░░ 78% 2h17m  |  7d ██░░░░ 24% 1d14h   ×
```

## Why this exists

Every other Claude Code monitor either:
- Only works in terminal TUI mode (not VS Code)
- Estimates rate limits from JSONL files instead of showing real %

This widget calls `api.anthropic.com/api/oauth/usage` directly — the **same endpoint** the VS Code "Account & Usage" panel uses — so you get the exact utilization % and real reset time, always visible without clicking anything.

## Features

- **Real 5h/7d rate limit bars** with exact % and countdown to reset
- **Today's total tokens + cost** across all sessions and projects
- **Session stats** — tokens and message count for the active session
- **10 themes** — right-click anywhere to switch
- **Always on top**, draggable, 30px tall — stays out of your way
- **Auto-starts at login** (Windows, macOS, Linux)
- **Zero dependencies** — pure Python stdlib + tkinter

## Requirements

- Python 3.8+
- `tkinter` (included with standard Python on Windows/macOS; on Linux: `sudo apt install python3-tk`)
- Claude Code CLI authenticated with Claude AI (claude.ai account, not API key)

## Install

```bash
git clone https://github.com/pmashroo58/claude-code-monitor
cd claude-code-monitor
python monitor.py
```

That's it. The widget registers itself to auto-start at login on first run.

## Session stats setup (optional)

For the `sess` column (current session token count), add the Stop hook to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "python /path/to/hooks/capture-session.py",
        "timeout": 5
      }]
    }]
  }
}
```

Without this hook, session stats show `--` but everything else works fine.

## How it works

### Rate limits (real data)
Claude Code authenticates with claude.ai using OAuth. The OAuth token lives at `~/.claude/.credentials.json`. This widget uses that same token to call:

```
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <your_oauth_token>
```

Response includes `five_hour.utilization`, `five_hour.resets_at`, `seven_day.utilization`, `seven_day.resets_at` — exactly what the VS Code extension displays. Polled every 60 seconds. Countdown refreshes every 5 seconds from the stored `resets_at` timestamp.

### Token/cost data
Scans `~/.claude/projects/**/*.jsonl` (Claude Code's session files) and aggregates today's `input_tokens`, `output_tokens`, `cache_read_input_tokens`, and `cache_creation_input_tokens` across all projects and tabs.

### Session data
The Stop hook fires after each Claude response and writes the current session's stats to `~/.claude/widgets/claude-code-monitor/session_data.json`. The widget reads this file every 5 seconds.

## Themes

Right-click anywhere on the widget to open the theme picker.

| Dark themes | Light themes |
|------------|-------------|
| one-dark | linen |
| catppuccin-mocha | sakura |
| tokyo-night | |
| dracula | |
| nord | |
| graphite | |
| mono | |
| twilight | |

## Controls

| Action | How |
|--------|-----|
| Move | Drag anywhere on the widget |
| Switch theme | Right-click |
| Close | Click × |

Position and theme are saved to `~/.claude/widgets/claude-code-monitor/config.json`.

## Color coding

| Color | Meaning |
|-------|---------|
| Green | < 50% used |
| Yellow | 50–80% used |
| Red | > 80% used — approaching limit |

## Startup registration

On first run, `register_startup()` registers the widget to auto-launch:
- **Windows**: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
- **macOS**: `~/Library/LaunchAgents/com.claude.monitor.plist`
- **Linux**: `~/.config/autostart/claude-code-monitor.desktop`

To remove from startup, delete the registry key / plist / desktop file.

## FAQ

**Rate limits show `░░░░░░`?**  
You're logged in with an API key, not a claude.ai account. Rate limits are only available for Claude AI (claude.ai) subscribers.

**Session shows `--`?**  
The Stop hook isn't installed. See [Session stats setup](#session-stats-setup-optional) above. Today's totals still work without it.

**Widget not starting?**  
Run `python monitor.py` in a terminal to see errors. Common cause: Python without tkinter.

## License

MIT
