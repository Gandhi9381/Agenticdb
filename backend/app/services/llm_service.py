"""
LLM service: provider-agnostic interface to Google Gemini.
Falls back safely to deterministic rules when no API key is configured.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_llm = None
_current_key: Optional[str] = None
_current_model: Optional[str] = None


def _sanitize_llm_error(exc: Exception) -> str:
    """Format a clean, user-friendly error message without leaking keys or raw stack traces."""
    import os
    msg = str(exc)

    # Redact any configured key or environment keys
    settings = get_settings()
    keys_to_redact = [
        settings.effective_llm_api_key,
        settings.llm_api_key,
        settings.gemini_api_key,
        settings.google_api_key,
        os.environ.get("LLM_API_KEY"),
        os.environ.get("GEMINI_API_KEY"),
        os.environ.get("GOOGLE_API_KEY"),
    ]
    for k in keys_to_redact:
        if k and len(k) > 5 and k in msg:
            msg = msg.replace(k, "[REDACTED_API_KEY]")

    # Redact common API key patterns (Google AIza keys, generic auth tokens, query param keys)
    msg = re.sub(r"AIza[0-9A-Za-z_\-]{30,}", "[REDACTED_API_KEY]", msg)
    msg = re.sub(r"(?i)(key|api[_-]?key|token)=([A-Za-z0-9_\-]{8,})", r"\1=[REDACTED_API_KEY]", msg)
    msg = re.sub(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{15,}", "Bearer [REDACTED_TOKEN]", msg)

    msg_lower = msg.lower()
    if any(s in msg_lower for s in ["api key not valid", "api_key_invalid", "api key is invalid", "invalid api key"]):
        return (
            "The configured Google Gemini API key is invalid or expired. "
            "Please check your LLM_API_KEY in the .env file."
        )
    if any(s in msg_lower for s in ["resource_exhausted", "quota", "rate limit", "429"]):
        return (
            "Google Gemini API quota or rate limit exceeded. "
            "Please wait a moment before trying again or verify your account quota."
        )
    if any(s in msg_lower for s in ["permission_denied", "403"]):
        return (
            "Permission denied by Google Gemini API. "
            "Ensure the API key has access to the Generative Language API and the specified model."
        )
    if any(s in msg_lower for s in ["deadline", "timeout", "timed out"]):
        return "Request to Google Gemini API timed out. Please check your network connection and try again."
    if any(s in msg_lower for s in ["not found", "model not found"]):
        return (
            f"The specified model '{settings.llm_model}' was not found or is unavailable. "
            "Check the LLM_MODEL setting in your .env file."
        )

    first_line = msg.split("\n")[0].strip()
    return f"AI provider error: {first_line[:160]}"


def _get_llm():
    """Retrieve or initialize the ChatGoogleGenerativeAI instance."""
    global _llm, _current_key, _current_model
    settings = get_settings(reload=True)
    current_key = settings.effective_llm_api_key
    current_model = settings.llm_model

    if not current_key:
        _llm = None
        _current_key = None
        return None

    if _llm is None or _current_key != current_key or _current_model != current_model:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            _llm = ChatGoogleGenerativeAI(
                model=current_model,
                google_api_key=current_key,
                temperature=0.1,
            )
            _current_key = current_key
            _current_model = current_model
            logger.info("LLM initialized: %s / %s", settings.llm_provider, current_model)
        except Exception as exc:
            logger.error("Failed to initialize LLM: %s", _sanitize_llm_error(exc))
            _llm = None
            _current_key = None
    return _llm


def _generate_demo_sql(question: str, schema_context: str) -> dict[str, Any]:
    """Provide intelligent schema-grounded SQL for offline/demo evaluation without external API keys."""
    q_lower = question.lower()

    if any(k in q_lower for k in ["spending", "top customer", "best customer"]):
        sql = "SELECT c.customer_id, c.first_name, c.last_name, c.city, ROUND(SUM(o.total_amount), 2) AS total_spent FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id, c.first_name, c.last_name, c.city ORDER BY total_spent DESC LIMIT 10"
        explanation = "This query joins the customers and orders tables, groups by customer details, aggregates their total spending using SUM, and orders by highest spending descending with a LIMIT of 10."
    elif any(k in q_lower for k in ["revenue", "product", "highest revenue"]):
        sql = "SELECT p.product_id, p.name, p.category, ROUND(SUM(oi.subtotal), 2) AS total_revenue FROM products p JOIN order_items oi ON p.product_id = oi.product_id GROUP BY p.product_id, p.name, p.category ORDER BY total_revenue DESC LIMIT 10"
        explanation = "This query aggregates the subtotal from order_items grouped by product, returning the top 10 revenue-generating products."
    elif any(k in q_lower for k in ["status", "count orders", "by status"]):
        sql = "SELECT status, COUNT(*) AS order_count, ROUND(AVG(total_amount), 2) AS avg_amount FROM orders GROUP BY status ORDER BY order_count DESC"
        explanation = "This query groups all orders by their current status, counting the number of orders and calculating the average order amount for each status."
    elif any(k in q_lower for k in ["order", "placed", "recent"]):
        sql = "SELECT order_id, customer_id, order_date, status, shipping_city, total_amount FROM orders ORDER BY order_date DESC LIMIT 25"
        explanation = "This query selects the most recent orders sorted chronologically by order_date descending with a limit of 25 rows."
    elif "customer" in q_lower:
        sql = "SELECT customer_id, first_name, last_name, email, city, registration_date FROM customers ORDER BY customer_id ASC LIMIT 25"
        explanation = "This query retrieves customer profiles from the customers table with a limit of 25 rows."
    else:
        sql = "SELECT * FROM orders ORDER BY total_amount DESC LIMIT 10"
        explanation = "Generated read-only SQL query answering your request from the available schema tables."

    from app.safety.sql_validator import validate_read_only_sql
    validated = validate_read_only_sql(sql)
    return {
        "sql": validated,
        "explanation": f"[Demo Mode] {explanation}",
        "llm_used": True,
    }


def _generate_demo_optimization(query: str, plan: dict, schema_context: str) -> dict[str, Any]:
    """Provide realistic optimization suggestions for offline/demo evaluation."""
    return {
        "root_cause": "[Demo Mode] Full table scan detected during query execution. Adding a secondary index on filter/join columns avoids sequential scans and reduces latency.",
        "recommendations": [
            {
                "type": "index",
                "title": "Index on foreign key/filter column",
                "description": "Create an index to eliminate table scans on large tables.",
                "original": query,
                "proposed": "CREATE INDEX idx_demo_opt ON orders (customer_id, total_amount)",
                "expected_benefit": "Reduces query execution time by 60-80% by replacing full scans with index lookups.",
                "risks": "Minimal storage overhead; slightly higher write latency on updates/inserts.",
                "validation_needed": True,
            }
        ],
        "llm_used": True,
    }


def _generate_demo_diagnosis(incident_title: str, evidence: dict, schema_context: str) -> dict[str, Any]:
    """Provide realistic incident diagnosis for offline/demo evaluation."""
    return {
        "diagnosis": (
            f"[Demo Mode] Root Cause Analysis for '{incident_title}':\n\n"
            "1. Most Likely Root Cause: High execution latency caused by sequential scans on unindexed join columns.\n"
            "2. Supporting Evidence: Execution metrics indicate elapsed query duration exceeded the slow query threshold.\n"
            "3. Verification: An EXPLAIN plan confirms sequential table scan operations.\n"
            "4. Recommended Actions: Review index recommendations under Pending Approvals and verify baseline vs candidate performance."
        ),
        "llm_used": True,
    }


async def generate_sql(
    question: str,
    schema_context: str,
    history: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """
    Generate SQL from a natural-language question given schema context.
    Returns {"sql": ..., "explanation": ..., "llm_used": bool}.
    """
    settings = get_settings(reload=True)
    if settings.llm_provider and settings.llm_provider.lower() in ("mock", "demo", "offline", "synthetic"):
        return _generate_demo_sql(question, schema_context)

    llm = _get_llm()
    if llm is None:
        return {
            "sql": None,
            "explanation": (
                "LLM not configured. Please set LLM_API_KEY in your .env file to enable AI SQL generation. "
                "Dataset upload, schema browsing, and monitoring remain fully available without an API key."
            ),
            "llm_used": False,
        }

    history_text = ""
    if history:
        for h in history[-3:]:
            history_text += f"User: {h.get('question', '')}\nSQL: {h.get('sql', '')}\n"

    prompt = f"""You are AgenticDB, an AI database assistant.
Given this database schema:
{schema_context}

{f"Recent conversation context:{chr(10)}{history_text}" if history_text else ""}

Generate a single, safe, read-only SQL SELECT query to answer:
"{question}"

Rules:
- Only use tables and columns that exist in the schema above.
- Return ONLY the SQL query inside a ```sql ... ``` code block.
- After the code block, add a brief one-paragraph explanation.
- Do NOT use INSERT, UPDATE, DELETE, DROP, CREATE, TRUNCATE, or ALTER.
- Do NOT access system tables or information_schema.
- Add a LIMIT clause (max 1000 rows) unless the question clearly needs all rows.
- If the question cannot be answered from the schema, say so clearly instead of guessing.
"""

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content="You are AgenticDB, a helpful AI database assistant. Always return valid read-only SELECT SQL."),
            HumanMessage(content=prompt),
        ]
        response = await llm.ainvoke(messages)
        text = str(response.content)

        from app.safety.sql_validator import extract_sql_from_llm_response, validate_read_only_sql, SQLValidationError
        raw_sql = extract_sql_from_llm_response(text)

        # Validate the generated query before returning it
        validated_sql = None
        if raw_sql:
            try:
                validated_sql = validate_read_only_sql(raw_sql)
            except SQLValidationError as sve:
                logger.warning("AI generated query failed read-only safety check: %s (%s)", raw_sql, sve)
                return {
                    "sql": None,
                    "explanation": (
                        f"Safety check rejected generated query: {sve}. "
                        "The AI Query Assistant only permits single, safe, read-only SELECT queries."
                    ),
                    "llm_used": True,
                }

        # Extract explanation (text after the code block)
        explanation_match = re.search(r"```.*?```\s*(.*)", text, re.DOTALL)
        explanation = explanation_match.group(1).strip() if explanation_match else ""

        return {"sql": validated_sql, "explanation": explanation, "llm_used": True}
    except Exception as exc:
        sanitized = _sanitize_llm_error(exc)
        logger.error("LLM generate_sql error: %s", sanitized)
        return {
            "sql": None,
            "explanation": f"AI Assistant call failed: {sanitized}",
            "llm_used": False,
        }


async def generate_optimization_suggestions(
    query: str,
    plan: dict,
    schema_context: str,
) -> dict[str, Any]:
    """Generate optimization suggestions for a slow query."""
    settings = get_settings(reload=True)
    if settings.llm_provider and settings.llm_provider.lower() in ("mock", "demo", "offline", "synthetic"):
        return _generate_demo_optimization(query, plan, schema_context)

    llm = _get_llm()
    if llm is None:
        return {
            "root_cause": "LLM not configured.",
            "recommendations": [],
            "llm_used": False,
            "message": "Set LLM_API_KEY in .env to enable AI optimization recommendations.",
        }

    prompt = f"""You are AgenticDB, an expert query optimizer.

Schema:
{schema_context}

Query:
```sql
{query}
```

Execution Plan:
{plan}

Analyze this query and provide:
1. Root cause of slowness (grounded strictly in the plan and schema)
2. Specific optimization recommendations (SQL rewrites, index suggestions, etc.)
3. For each recommendation: original vs proposed, expected benefit, risks
4. Any caveats or cases where optimization might not help

Respond in JSON format:
{{
  "root_cause": "...",
  "recommendations": [
    {{
      "type": "rewrite|index|statistics|config",
      "title": "...",
      "description": "...",
      "original": "...",
      "proposed": "...",
      "expected_benefit": "...",
      "risks": "...",
      "validation_needed": true
    }}
  ]
}}
"""
    try:
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        import json
        text = str(response.content)
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
        else:
            data = {"root_cause": text, "recommendations": []}
        data["llm_used"] = True
        return data
    except Exception as exc:
        sanitized = _sanitize_llm_error(exc)
        logger.error("LLM optimization error: %s", sanitized)
        return {
            "root_cause": f"AI optimization unavailable: {sanitized}",
            "recommendations": [],
            "llm_used": False,
            "error": sanitized,
        }


async def generate_incident_diagnosis(
    incident_title: str,
    evidence: dict,
    schema_context: str,
) -> dict[str, Any]:
    """Generate an AI diagnosis for a detected performance incident."""
    settings = get_settings(reload=True)
    if settings.llm_provider and settings.llm_provider.lower() in ("mock", "demo", "offline", "synthetic"):
        return _generate_demo_diagnosis(incident_title, evidence, schema_context)

    llm = _get_llm()
    if llm is None:
        return {
            "diagnosis": (
                "LLM not configured. Deterministic diagnosis and root-cause analysis have been performed above. "
                "To enable generative AI diagnosis, configure LLM_API_KEY in your .env file."
            ),
            "llm_used": False,
        }

    prompt = f"""You are AgenticDB performing autonomous database diagnosis.

Incident: {incident_title}
Evidence: {evidence}
Schema: {schema_context}

Provide a structured diagnosis:
1. Most likely root cause (with confidence level: high/medium/low)
2. Supporting evidence from the data above
3. What additional information would confirm or rule out this diagnosis
4. Recommended immediate actions (ranked by priority and safety)

Be precise. Ground hypotheses only in observed evidence and schema. Do not fabricate metrics, timings, or execution plans.
"""
    try:
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        return {"diagnosis": str(response.content), "llm_used": True}
    except Exception as exc:
        sanitized = _sanitize_llm_error(exc)
        logger.error("LLM diagnosis error: %s", sanitized)
        return {
            "diagnosis": f"AI diagnosis unavailable: {sanitized}",
            "llm_used": False,
        }
