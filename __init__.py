"""Telegram UX Plugin — native cards, progress updates, and inline actions.

Sends or updates messages directly via Telegram Bot API using MarkdownV2 formatting,
ensuring mobile copy buttons, syntax coloring, expandable blockquotes, and inline actions.
"""

from __future__ import annotations

import importlib
import inspect
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STYLE_MAP = {
    "text": {
        "info": "[i]",
        "success": "[+]",
        "warning": "[!]",
        "error": "[x]",
        "working": "[~]",
        "memory": "[m]",
        "gateway": "[g]",
        "steer": "[>]",
        "compression": "[c]",
    },
    "emoji": {
        "info": "ℹ️",
        "success": "✅",
        "warning": "⚠️",
        "error": "❌",
        "working": "⏳",
        "memory": "🧠",
        "gateway": "♻️",
        "steer": "⏩",
        "compression": "🗜️",
    },
}

# Telegram MarkdownV2 reserved special characters outside code blocks
MD_SPECIAL = r"\_*[]()~`>#+-=|{}.!"


def _escape_md(text: Any) -> str:
    """Escape special characters for Telegram MarkdownV2 outside code blocks."""
    if text is None:
        return ""
    s = str(text)
    return re.sub(r"([\\_*\[\]()~`>#+\-=|{}.!])", r"\\\1", s)


def _escape_inline_code(text: Any) -> str:
    """Escape backtick and backslash inside inline `code`."""
    if text is None:
        return ""
    return str(text).replace("\\", "\\\\").replace("`", "\\`")


def _escape_code_block(text: str) -> str:
    """Escape backtick and backslash inside ```code``` blocks."""
    if not text:
        return ""
    return text.replace("\\", "\\\\").replace("`", "\\`")


def _format_body_md(body: str, expandable: bool = False) -> str:
    if not body:
        return ""

    # Check if body contains explicit triple-backtick code blocks
    code_match = re.search(r"```([a-zA-Z0-9_\-+]*)\n?(.*?)```", body, re.DOTALL)
    if code_match:
        lang = code_match.group(1).strip()
        code = code_match.group(2).strip("\n")
        escaped_code = _escape_code_block(code)
        code_block = f"```{lang}\n{escaped_code}\n```"

        pre_text = body[:code_match.start()].strip()
        post_text = body[code_match.end():].strip()

        parts = []
        if pre_text:
            escaped_pre = _escape_md(pre_text)
            if expandable:
                lines = [f"**>{line}" for line in escaped_pre.split("\n")]
                parts.append("\n".join(lines))
            else:
                lines = [f">{line}" for line in escaped_pre.split("\n")]
                parts.append("\n".join(lines))

        parts.append(code_block)

        if post_text:
            escaped_post = _escape_md(post_text)
            if expandable:
                lines = [f"**>{line}" for line in escaped_post.split("\n")]
                parts.append("\n".join(lines))
            else:
                lines = [f">{line}" for line in escaped_post.split("\n")]
                parts.append("\n".join(lines))

        return "\n\n".join(parts)

    # Body without code block:
    escaped = _escape_md(body)
    if expandable:
        lines = [f"**>{line}" for line in escaped.split("\n")]
        return "\n".join(lines)
    else:
        lines = [f">{line}" for line in escaped.split("\n")]
        return "\n".join(lines)


def _build_card_md(
    title: str,
    fields: Optional[Dict[str, Any]] = None,
    body: Optional[str] = None,
    footer: Optional[str] = None,
    style: str = "info",
    theme: str = "text",
    expandable: bool = False,
) -> str:
    icon_dict = STYLE_MAP.get(theme, STYLE_MAP["text"])
    icon = icon_dict.get(style, icon_dict["info"])

    escaped_title = _escape_md(title)
    escaped_icon = _escape_inline_code(icon)
    header = f"*{escaped_title}* `{escaped_icon}`" if theme == "text" else f"{icon} *{escaped_title}*"

    parts = [header]

    if fields:
        field_lines = []
        for k, v in fields.items():
            k_esc = _escape_md(k)
            v_esc = _escape_inline_code(v)
            field_lines.append(f"*{k_esc}:* `{v_esc}`")
        parts.append("\n".join(field_lines))

    if body:
        parts.append(_format_body_md(body, expandable=expandable))

    if footer:
        parts.append(f"_{_escape_md(footer)}_")

    return "\n\n".join(parts)


def _resolve_target(args: Dict[str, Any]) -> tuple[Optional[str], Optional[int]]:
    chat_id = args.get("chat_id") or os.getenv("HERMES_SESSION_CHAT_ID")
    thread_id_raw = args.get("thread_id") or os.getenv("HERMES_SESSION_THREAD_ID")
    thread_id = int(thread_id_raw) if thread_id_raw and str(thread_id_raw).isdigit() else None
    return str(chat_id) if chat_id else None, thread_id


def _call_tg_api(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        try:
            from hermes_cli.config import load_env
            env = load_env()
            token = env.get("TELEGRAM_BOT_TOKEN")
        except Exception:
            pass
    if not token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not configured in environment or ~/.hermes/.env"}

    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(err_body)
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}: {err_body}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _build_markup(buttons: Optional[List[Dict[str, str]]]) -> Optional[Dict[str, Any]]:
    if not buttons:
        return None
    keyboard = []
    row = []
    for btn in buttons:
        text = btn.get("text", "Link")
        url = btn.get("url")
        if url:
            row.append({"text": text, "url": url})
            if len(row) >= 2:
                keyboard.append(row)
                row = []
    if row:
        keyboard.append(row)
    return {"inline_keyboard": keyboard} if keyboard else None


def card_handler(args: Dict[str, Any], **kwargs: Any) -> str:
    title = args.get("title", "Status")
    fields = args.get("fields")
    body = args.get("body")
    footer = args.get("footer")
    style = args.get("style", "info")
    theme = args.get("theme", "text")
    expandable = bool(args.get("expandable", False))
    buttons = args.get("buttons")
    message_id = args.get("message_id")

    chat_id, thread_id = _resolve_target(args)
    if not chat_id:
        return json.dumps({"success": False, "error": "No chat_id provided or inferred from session"})

    text_md = _build_card_md(title, fields, body, footer, style, theme, expandable)

    # Enforce Telegram 4096 character safety limit
    if len(text_md) > 4000:
        text_md = text_md[:3920] + "\n\\.\\.\\.\n_[truncated]_"

    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text_md,
        "parse_mode": "MarkdownV2",
    }

    markup = _build_markup(buttons)
    if markup:
        payload["reply_markup"] = markup

    if message_id:
        payload["message_id"] = int(message_id)
        res = _call_tg_api("editMessageText", payload)
    else:
        if thread_id:
            payload["message_thread_id"] = thread_id
        res = _call_tg_api("sendMessage", payload)

    # Fallback to plain text if MarkdownV2 entity parsing fails
    if not res.get("ok") and "can't parse entities" in str(res.get("description", "")).lower():
        logger.warning("Telegram MarkdownV2 parse error: %s. Falling back to plain text.", res.get("description"))
        plain = re.sub(r"\\([\\_*\[\]()~`>#+\-=|{}.!])", r"\1", text_md)
        plain = re.sub(r"[*_`]", "", plain)
        payload["text"] = plain
        payload.pop("parse_mode", None)
        if message_id:
            res = _call_tg_api("editMessageText", payload)
        else:
            res = _call_tg_api("sendMessage", payload)

    if res.get("ok"):
        msg_result = res.get("result", {})
        return json.dumps({
            "success": True,
            "message_id": msg_result.get("message_id"),
            "chat_id": str(chat_id),
            "theme": theme,
        })
    return json.dumps({"success": False, "error": res.get("description") or res.get("error")})


def status_handler(args: Dict[str, Any], **kwargs: Any) -> str:
    message = args.get("message", "")
    style = args.get("style", "info")
    theme = args.get("theme", "text")
    message_id = args.get("message_id")

    chat_id, thread_id = _resolve_target(args)
    if not chat_id:
        return json.dumps({"success": False, "error": "No chat_id provided or inferred from session"})

    icon_dict = STYLE_MAP.get(theme, STYLE_MAP["text"])
    icon = icon_dict.get(style, icon_dict["info"])

    if theme == "text":
        text_md = f"`{_escape_inline_code(icon)}` {_escape_md(message)}"
    else:
        text_md = f"{icon} {_escape_md(message)}"

    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text_md,
        "parse_mode": "MarkdownV2",
    }

    if message_id:
        payload["message_id"] = int(message_id)
        res = _call_tg_api("editMessageText", payload)
    else:
        if thread_id:
            payload["message_thread_id"] = thread_id
        res = _call_tg_api("sendMessage", payload)

    if res.get("ok"):
        msg_result = res.get("result", {})
        return json.dumps({
            "success": True,
            "message_id": msg_result.get("message_id"),
            "chat_id": str(chat_id),
            "theme": theme,
        })
    return json.dumps({"success": False, "error": res.get("description") or res.get("error")})


CARD_SCHEMA = {
    "name": "telegram_send_card",
    "description": (
        "Send or update a rich Telegram status card directly to the active chat using native MarkdownV2. "
        "Guarantees code syntax highlighting, copy button on mobile, expandable quotes, and buttons."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Card title header"},
            "style": {
                "type": "string",
                "enum": ["info", "success", "warning", "error", "working", "gateway", "steer", "compression"],
                "description": "Status level badge",
            },
            "theme": {
                "type": "string",
                "enum": ["text", "emoji"],
                "description": "Icon theme: 'text' uses clean CLI tokens ([i], [+], [!], [x], [~]); 'emoji' uses Unicode symbols",
            },
            "fields": {
                "type": "object",
                "description": "Key-value pairs to display as formatted monospace fields",
            },
            "body": {
                "type": "string",
                "description": "Main body text. Supports ```language ... ``` code blocks.",
            },
            "expandable": {
                "type": "boolean",
                "description": "If true, wraps text outside code blocks in a collapsible blockquote",
            },
            "footer": {"type": "string", "description": "Small italic footer text"},
            "buttons": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "url": {"type": "string"},
                    },
                    "required": ["text", "url"],
                },
                "description": "Inline URL keyboard buttons",
            },
            "message_id": {
                "type": "integer",
                "description": "If provided, edits this existing message in-place instead of creating a new one",
            },
            "chat_id": {
                "type": "string",
                "description": "Optional explicit chat ID (defaults to current session chat)",
            },
        },
        "required": ["title"],
    },
}

STATUS_SCHEMA = {
    "name": "telegram_send_status",
    "description": "Send or update a brief one-line status line in Telegram.",
    "parameters": {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Status text"},
            "style": {
                "type": "string",
                "enum": ["info", "success", "warning", "error", "working", "gateway", "steer", "compression"],
            },
            "theme": {
                "type": "string",
                "enum": ["text", "emoji"],
                "description": "Icon theme: 'text' ([+], [~], [!]) or 'emoji' (✅, ⏳, ⚠️)",
            },
            "message_id": {
                "type": "integer",
                "description": "If provided, edits this message in-place",
            },
            "chat_id": {
                "type": "string",
                "description": "Optional explicit chat ID",
            },
        },
        "required": ["message"],
    },
}


def format_telegram_verbose_tool(tool_name: str, args: Optional[Dict[str, Any]], preview: Optional[str] = None) -> str:
    """Format tool progress event cleanly for Telegram verbose mode."""
    args = args or {}
    badge = "[~]"

    if tool_name == "terminal":
        cmd = str(args.get("command", "")).strip()
        lines = cmd.splitlines()
        if len(lines) > 30 or len(cmd) > 1500:
            cmd_short = "\n".join(lines[:30])
            if len(cmd_short) > 1500:
                cmd_short = cmd_short[:1497] + "\n..."
            else:
                cmd_short += f"\n# ... ({len(lines) - 30} more lines)"
        else:
            cmd_short = cmd
        cmd_clean = cmd_short.replace("```", "'''")
        return f"{badge} **terminal**\n```sh\n{cmd_clean}\n```"

    if tool_name == "read_file":
        path = str(args.get("path", "")).replace("`", "'")
        offset = args.get("offset")
        limit = args.get("limit")
        line_range = f":{offset}-{int(offset) + int(limit) - 1}" if offset and limit else ""
        if len(path) > 100:
            path = "..." + path[-97:]
        return f"{badge} **read_file** `{path}{line_range}`"

    if tool_name == "patch":
        path = str(args.get("path", "")).replace("`", "'")
        if len(path) > 100:
            path = "..." + path[-97:]
        old_str = str(args.get("old_string", "")).strip()
        new_str = str(args.get("new_string", "")).strip()
        old_lines = old_str.splitlines()
        new_lines = new_str.splitlines()
        max_lines = 25
        diff_lines = []
        for l in old_lines[:max_lines]:
            diff_lines.append(f"- {l[:120]}")
        if len(old_lines) > max_lines:
            diff_lines.append(f"- ... ({len(old_lines) - max_lines} more lines)")
        for l in new_lines[:max_lines]:
            diff_lines.append(f"+ {l[:120]}")
        if len(new_lines) > max_lines:
            diff_lines.append(f"+ ... ({len(new_lines) - max_lines} more lines)")
        if diff_lines:
            diff_block = "\n".join(diff_lines)
            if len(diff_block) > 1800:
                diff_block = diff_block[:1797] + "\n..."
            diff_block = diff_block.replace("```", "'''")
            return f"{badge} **patch** `{path}`\n```diff\n{diff_block}\n```"
        return f"{badge} **patch** `{path}`"

    if tool_name == "write_file":
        path = str(args.get("path", "")).replace("`", "'")
        if len(path) > 100:
            path = "..." + path[-97:]
        content = str(args.get("content", ""))
        line_count = len(content.splitlines())
        return f"{badge} **write_file** `{path}` *({line_count} lines)*"

    if tool_name == "execute_code":
        code = str(args.get("code", "")).strip()
        lines = code.splitlines()
        if len(lines) > 35 or len(code) > 1500:
            code_short = "\n".join(lines[:35])
            if len(code_short) > 1500:
                code_short = code_short[:1497] + "\n..."
            else:
                code_short += f"\n# ... ({len(lines) - 35} more lines)"
        else:
            code_short = code
        code_clean = code_short.replace("```", "'''")
        return f"{badge} **execute_code**\n```python\n{code_clean}\n```"

    if tool_name == "search_files":
        pat = str(args.get("pattern", "")).replace("`", "'")
        if len(pat) > 60:
            pat = pat[:57] + "..."
        tgt = str(args.get("target", "content"))
        path = args.get("path")
        path_str = ""
        if path and path != ".":
            path_clean = str(path).replace("`", "'")
            if len(path_clean) > 50:
                path_clean = "..." + path_clean[-47:]
            path_str = f" in `{path_clean}`"
        return f"{badge} **search_files** `{pat}` *({tgt})*{path_str}"

    if tool_name == "skill_view":
        name = str(args.get("name", "")).replace("`", "'")
        fp = args.get("file_path")
        fp_str = f" `{str(fp).replace('`', '')}`" if fp else ""
        return f"{badge} **skill_view** `{name}`{fp_str}"

    if tool_name == "web_search":
        query = str(args.get("query", "")).replace("`", "'")
        if len(query) > 60:
            query = query[:57] + "..."
        return f'{badge} **web_search** `"{query}"`'

    # Fallback for generic tools
    if args:
        summary_items = []
        for k, v in list(args.items())[:3]:
            v_str = str(v)
            if len(v_str) > 30:
                v_str = v_str[:27] + "..."
            summary_items.append(f"{k}: {v_str}")
        summary = ", ".join(summary_items)
        return f"{badge} **{tool_name}** `{summary}`"

    if preview:
        return f'{badge} **{tool_name}** `"{preview}"`'

    return f"{badge} **{tool_name}**"


EMOJI_TOKEN_MAP = [
    # Gateway lifecycle notices -> [g]
    (r"(?:⚠️?|⏳|♻️?|🔄)\s*(?=.*(?:[Gg]ateway|restarting|shutting down|before restart))", "[g] "),
    (r"♻️?\s*", "[g] "),
    # Context compression & compaction notices -> [c]
    (r"(?:ℹ️?|⚠️?|⏳|🗜️?)\s*(?=.*(?:[Cc]ompress|[Ss]ummary generation|[Cc]ompact))", "[c] "),
    (r"🗜️?\s*", "[c] "),
    # Steering, redirecting & subagent delegation -> [>]
    (r"⏩\s*", "[>] "),
    (r"↪️?\s*", "[>] "),
    (r"🔀\s*", "[>] "),
    # Memory, skill patches, reviews -> [m]
    (r"💾\s*", "[m] "),
    (r"🧠\s*", "[m] "),
    (r"👁️?\s*", "[m] "),
    (r"📝\s*(?=.*[Ss]kill)", "[m] "),
    # Standard status tokens
    (r"✅\s*", "[+] "),
    (r"✔\s*", "[+] "),
    (r"✓\s*", "[+] "),
    (r"✨\s*", "[+] "),
    (r"🔒\s*", "[+] "),
    (r"🔐\s*", "[+] "),
    (r"➕\s*", "[+] "),
    (r"❌\s*", "[x] "),
    (r"✗\s*", "[x] "),
    (r"✖\s*", "[x] "),
    (r"✕\s*", "[x] "),
    (r"⛔\s*", "[x] "),
    (r"🛑\s*", "[x] "),
    (r"⚠️?\s*", "[!] "),
    (r"⚡\s*", "[!] "),
    (r"⚕️?\s*", "[!] "),
    (r"🟡\s*", "[!] "),
    (r"⏸️?\s*", "[!] "),
    (r"⏱️?\s*", "[~] "),
    (r"⏳\s*", "[~] "),
    (r"🔄\s*", "[~] "),
    (r"⚙️?\s*", "[~] "),
    (r"🔎\s*", "[~] "),
    (r"💻\s*", "[~] "),
    (r"ℹ️?\s*", "[i] "),
    (r"💬\s*", "[i] "),
    (r"💡\s*", "[i] "),
    (r"📌\s*", "[i] "),
    (r"📋\s*", "[i] "),
    (r"✦\s*", "[i] "),
    (r"🎭\s*", "[i] "),
    (r"📊\s*", "[i] "),
    (r"📚\s*", "[i] "),
    (r"📖\s*", "[i] "),
    (r"🤖\s*", "[i] "),
    (r"🎙️?\s*", "[i] "),
    (r"👀\s*", "[i] "),
    (r"📝\s*", "[i] "),
    (r"➖\s*", "[-] "),
]

LATEX_MAP = [
    (r"\$\s*\\rightarrow\s*\$|\\rightarrow(?=[^a-zA-Z]|$)", "→"),
    (r"\$\s*\\to\s*\$|\\to(?=[^a-zA-Z]|$)", "→"),
    (r"\$\s*\\leftarrow\s*\$|\\leftarrow(?=[^a-zA-Z]|$)", "←"),
    (r"\$\s*\\Rightarrow\s*\$|\\Rightarrow(?=[^a-zA-Z]|$)", "⇒"),
    (r"\$\s*\\Leftarrow\s*\$|\\Leftarrow(?=[^a-zA-Z]|$)", "⇐"),
    (r"\$\s*\\leftrightarrow\s*\$|\\leftrightarrow(?=[^a-zA-Z]|$)", "↔"),
    (r"\$\s*\\le(q)?\s*\$|\\le(q)?(?=[^a-zA-Z]|$)", "≤"),
    (r"\$\s*\\ge(q)?\s*\$|\\ge(q)?(?=[^a-zA-Z]|$)", "≥"),
    (r"\$\s*\\neq\s*\$|\\neq(?=[^a-zA-Z]|$)", "≠"),
    (r"\$\s*\\approx\s*\$|\\approx(?=[^a-zA-Z]|$)", "≈"),
    (r"\$\s*\\times\s*\$|\\times(?=[^a-zA-Z]|$)", "×"),
    (r"\$\s*\\cdot\s*\$|\\cdot(?=[^a-zA-Z]|$)", "·"),
    (r"\$\s*\\dots\s*\$|\\dots(?=[^a-zA-Z]|$)", "…"),
    (r"\$\s*\\pm\s*\$|\\pm(?=[^a-zA-Z]|$)", "±"),
    (r"\$\s*\\mp\s*\$|\\mp(?=[^a-zA-Z]|$)", "∓"),
    (r"\$\s*\\infty\s*\$|\\infty(?=[^a-zA-Z]|$)", "∞"),
    (r"\$\s*\\in\s*\$|\\in(?=[^a-zA-Z]|$)", "∈"),
    (r"\$\s*\\notin\s*\$|\\notin(?=[^a-zA-Z]|$)", "∉"),
    (r"\$\s*\\subset\s*\$|\\subset(?=[^a-zA-Z]|$)", "⊂"),
    (r"\$\s*\\subseteq\s*\$|\\subseteq(?=[^a-zA-Z]|$)", "⊆"),
    (r"\$\s*\\forall\s*\$|\\forall(?=[^a-zA-Z]|$)", "∀"),
    (r"\$\s*\\exists\s*\$|\\exists(?=[^a-zA-Z]|$)", "∃"),
    (r"\$\s*\\sum\s*\$|\\sum(?=[^a-zA-Z]|$)", "∑"),
    (r"\$\s*\\prod\s*\$|\\prod(?=[^a-zA-Z]|$)", "∏"),
    (r"\$\s*\\partial\s*\$|\\partial(?=[^a-zA-Z]|$)", "∂"),
    (r"\$\s*\\nabla\s*\$|\\nabla(?=[^a-zA-Z]|$)", "∇"),
    (r"\$\s*\\int\s*\$|\\int(?=[^a-zA-Z]|$)", "∫"),
    (r"\$\s*\\lim\s*\$|\\lim(?=[^a-zA-Z]|$)", "lim"),
    (r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"\1/\2"),
    (r"\\sqrt\{([^{}]+)\}", r"√(\1)"),
    (r"\$\s*\\alpha\s*\$|\\alpha(?=[^a-zA-Z]|$)", "α"),
    (r"\$\s*\\beta\s*\$|\\beta(?=[^a-zA-Z]|$)", "β"),
    (r"\$\s*\\gamma\s*\$|\\gamma(?=[^a-zA-Z]|$)", "γ"),
    (r"\$\s*\\delta\s*\$|\\delta(?=[^a-zA-Z]|$)", "δ"),
    (r"\$\s*\\epsilon\s*\$|\\epsilon(?=[^a-zA-Z]|$)", "ε"),
    (r"\$\s*\\lambda\s*\$|\\lambda(?=[^a-zA-Z]|$)", "λ"),
    (r"\$\s*\\mu\s*\$|\\mu(?=[^a-zA-Z]|$)", "μ"),
    (r"\$\s*\\pi\s*\$|\\pi(?=[^a-zA-Z]|$)", "π"),
    (r"\$\s*\\sigma\s*\$|\\sigma(?=[^a-zA-Z]|$)", "σ"),
    (r"\$\s*\\theta\s*\$|\\theta(?=[^a-zA-Z]|$)", "θ"),
    (r"\$\s*\\omega\s*\$|\\omega(?=[^a-zA-Z]|$)", "ω"),
    (r"\$\s*\\Delta\s*\$|\\Delta(?=[^a-zA-Z]|$)", "Δ"),
    (r"\$\s*\\Omega\s*\$|\\Omega(?=[^a-zA-Z]|$)", "Ω"),
]


def clean_telegram_content(text: str) -> str:
    """Sanitize content for Telegram: convert emojis to text tokens, LaTeX to Unicode, and fix list formatting."""
    if not text:
        return text

    # 0. Stash fenced code blocks first, then normalize multi-backtick inline spans
    fences: list[str] = []
    def _stash_fence(m: re.Match) -> str:
        fences.append(m.group(0))
        return f"\x00FENCE_{len(fences)-1}\x00"

    text = re.sub(r"(```[\s\S]*?```)", _stash_fence, text)
    # CommonMark uses `` `code` `` to escape backticks inside code spans.
    # Telegram MarkdownV2 only supports single `code`. Normalize multi-backtick spans.
    text = re.sub(r"``+\s*`?([^`\n]+?)`?\s*``+", r"`\1`", text)
    for i, f in enumerate(fences):
        text = text.replace(f"\x00FENCE_{len(fences)-1-i}\x00", f)

    # 1. Stash fenced code blocks and inline code so they remain untouched
    code_blocks: list[str] = []
    def _stash_code(m: re.Match) -> str:
        code_blocks.append(m.group(0))
        return f"\x00CODE_{len(code_blocks)-1}\x00"

    text = re.sub(r"(```[\s\S]*?```|`[^`]+`)", _stash_code, text)

    # 2. Replace known status emojis with monospace tokens
    for pat, token in EMOJI_TOKEN_MAP:
        text = re.sub(pat, token, text)

    # 3. Strip remaining Unicode emojis outside code
    emoji_pattern = r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\ufe0e\ufe0f]|\u200d"
    text = re.sub(emoji_pattern, "", text)

    # 4. Replace LaTeX arrows and math notations with clean Unicode
    for pat, repl in LATEX_MAP:
        text = re.sub(pat, repl, text)

    # Strip remaining bare inline math delimiters: $x$ -> x
    text = re.sub(r"\$([^$\n]+)\$", r"\1", text)

    # 5. Convert line-start list markers (* and -) to clean bullets
    text = re.sub(r"^(\s*)[*-] ", r"\1• ", text, flags=re.MULTILINE)

    # 6. Restore preserved code blocks
    for idx, cb in enumerate(code_blocks):
        text = text.replace(f"\x00CODE_{idx}\x00", cb)

    # 7. Normalize nested bold-around-code **`code`** to `code`
    text = re.sub(r"\*\*`([^`]+)`\*\*", r"`\1`", text)

    # 8. Collapse multiple spaces outside code (preserving line indentation)
    text = re.sub(r"([^\n ]) {2,}", r"\1 ", text)

    return text.strip()


def _install_turnrunner_hook(ctx: Any) -> None:
    """Wrap TurnRunner progress and status callbacks to render clean tokens in Telegram."""
    try:
        from gateway.run_turn_runner import TurnRunner
    except ImportError as e:
        logger.debug("TurnRunner not importable (not in gateway mode): %s", e)
        return

    orig_progress = getattr(TurnRunner, "_orig_progress_callback_tg_ux", None)
    if orig_progress is None:
        orig_progress = TurnRunner.progress_callback
        TurnRunner._orig_progress_callback_tg_ux = orig_progress

    orig_status = getattr(TurnRunner, "_orig_status_callback_tg_ux", None)
    if orig_status is None:
        orig_status = TurnRunner._status_callback_sync
        TurnRunner._orig_status_callback_tg_ux = orig_status

    def clean_status_callback(self: Any, event_type: str, message: str) -> None:
        turn_ctx = getattr(self, "_ctx", None)
        source = getattr(turn_ctx, "source", None)
        platform = getattr(source, "platform", None)
        if getattr(platform, "value", platform) == "telegram" and message:
            message = clean_telegram_content(message)
        return orig_status(self, event_type, message)

    TurnRunner._status_callback_sync = clean_status_callback

    def verbose_progress_callback(self: Any, event_type: str, tool_name: Optional[str] = None, preview: Optional[str] = None, args: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Any:
        turn_ctx = getattr(self, "_ctx", None)
        source = getattr(turn_ctx, "source", None)
        platform = getattr(source, "platform", None)
        platform_name = getattr(platform, "value", platform)

        if (
            platform_name == "telegram"
            and getattr(turn_ctx, "progress_mode", None) == "verbose"
            and event_type == "tool.started"
            and tool_name
            and tool_name != "_thinking"
            and tool_name != "clarify"
        ):
            # Respect interruption
            try:
                holder = getattr(turn_ctx, "agent_holder", None)
                agent = holder[0] if holder else None
                if agent is not None and getattr(agent, "is_interrupted", False):
                    return
            except Exception:
                pass

            msg = format_telegram_verbose_tool(tool_name, args, preview)
            if hasattr(turn_ctx, "last_was_terminal_block"):
                turn_ctx.last_was_terminal_block[0] = False

            # Dedup identical progress messages
            last_msg_holder = getattr(turn_ctx, "last_progress_msg", None)
            repeat_holder = getattr(turn_ctx, "repeat_count", None)
            progress_q = getattr(turn_ctx, "progress_queue", None)
            sc_holder = getattr(turn_ctx, "stream_consumer_holder", None)
            sc = sc_holder[0] if sc_holder else None

            if last_msg_holder and repeat_holder and msg == last_msg_holder[0]:
                repeat_holder[0] += 1
                if sc is not None and getattr(sc, "accepts_tool_progress", False):
                    sc.on_tool_progress(f"{msg} (×{repeat_holder[0] + 1})")
                    return
                if progress_q:
                    progress_q.put(("__dedup__", msg, repeat_holder[0]))
                return

            if last_msg_holder:
                last_msg_holder[0] = msg
            if repeat_holder:
                repeat_holder[0] = 0

            if sc is not None and getattr(sc, "accepts_tool_progress", False):
                sc.on_tool_progress(msg)
                return

            if progress_q:
                progress_q.put(msg)
            return

        return orig_progress(self, event_type, tool_name, preview, args, **kwargs)

    TurnRunner.progress_callback = verbose_progress_callback

    def _uninstall_hook() -> None:
        if hasattr(TurnRunner, "_orig_progress_callback_tg_ux"):
            TurnRunner.progress_callback = TurnRunner._orig_progress_callback_tg_ux
        if hasattr(TurnRunner, "_orig_status_callback_tg_ux"):
            TurnRunner._status_callback_sync = TurnRunner._orig_status_callback_tg_ux

    if hasattr(ctx, "on_unload"):
        ctx.on_unload(_uninstall_hook)


def _find_telegram_adapter_classes() -> list[type]:
    """Discover all TelegramAdapter classes (bundled or loaded via hermes_plugins)."""
    classes: list[type] = []
    for mod_name, mod in list(sys.modules.items()):
        if mod and "telegram" in mod_name and "adapter" in mod_name:
            cls = getattr(mod, "TelegramAdapter", None)
            if isinstance(cls, type) and cls not in classes:
                classes.append(cls)
    for mod_path in [
        "plugins.platforms.telegram.adapter",
        "hermes_plugins.platforms__telegram.adapter",
        "hermes_plugins.telegram_platform.adapter",
    ]:
        try:
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, "TelegramAdapter", None)
            if isinstance(cls, type) and cls not in classes:
                classes.append(cls)
        except Exception:
            pass
    if not classes:
        try:
            from hermes_cli.plugins_loader import in_plugin_load_worker
            if not in_plugin_load_worker():
                from gateway.platform_registry import platform_registry
                entry = platform_registry.get("telegram")
                if entry and entry.adapter_factory:
                    mod = inspect.getmodule(entry.adapter_factory)
                    cls = getattr(mod, "TelegramAdapter", None)
                    if isinstance(cls, type) and cls not in classes:
                        classes.append(cls)
        except Exception:
            pass
    return classes


def _hook_adapter_class(cls: type) -> None:
    """Safely hook a TelegramAdapter class to sanitize outgoing content and format markdown."""
    orig_format = getattr(cls, "_orig_format_message_tg_ux", None)
    if orig_format is None:
        orig_format = cls.format_message
        cls._orig_format_message_tg_ux = orig_format

        def _wrap_format(of: Any) -> Any:
            def clean_format_message(self: Any, content: str) -> str:
                return of(self, clean_telegram_content(content))
            return clean_format_message

        cls.format_message = _wrap_format(orig_format)

    orig_send = getattr(cls, "_orig_send_tg_ux", None)
    if orig_send is None:
        orig_send = cls.send
        cls._orig_send_tg_ux = orig_send

        def _wrap_send(osnd: Any) -> Any:
            async def clean_send(self: Any, chat_id: str, content: str, reply_to: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Any:
                if content:
                    content = clean_telegram_content(content)
                return await osnd(self, chat_id, content, reply_to=reply_to, metadata=metadata)
            return clean_send

        cls.send = _wrap_send(orig_send)

    orig_edit = getattr(cls, "_orig_edit_message_tg_ux", None)
    if orig_edit is None:
        orig_edit = cls.edit_message
        cls._orig_edit_message_tg_ux = orig_edit

        def _wrap_edit(oe: Any) -> Any:
            async def clean_edit_message(self: Any, chat_id: str, message_id: str, content: str, *, finalize: bool = False, metadata: Optional[Dict[str, Any]] = None) -> Any:
                if content:
                    content = clean_telegram_content(content)
                return await oe(self, chat_id, message_id, content, finalize=finalize, metadata=metadata)
            return clean_edit_message

        cls.edit_message = _wrap_edit(orig_edit)


def _install_telegram_adapter_hook(ctx: Any) -> None:
    """Wrap TelegramAdapter format_message, send, edit_message, and emit_warning to clean emojis and notices."""
    for cls in _find_telegram_adapter_classes():
        _hook_adapter_class(cls)

    # 1. Hook BasePlatformAdapter.emit_warning so system notices (hygiene, gateway restart) are cleaned
    try:
        from gateway.platforms.base import BasePlatformAdapter
        orig_emit = getattr(BasePlatformAdapter, "_orig_emit_warning_tg_ux", None)
        if orig_emit is None:
            orig_emit = BasePlatformAdapter.emit_warning
            BasePlatformAdapter._orig_emit_warning_tg_ux = orig_emit

            async def clean_emit_warning(self: Any, chat_id: str, content: str, *args: Any, **kwargs: Any) -> Any:
                if content and getattr(self, "name", "") == "telegram":
                    content = clean_telegram_content(content)
                return await orig_emit(self, chat_id, content, *args, **kwargs)

            BasePlatformAdapter.emit_warning = clean_emit_warning
    except Exception:
        pass

    # 2. Hook platform_registry.create_adapter so dynamically materialized Telegram adapters get hooked
    try:
        from gateway.platform_registry import platform_registry
        orig_create = getattr(platform_registry, "_orig_create_adapter_tg_ux", None)
        if orig_create is None:
            orig_create = platform_registry.create_adapter
            platform_registry._orig_create_adapter_tg_ux = orig_create

            def clean_create_adapter(name: str, config: Any, *args: Any, **kwargs: Any) -> Any:
                adapter = orig_create(name, config, *args, **kwargs)
                if name == "telegram" and adapter is not None:
                    _hook_adapter_class(type(adapter))
                return adapter

            platform_registry.create_adapter = clean_create_adapter
    except Exception:
        pass

    def _uninstall_adapter_hook() -> None:
        for c in _find_telegram_adapter_classes():
            if hasattr(c, "_orig_format_message_tg_ux"):
                c.format_message = getattr(c, "_orig_format_message_tg_ux")
            if hasattr(c, "_orig_send_tg_ux"):
                c.send = getattr(c, "_orig_send_tg_ux")
            if hasattr(c, "_orig_edit_message_tg_ux"):
                c.edit_message = getattr(c, "_orig_edit_message_tg_ux")
        try:
            from gateway.platforms.base import BasePlatformAdapter
            if hasattr(BasePlatformAdapter, "_orig_emit_warning_tg_ux"):
                BasePlatformAdapter.emit_warning = getattr(BasePlatformAdapter, "_orig_emit_warning_tg_ux")
        except Exception:
            pass
        try:
            from gateway.platform_registry import platform_registry
            if hasattr(platform_registry, "_orig_create_adapter_tg_ux"):
                platform_registry.create_adapter = getattr(platform_registry, "_orig_create_adapter_tg_ux")
        except Exception:
            pass

    if hasattr(ctx, "on_unload"):
        ctx.on_unload(_uninstall_adapter_hook)


def _transform_llm_output_hook(response_text: str, platform: Any = None, **kwargs: Any) -> Optional[str]:
    """Hook transform_llm_output to sanitize LaTeX and emojis before final delivery."""
    if getattr(platform, "value", platform) == "telegram" and response_text:
        cleaned = clean_telegram_content(response_text)
        if cleaned != response_text:
            return cleaned
    return None


def register(ctx: Any) -> None:
    ctx.register_tool(
        name="telegram_send_card",
        toolset="telegram_ux",
        schema=CARD_SCHEMA,
        handler=card_handler,
    )
    ctx.register_tool(
        name="telegram_send_status",
        toolset="telegram_ux",
        schema=STATUS_SCHEMA,
        handler=status_handler,
    )
    _install_turnrunner_hook(ctx)
    _install_telegram_adapter_hook(ctx)
    if hasattr(ctx, "register_hook"):
        ctx.register_hook("transform_llm_output", _transform_llm_output_hook)

