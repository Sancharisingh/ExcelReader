from __future__ import annotations

from typing import Any, TypedDict
from langgraph.graph import END, START, StateGraph

from .models import AgentResult, StepTrace, Workflow
from .selector import WorkflowSelector
from .tools import evaluate_condition, extract_inputs, missing_required_inputs, render_result, resolve_tool


class AgentState(TypedDict, total=False):
    request: str
    workflow: Workflow | None
    selection_reason: str
    traces: list[StepTrace]
    data: dict[str, Any]
    result: AgentResult


def build_agent(workflows: list[Workflow]):
    selector = WorkflowSelector(workflows)

    def select_workflow(state: AgentState) -> dict[str, Any]:
        workflow, reason = selector.select(state["request"])
        inputs = extract_inputs(workflow, state["request"]) if workflow else {}
        return {"workflow": workflow, "selection_reason": reason, "traces": [], "data": {"request": state["request"], "workflow_id": workflow.id if workflow else None, "inputs": inputs, "expected_output": workflow.expected_output if workflow else "", "completed_steps": []}}

    def execute_steps(state: AgentState) -> dict[str, Any]:
        workflow = state.get("workflow")
        if not workflow:
            return {}
        data, traces = dict(state["data"]), list(state["traces"])
        missing = missing_required_inputs(workflow, data["inputs"])
        if missing:
            data["blocked_by_missing_inputs"] = missing
            traces.append(StepTrace(step="Validate required inputs", status="skipped", detail="Missing: " + ", ".join(missing)))
            return {"data": data, "traces": traces}
        for index, step in enumerate(workflow.steps):
            tool_name, tool = resolve_tool(workflow, step)
            try:
                data.update(tool(step, data))
                data["completed_steps"].append(step)
                traces.append(StepTrace(step=step, status="completed", tool=tool_name, detail=f"{tool_name} completed within the selected workflow scope."))
            except Exception as exc:
                traces.append(StepTrace(step=step, status="failed", tool=tool_name, detail=f"{type(exc).__name__}: {exc}"))
                break
            for condition in workflow.conditions:
                _, detail, stop = evaluate_condition(condition, data)
                if stop:
                    data["blocked_by_condition"] = detail
                    traces.append(StepTrace(step=f"Condition: {condition}", status="skipped", detail=detail))
                    return {"data": data, "traces": traces}
        for condition in workflow.conditions:
            outcome, detail, _ = evaluate_condition(condition, data)
            traces.append(StepTrace(step=f"Condition: {condition}", status="completed" if outcome else "skipped", detail=detail))
        return {"data": data, "traces": traces}

    def finalise(state: AgentState) -> dict[str, Any]:
        workflow = state.get("workflow")
        if not workflow:
            result = AgentResult(selected_workflow=None, selection_reason=state["selection_reason"], final_output="I could not find a matching workflow. Please rephrase the request.")
        else:
            data = state["data"]
            if data.get("blocked_by_missing_inputs"):
                output = "I need the following information before I can continue: " + ", ".join(data["blocked_by_missing_inputs"]) + "."
            elif data.get("blocked_by_condition"):
                output = data["blocked_by_condition"]
            else:
                output = render_result(workflow, data)
            result = AgentResult(selected_workflow=workflow.name, selection_reason=state["selection_reason"], steps_executed=state.get("traces", []), final_output=output, data=data)
        return {"result": result}

    graph = StateGraph(AgentState)
    graph.add_node("select_workflow", select_workflow)
    graph.add_node("execute_steps", execute_steps)
    graph.add_node("finalise", finalise)
    graph.add_edge(START, "select_workflow")
    graph.add_edge("select_workflow", "execute_steps")
    graph.add_edge("execute_steps", "finalise")
    graph.add_edge("finalise", END)
    return graph.compile()


def run_agent(request: str, workflows: list[Workflow]) -> AgentResult:
    return build_agent(workflows).invoke({"request": request})["result"]
