# hermes-telegram-minimal

Minimalist, emoji-free Telegram UX plugin for [Hermes Agent](https://hermes-agent.nousresearch.com).

Provides developer-first formatting: clean monospace text tokens (`[+]`, `[i]`, `[!]`), syntax-highlighted tool progress streams with overflow limits, LaTeX math normalization to Unicode, and robust MarkdownV2 delivery.

---

## Features

- **Emoji Sanitization & Monospace Tokens**: Replaces conversational emojis with utilitarian tokens (`[+]`, `[i]`, `[!]`, `[~]`).
- **Verbose Tool Progress**:
  - **`execute_code`**: Streams Python syntax blocks during script execution (up to 35 lines / 1500 chars).
  - **`patch`**: Streams compact, readable unified diff previews (up to 25 lines of additions/deletions).
  - **`terminal`**: Streams shell command execution blocks.
  - **Overflow Safety**: Protects Telegram's 4,096-character limit while keeping full code visibility on desktop.
- **LaTeX Math Normalization**: Automatically converts math LaTeX symbols (`\rightarrow` → `→`, `\omega` → `ω`, `\Delta` → `Δ`) into native Unicode.
- **Native Telegram Tools**:
  - `telegram_send_card`: Structured MarkdownV2 status cards with thread routing.
  - `telegram_send_status`: Single-line status indicators with live in-place edits.
- **Upstream Deadlock Protection**: Built-in compatibility guard for Hermes v0.21.4+ isolated plugin load workers.

---

## Installation

Clone directly into your Hermes plugins directory:

```bash
git clone https://github.com/jtnqr/hermes-telegram-minimal.git ~/.hermes/plugins/telegram-minimal
```

Enable the plugin via Hermes CLI:

```bash
hermes plugins enable telegram-minimal
```

Restart your gateway:

```bash
hermes gateway restart
# or if running under systemd:
systemctl --user restart hermes-gateway
```

---

## Configuration

In `~/.hermes/config.yaml`:

```yaml
display:
  tool_progress: verbose
  tool_progress_command: true
  platforms:
    telegram:
      tool_progress: verbose

plugins:
  enabled:
    - telegram-minimal
```

Run `/verbose` in chat at any time to cycle progress display modes (`off` → `new` → `all` → `verbose`).

---

## Development & Testing

Run unit tests:

```bash
pytest tests/
```

---

## License

[MIT](LICENSE) © 2026 Julius Wicaksono (jtnqr)
