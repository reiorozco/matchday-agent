"""HTML landing for the root route (content-negotiated).

Browsers (``Accept: text/html``) get a friendly landing that points to the
live chat demo; API clients (curl / ``Accept: */*`` or ``application/json``)
keep the JSON metadata response. Rationale in ``docs/decisions.md`` § 8.13 —
a raw JSON index reads as "broken" to a non-engineer clicking the live URL,
so humans get a page and machines keep the contract.

The template is placeholder-substituted (not f-string / ``str.format``) so the
inline CSS braces don't need escaping.
"""

# This module is a self-contained HTML/CSS template string; the long lines in
# the template are intentional and not worth wrapping.
# ruff: noqa: E501
from __future__ import annotations

import html
import os

# Where a human should actually try the agent (the SvelteKit chat surface that
# consumes this agent's SSE stream). Overridable via env for previews/staging.
CHAT_DEMO_URL: str = os.environ.get(
    "CHAT_DEMO_URL", "https://matchday-mcp-web.vercel.app/chat"
)
REPO_URL: str = os.environ.get(
    "REPO_URL", "https://github.com/reiorozco/matchday-agent"
)

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="color-scheme" content="dark" />
<title>matchday-agent — Football-analyst AI agent</title>
<meta name="description" content="A LangGraph agent orchestrating MCP tools + Wikipedia RAG, streaming its reasoning over SSE." />
<style>
  :root {
    --ground: #08110c; --stripe: #0c1a12; --grass: #34d399; --grass-deep: #059669;
    --ink: #f0fdf4; --muted: #9db8aa; --chip-bd: rgba(52,211,153,0.30);
    --chip-ink: #cff6e4;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0; color: var(--ink);
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    background:
      radial-gradient(900px 520px at 15% -10%, rgba(224,252,231,0.10), transparent 60%),
      repeating-linear-gradient(90deg, var(--ground) 0 92px, var(--stripe) 92px 184px);
    display: grid; place-items: center; padding: 40px 22px;
  }
  main { width: 100%; max-width: 620px; }
  .eyebrow {
    font-family: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace;
    font-size: 14px; letter-spacing: 0.03em; color: var(--grass);
    display: inline-flex; align-items: center; gap: 9px; margin-bottom: 18px;
  }
  .dot {
    width: 9px; height: 9px; border-radius: 50%; background: var(--grass);
    box-shadow: 0 0 0 4px rgba(52,211,153,0.18), 0 0 14px 1px rgba(52,211,153,0.55);
    animation: pulse 2.4s ease-in-out infinite;
  }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.45; } }
  @media (prefers-reduced-motion: reduce) { .dot { animation: none; } }
  h1 {
    margin: 0; font-size: clamp(40px, 9vw, 66px); font-weight: 900;
    letter-spacing: -0.035em; line-height: 0.95; text-wrap: balance;
  }
  h1 .accent { color: var(--grass); }
  .tagline { margin: 12px 0 0; font-size: 21px; font-weight: 600; color: #dcefe4; }
  .lead { margin: 16px 0 0; font-size: 16px; line-height: 1.6; color: var(--muted); }
  .cta-row { margin: 30px 0 0; display: flex; flex-wrap: wrap; align-items: center; gap: 16px; }
  .cta {
    display: inline-flex; align-items: center; gap: 10px;
    background: var(--grass); color: #04120b; text-decoration: none;
    font-weight: 700; font-size: 17px; padding: 14px 26px; border-radius: 12px;
    transition: transform .12s ease, box-shadow .12s ease, background .12s ease;
    box-shadow: 0 6px 24px rgba(52,211,153,0.28);
  }
  .cta:hover { background: #4ade80; transform: translateY(-1px); box-shadow: 0 10px 30px rgba(52,211,153,0.38); }
  .cta:focus-visible { outline: 3px solid #a7f3d0; outline-offset: 3px; }
  .ghlink {
    color: var(--muted); text-decoration: none; font-size: 15px;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    border-bottom: 1px solid transparent; transition: color .12s, border-color .12s;
  }
  .ghlink:hover { color: var(--ink); border-color: var(--chip-bd); }
  .ghlink:focus-visible { outline: 2px solid var(--chip-bd); outline-offset: 3px; border-radius: 3px; }
  .note {
    margin: 14px 0 0; font-size: 13px; color: #6f8a7c;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
  }
  .tools { margin: 34px 0 0; display: flex; flex-wrap: wrap; gap: 9px; }
  .tool {
    font-family: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace;
    font-size: 13.5px; color: var(--chip-ink);
    padding: 6px 12px; border: 1px solid var(--chip-bd); border-radius: 999px;
  }
  footer {
    margin: 34px 0 0; padding-top: 18px; border-top: 1px solid rgba(52,211,153,0.14);
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 12.5px; line-height: 1.7; color: #647a6d;
  }
  footer b { color: #8fae9f; font-weight: 600; }
</style>
</head>
<body>
  <main>
    <span class="eyebrow"><span class="dot"></span> LangGraph agent · live</span>
    <h1>matchday<span class="accent">-agent</span></h1>
    <p class="tagline">Football-analyst AI agent</p>
    <p class="lead">Ask about standings, fixtures, top scorers, or the history of a rivalry. The agent orchestrates live football tools over MCP plus a Wikipedia RAG layer, and streams its reasoning to you in real time.</p>

    <div class="cta-row">
      <a class="cta" href="__CHAT_URL__">Try the live chat &rarr;</a>
      <a class="ghlink" href="__REPO_URL__">source on GitHub</a>
    </div>
    <p class="note">First reply can take ~20s while the agent wakes up (scale-to-zero); ~2-3s once warm.</p>

    <div class="tools">__TOOLS__</div>

    <footer>
      Model: <b>__MODEL__</b> &middot; v__VERSION__<br />
      This page <em>is</em> the agent's HTTP API. Request it with <b>Accept: application/json</b> (or <code>curl</code>) for the machine-readable index &mdash; see the README for the SSE contract.
    </footer>
  </main>
</body>
</html>"""


def render_landing(
    *,
    version: str,
    model: str,
    tools: list[str],
    chat_url: str = CHAT_DEMO_URL,
    repo_url: str = REPO_URL,
) -> str:
    """Render the browser landing page as a full HTML document."""
    chips = "".join(f'<span class="tool">{html.escape(t)}</span>' for t in tools)
    return (
        _TEMPLATE.replace("__TOOLS__", chips)
        .replace("__CHAT_URL__", html.escape(chat_url, quote=True))
        .replace("__REPO_URL__", html.escape(repo_url, quote=True))
        .replace("__MODEL__", html.escape(model))
        .replace("__VERSION__", html.escape(version))
    )
