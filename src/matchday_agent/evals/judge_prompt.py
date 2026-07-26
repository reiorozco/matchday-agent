"""LLM-as-judge prompt for the correctness evaluator.

The judge is Gemini (NOT Groq) to avoid self-judging bias — the agent's
primary provider is Groq per docs/decisions.md § 0.1. Gemini's free tier
is a separate quota pool from Groq's daily TPD limit.
"""

from __future__ import annotations

JUDGE_MODEL_ID = "google_genai:gemini-3.5-flash"

JUDGE_PROMPT_TEMPLATE = """You are evaluating a football-analyst agent that answers in Spanish.

USER QUERY:
{input}

REFERENCE ANSWER (gold):
{reference_summary}

AGENT OUTPUT:
{output}

Score the agent output on correctness against the reference on a 1-5 scale:
1 = wrong or hallucinated stats
2 = mostly incorrect
3 = partially correct with gaps
4 = mostly correct, minor omissions
5 = fully correct + complete

Return ONLY valid JSON (no markdown fence, no prose):
{{"score": <int 1-5>, "reasoning": "<one sentence>"}}"""
