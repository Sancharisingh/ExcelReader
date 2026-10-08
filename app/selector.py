from __future__ import annotations

import json
import os
import re
from typing import Callable

from rapidfuzz import fuzz

from .models import Workflow

STOP_WORDS = {"a", "an", "and", "are", "can", "check", "for", "i", "is", "it", "list", "me", "my", "of", "please", "process", "show", "the", "this", "to", "what", "which", "with", "you"}


def _tokens(text: str) -> set[str]:
    aliases = {"failing": "fail", "failure": "fail", "failed": "fail", "restocking": "restock", "prices": "price", "products": "product", "workflows": "workflow", "keywords": "keyword"}
    result = set()
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        token = aliases.get(token, token)
        if token.endswith("s") and len(token) > 4:
            token = token[:-1]
        if len(token) > 2 and token not in STOP_WORDS:
            result.add(token)
    return result


def _llm() -> Callable[[str], str] | None:
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    try:
        if provider == "gemini" and os.getenv("GEMINI_API_KEY"):
            from langchain_google_genai import ChatGoogleGenerativeAI
            client = ChatGoogleGenerativeAI(model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"), temperature=0)
        elif provider == "groq" and os.getenv("GROQ_API_KEY"):
            from langchain_groq import ChatGroq
            client = ChatGroq(model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), temperature=0)
        else:
            return None
        return lambda prompt: str(client.invoke(prompt).content)
    except ImportError:
        return None


class WorkflowSelector:
    def __init__(self, workflows: list[Workflow]) -> None:
        self.workflows, self.call_llm = workflows, _llm()

    def select(self, request: str) -> tuple[Workflow | None, str]:
        if self.call_llm:
            catalog = [{"id": w.id, "name": w.name, "trigger": w.description, "inputs": w.inputs} for w in self.workflows]
            prompt = ("Select a workflow only when the request clearly matches one. Return ONLY JSON: "
                      '{"workflow_id": "one permitted ID or null", "confidence": 0.0, "reason": "short reason"}. '
                      f"WORKFLOWS={json.dumps(catalog)}\nREQUEST={request}")
            try:
                chosen = json.loads(self.call_llm(prompt).replace("```json", "").replace("```", "").strip())
                match = next((w for w in self.workflows if w.id == chosen.get("workflow_id")), None)
                confidence = float(chosen.get("confidence", 0))
                if match and confidence >= 0.70:
                    return match, f"Selected by LLM with confidence {confidence:.0%}: {chosen.get('reason') or 'clear workflow match.'}"
                if match:
                    return None, f"Best LLM match confidence ({confidence:.0%}) is below the 70% execution threshold."
                if chosen.get("workflow_id") is None:
                    return None, str(chosen.get("reason") or "No workflow applies to this request.")
            except Exception:
                pass
        request_terms = _tokens(request)
        scored: list[tuple[float, int, int, Workflow]] = []
        for workflow in self.workflows:
            catalog = " ".join([workflow.name, workflow.description, *workflow.inputs, *workflow.steps])
            overlap = len(request_terms & _tokens(catalog))
            name_overlap = len(request_terms & _tokens(f"{workflow.name} {workflow.description}"))
            score = fuzz.token_set_ratio(request.lower(), catalog.lower())
            scored.append((score, overlap, name_overlap, workflow))
        score, overlap, name_overlap, match = max(scored, key=lambda item: (item[1], item[2], item[0]))
        # False positives are more harmful than asking for clarification. A request
        # needs a clear name/trigger term or at least three catalogue terms.
        if (name_overlap == 0 and overlap < 3) or (name_overlap == 0 and score < 30):
            return None, "No workflow clearly matches this request. Please provide a business request covered by the workflow catalogue."
        return match, f"Selected by offline relevance: {overlap} matching business term(s), score {score:.0f}."
