"""Generic, Excel-driven tool execution.

Tool selection is derived from the `Tools_Required` and `Steps` cells of the
selected workflow. Simulated records are configuration, not workflow code.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import mean
from typing import Any, Callable

from .models import Workflow
from .selector import _llm

Tool = Callable[[str, dict[str, Any]], dict[str, Any]]
CONFIG_PATH = Path(__file__).parents[1] / "config" / "simulated_sources.json"
SIMULATED_SOURCES: dict[str, dict[str, Any]] = json.loads(CONFIG_PATH.read_text())

# This is a reusable catalog. New Excel workflows can use these human-readable
# tool labels without a Python change; unknown labels use the safe action adapter.
TOOL_CATALOG = {
    "csv reader": "source_reader", "excel/csv parser": "source_reader", "csv/database reader": "source_reader",
    "product data reader": "source_reader", "order database/api": "source_reader", "shipment lookup": "source_reader",
    "employee/task database": "source_reader", "calculator": "analyzer", "data validation": "analyzer",
    "text similarity": "analyzer", "llm/classifier": "analyzer", "ranking logic": "analyzer",
    "llm": "text_generator", "text validation": "validator", "reporting": "reporter",
}


def _key(label: str) -> str:
    words = re.findall(r"[a-z0-9]+", label.lower())
    return "_".join(words)


def input_schema(workflow: Workflow) -> list[dict[str, str]]:
    """Turn Excel input labels into a portable input schema."""
    return [{"label": label, "key": _key(label)} for label in workflow.inputs]


def _value_after_label(request: str, label: str) -> str | None:
    names = [label, label.split()[-1], *[part.strip() for part in re.split(r"\bor\b|/", label, flags=re.I) if part.strip()]]
    for name in names:
        escaped = re.escape(name).replace(r"\ ", r"\s+")
        match = re.search(rf"(?:{escaped})\s*(?::|=|is|are)\s*([^.;\n]+)", request, re.I)
        if match:
            return match.group(1).strip()
    return None


def extract_inputs(workflow: Workflow, request: str) -> dict[str, Any]:
    """Generic extraction from the Excel-defined input labels and common identifiers."""
    values: dict[str, Any] = {}
    llm = _llm()
    if llm:
        schema = input_schema(workflow)
        prompt = ("Extract values from the request for this exact schema. Return ONLY a JSON object whose keys are the schema keys. "
                  "Use null when the request does not supply a value; do not invent facts. "
                  f"SCHEMA={json.dumps(schema)}\nREQUEST={request}")
        try:
            candidate = json.loads(llm(prompt).replace("```json", "").replace("```", "").strip())
            values = {field["key"]: candidate.get(field["key"]) for field in schema}
        except Exception:
            values = {}
    for field in input_schema(workflow):
        label, key = field["label"], field["key"]
        value = values.get(key) or _value_after_label(request, label)
        if not value and any(token in key for token in ("id", "identifier")):
            match = re.search(r"\b[A-Z]{2,}[ -]?\d+\b", request, re.I)
            value = match.group(0).upper().replace(" ", "-") if match else None
        if not value and "date" in key:
            match = re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{1,2}(?:\s*(?:-|to)\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*)?\d{1,2}\b", request, re.I)
            value = match.group(0) if match else None
        if not value and "skill" in key:
            match = re.search(r"(?:skills?|expertise)\s*(?:of|in|for|:)?\s*([a-z0-9 ,+/&-]+)", request, re.I)
            match = match or re.search(r"(?:requiring|with)\s+(.+?)\s+expertise", request, re.I)
            if match:
                value = [re.sub(r"^(?:advanced|strong|senior)\s+", "", part.strip().lower()) for part in re.split(r",|\band\b|/", match.group(1)) if part.strip()]
        if not value and "priorit" in key:
            match = re.search(r"\b(urgent|high|medium|normal|low)\s+(?:task|priority)?", request, re.I)
            value = match.group(1).lower() if match else None
        if not value and key in {"product_name", "name"}:
            match = re.search(r"\bfor\s+(.+?)(?:\.|$)", request, re.I)
            value = match.group(1).strip() if match else None
        values[key] = value
    if "attributes" in values and not values["attributes"]:
        values["attributes"] = [value for key, value in values.items() if key not in {"attributes", "request_context"} and value]
    # Product/campaign requests often give natural language rather than labels.
    # Preserve it as an explicit generic context field for LLM or text adapters.
    values["request_context"] = request
    return values


def _declared_adapters(workflow: Workflow) -> list[str]:
    adapters = [TOOL_CATALOG.get(tool.strip().lower(), "action") for tool in workflow.tools]
    return list(dict.fromkeys(adapters)) or ["action"]


def _step_intent(step: str) -> str:
    text = step.lower()
    if any(word in text for word in ("load", "read", "search", "retrieve", "detect columns")):
        return "source_reader"
    if any(word in text for word in ("validate", "normalize", "compare", "calculate", "identify", "classify", "map", "rank", "check", "flag", "group")):
        return "analyzer"
    if any(word in text for word in ("create", "generate", "summarize", "messaging", "export")):
        return "text_generator"
    return "action"


def resolve_tool(workflow: Workflow, step: str) -> tuple[str, Tool]:
    allowed = _declared_adapters(workflow)
    desired = _step_intent(step)
    name = desired if desired in allowed else ("reporter" if "reporter" in allowed and desired == "text_generator" else allowed[0])
    return name, REGISTRY[name]


def source_reader(_: str, data: dict[str, Any]) -> dict[str, Any]:
    source = SIMULATED_SOURCES.get(data["workflow_id"], {"records": []})
    records = source.get("records", [])
    artifacts = dict(data.get("artifacts", {}))
    # A reader can also perform a generic identifier lookup when the workflow
    # requests an order/customer/file identifier.
    identifier = _first_nonempty(data.get("inputs", {}), "id", "identifier", "email")
    if identifier:
        match = next((row for row in records if str(identifier).upper() in {str(value).upper() for value in row.values()}), None)
        artifacts.update({"record": match, "found": bool(match)})
    return {"source_records": records, "source": "simulated", "artifacts": artifacts}


def _first_nonempty(inputs: dict[str, Any], *terms: str) -> Any:
    for key, value in inputs.items():
        if value and any(term in key for term in terms):
            return value
    return None


def analyzer(_: str, data: dict[str, Any]) -> dict[str, Any]:
    """Apply reusable operations based on record shape, rather than workflow ID/name."""
    records, inputs = data.get("source_records", []), data["inputs"]
    artifacts = dict(data.get("artifacts", {}))
    if records and all({"current_stock", "minimum_stock"} <= set(row) for row in records):
        artifacts["matches"] = [{**row, "reorder_quantity": row["minimum_stock"] - row["current_stock"]} for row in records if row["current_stock"] < row["minimum_stock"]]
    elif records and all({"internal_price", "vendor_price"} <= set(row) for row in records):
        artifacts["matches"] = [{**row, "difference_percent": round(abs(row["vendor_price"] - row["internal_price"]) / row["internal_price"] * 100, 1)} for row in records if abs(row["vendor_price"] - row["internal_price"]) / row["internal_price"] > .10]
    elif records and all({"sku", "product_name"} <= set(row) for row in records):
        invalid = [row for row in records if not row["sku"] or not row["product_name"]]
        if invalid:
            artifacts["invalid_rows"] = invalid
            artifacts["valid_rows"] = [row for row in records if row not in invalid]
        else:
            groups: dict[str, list[dict[str, Any]]] = {}
            for row in records: groups.setdefault(str(row["sku"]), []).append(row)
            artifacts["matches"] = [{"products": group, "confidence": "definite" if len({str(row.get('sku')) for row in group}) == 1 else "possible", "matching_fields": ["SKU"] if len({str(row.get('sku')) for row in group}) == 1 else ["name", "attributes"]} for group in groups.values() if len(group) > 1]
    elif records and all({"employee", "skills", "workload"} <= set(row) for row in records):
        required = _first_nonempty(inputs, "skill") or []
        if isinstance(required, str): required = [part.strip().lower() for part in re.split(r",|\band\b", required) if part.strip()]
        candidates = [row for row in records if set(required).issubset(set(row["skills"])) and row["workload"] < .80]
        artifacts["recommendation"] = min(candidates, key=lambda row: row["workload"]) if candidates else None
        artifacts["required_skills"] = required
        artifacts["priority"] = inputs.get("priority") or ("urgent" if "urgent" in str(inputs.get("request_context", "")).lower() else "normal")
        artifacts["deadline"] = inputs.get("deadline") or "To be confirmed"
    elif records and all("keyword" in row for row in records):
        keywords = list(dict.fromkeys(str(row["keyword"]).strip().lower() for row in records))
        lookup = {str(row["keyword"]).strip().lower(): row for row in records}
        report = []
        for keyword in keywords:
            intent = "transactional" if any(word in keyword for word in ("buy", "price", "order")) else "commercial" if any(word in keyword for word in ("best", "review", "vs")) else "informational"
            row = lookup[keyword]
            report.append({"keyword": keyword, "intent": intent, "category": row.get("category", "Unmapped"), "priority": "high" if intent == "transactional" else "medium", "target_page": row.get("target_page", "/")})
        artifacts["keyword_report"] = report
    elif records and all({"success", "seconds"} <= set(row) for row in records):
        artifacts["success_rate"] = round(sum(bool(row["success"]) for row in records) / len(records) * 100, 1)
        artifacts["failure_rate"] = round(100 - artifacts["success_rate"], 1)
        artifacts["average_execution_seconds"] = round(mean(row["seconds"] for row in records), 2)
        artifacts["errors"] = [row["error"] for row in records if row.get("error")]
    elif records:
        identifier = _first_nonempty(inputs, "id", "identifier")
        match = next((row for row in records if identifier and identifier in {str(value) for value in row.values()}), None)
        artifacts["record"] = match
        artifacts["found"] = bool(match)
    return {"artifacts": artifacts}


def validator(_: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"validation": {key: value is not None for key, value in data["inputs"].items() if key != "request_context"}}


def text_generator(_: str, data: dict[str, Any]) -> dict[str, Any]:
    fields = {key: value for key, value in data["inputs"].items() if value and key != "request_context"}
    expected = data.get("expected_output", "").lower()
    if "meta description" in expected or "seo title" in expected:
        name = fields.get("product_name") or fields.get("name") or "Product"
        category = fields.get("category") or "product"
        material = fields.get("material") or "quality materials"
        color = fields.get("color") or "versatile"
        audience = fields.get("target_audience") or "everyday use"
        return {"generated_text": json.dumps({"description": f"{name} is a {color} {material} {category} designed for {audience}.", "short_description": f"{color.title()} {material} {category} for {audience}.", "seo_title": f"{name} | {category.title()}", "meta_description": f"Discover the {name}, a {color} {material} {category} designed for {audience}."})}
    if "campaign brief" in expected:
        goal = fields.get("campaign_goal") or fields.get("goal") or "the campaign objective"
        dates = fields.get("dates") or "dates to be confirmed"
        audience = fields.get("target_audience") or "target customers"
        return {"generated_text": json.dumps({"objective": goal, "audience": audience, "timeline": dates, "messaging": f"Promote the collection to {audience} to {goal}.", "channels": ["Email", "Social media"], "checklist": ["Confirm product assortment", "Approve creative", "Schedule launch", "Monitor performance"]})}
    return {"generated_text": "Generated result using supplied details: " + (", ".join(f"{key.replace('_', ' ')}={value}" for key, value in fields.items()) or "no structured details supplied")}


def reporter(_: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"report": {"artifacts": data.get("artifacts", {}), "generated_text": data.get("generated_text")}}


def action(step: str, _: dict[str, Any]) -> dict[str, Any]:
    return {"last_action": step}


REGISTRY: dict[str, Tool] = {"source_reader": source_reader, "analyzer": analyzer, "validator": validator, "text_generator": text_generator, "reporter": reporter, "action": action}


def missing_required_inputs(workflow: Workflow, inputs: dict[str, Any]) -> list[str]:
    """Only block fields explicitly made mandatory by the Excel decision text."""
    rules = " ".join(workflow.conditions).lower()
    must_validate = "missing" in rules or "before generating" in rules or "do not invent" in rules
    if not must_validate:
        return []
    # The assignment permits API/file simulation. If a checked-in source exists
    # for this workflow, its source-reader can satisfy the file input.
    if workflow.id in SIMULATED_SOURCES and any("file" in field["key"] or "csv" in field["key"] or "xlsx" in field["key"] for field in input_schema(workflow)):
        return []
    llm = _llm()
    if llm:
        try:
            prompt = ("From the workflow conditions, identify which schema keys are mandatory before execution. "
                      "Return ONLY JSON: {\"required_keys\": [..]}. Do not infer requirements absent from conditions. "
                      f"SCHEMA={json.dumps(input_schema(workflow))}\nCONDITIONS={workflow.conditions}")
            choice = json.loads(llm(prompt).replace("```json", "").replace("```", "").strip())
            required_keys = set(choice.get("required_keys", []))
            return [field["label"] for field in input_schema(workflow) if field["key"] in required_keys and not inputs.get(field["key"])]
        except Exception:
            pass
    missing = []
    for field in input_schema(workflow):
        label, key = field["label"], field["key"]
        label_terms = set(re.findall(r"[a-z]+", label.lower()))
        referenced = not label_terms.isdisjoint(set(re.findall(r"[a-z]+", rules)))
        if (referenced or "do not invent" in rules) and not inputs.get(key):
            missing.append(label)
    return missing


def evaluate_condition(condition: str, data: dict[str, Any]) -> tuple[bool, str, bool]:
    """Generic state-based branching. Integrations can expose `found`/`recommendation` signals."""
    text, artifacts = condition.lower(), data.get("artifacts", {})
    if "no order" in text or "no record" in text:
        if "found" not in artifacts and "record" not in artifacts:
            return True, "Waiting for the record lookup step.", False
        found = artifacts.get("found", artifacts.get("record") is not None)
        return bool(found), "Record found." if found else "No matching record was found; request another identifier.", not bool(found)
    if "no suitable" in text or "escalate" in text:
        candidate = artifacts.get("recommendation", True)
        return bool(candidate), "Suitable candidate found." if candidate else "No suitable candidate exists; escalate to a human.", not bool(candidate)
    if "missing" in text:
        return True, "Required fields were validated before execution.", False
    if "failure rate" in text:
        if "success_rate" not in artifacts:
            return True, "Waiting for performance metrics.", False
        failure_rate = 100 - float(artifacts["success_rate"])
        threshold = float(re.search(r"above\s+(\d+(?:\.\d+)?)\s*%", text).group(1)) if re.search(r"above\s+(\d+(?:\.\d+)?)\s*%", text) else 10.0
        triggered = failure_rate > threshold
        return triggered, f"Failure rate is {failure_rate:.1f}% (threshold {threshold:.1f}%).", False
    if "average execution time" in text:
        if "average_execution_seconds" not in artifacts:
            return True, "Waiting for performance metrics.", False
        return True, f"Average execution time is {artifacts['average_execution_seconds']} seconds.", False
    if "flag" in text or "mark" in text:
        count = len(artifacts.get("matches", artifacts.get("invalid_rows", [])))
        return bool(count), f"Rule evaluated; {count} matching record(s).", False
    return True, "Rule evaluated using the selected workflow state.", False


def render_result(workflow: Workflow, data: dict[str, Any]) -> str:
    """Render from the selected workflow's expected-output contract, without data-key routing."""
    artifacts = data.get("artifacts", {})
    llm = _llm()
    if llm and (artifacts or data.get("generated_text")):
        try:
            prompt = ("Write a concise business result using only the supplied execution data. Do not invent facts. "
                      f"EXPECTED_OUTPUT={workflow.expected_output}\nARTIFACTS={json.dumps(artifacts, default=str)}\nGENERATED={data.get('generated_text')}")
            return llm(prompt).strip()
        except Exception:
            pass
    if "generated_text" in data:
        return f"{data['generated_text']}. Expected output: {workflow.expected_output}."
    if artifacts:
        details = []
        for name, value in artifacts.items():
            label = name.replace("_", " ").capitalize()
            if isinstance(value, list):
                entries = [", ".join(f"{key.replace('_', ' ')}: {item}" for key, item in row.items()) if isinstance(row, dict) else str(row) for row in value]
                details.append(f"{label}: " + ("; ".join(entries) or "none"))
            elif isinstance(value, dict):
                details.append(f"{label}: " + ", ".join(f"{key.replace('_', ' ')}: {item}" for key, item in value.items()))
            else:
                details.append(f"{label}: {value}")
        return f"{workflow.expected_output}. " + " | ".join(details)
    return f"{workflow.expected_output}. Steps completed: {len(data.get('completed_steps', []))}."
