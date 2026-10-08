from app.excel_loader import load_workflows
from app.graph import run_agent
from app.models import Workflow
from pathlib import Path


def test_inventory_request_runs_traceable_workflow():
    workflow = Workflow(id="inventory-restock", name="Inventory Restock", description="Check inventory and find items needing restock", steps=["Fetch inventory", "Check stock threshold", "Identify products"], tools=["fetch_inventory", "check_stock_threshold"])
    result = run_agent("Check today's inventory and identify products that need restocking", [workflow])
    assert result.selected_workflow == "Inventory Restock"
    assert len(result.steps_executed) == 3
    assert result.final_output


def test_loader_reads_row_workflows(tmp_path):
    from openpyxl import Workbook
    file = tmp_path / "workflows.xlsx"
    book = Workbook(); sheet = book.active
    sheet.append(["Workflow Name", "Description", "Required Steps", "Tools/APIs Required", "Expected Output"])
    sheet.append(["Leave Request", "Process employee leave", "Validate request; Update leave balance", "update_record; send_notification", "Leave status"])
    book.save(file)
    workflows = load_workflows(file)
    assert workflows[0].name == "Leave Request"
    assert workflows[0].steps == ["Validate request", "Update leave balance"]


def test_all_supplied_workflows_load_and_execute():
    workbook = Path(__file__).parents[1] / "AI_Agent_Workflow_Assessment (1).xlsx"
    workflows = load_workflows(workbook)
    assert len(workflows) == 10
    assert {w.id for w in workflows} == {f"WF{i:03d}" for i in range(1, 11)}

    requests = [
        ("Which products need restocking?", "WF001"),
        ("Find products where vendor price differs by more than 10%.", "WF002"),
        ("Process this vendor spreadsheet and show invalid rows.", "WF003"),
        ("Generate SEO content for this product.", "WF004"),
        ("Where is order ORD-1001?", "WF005"),
        ("Find likely duplicate products in the catalog.", "WF006"),
        ("Create a campaign brief for the new collection.", "WF007"),
        ("Classify these keywords and map them to pages.", "WF008"),
        ("Assign this urgent task to the best available developer.", "WF009"),
        ("Which workflows are failing most often?", "WF010"),
    ]
    by_name = {workflow.name: workflow.id for workflow in workflows}
    for request, expected_id in requests:
        result = run_agent(request, workflows)
        assert by_name[result.selected_workflow] == expected_id
        assert result.steps_executed
        assert result.final_output


def test_unrelated_request_returns_no_workflow():
    workflows = load_workflows(Path(__file__).parents[1] / "AI_Agent_Workflow_Assessment (1).xlsx")
    result = run_agent("Write a Python program to reverse a linked list.", workflows)
    assert result.selected_workflow is None


def test_content_and_campaign_requirements_control_execution():
    workflows = load_workflows(Path(__file__).parents[1] / "AI_Agent_Workflow_Assessment (1).xlsx")
    blocked = run_agent("Generate SEO content for this product.", workflows)
    assert "I need the following information" in blocked.final_output
    assert len(blocked.steps_executed) == 1

    content = run_agent("Generate content for Classic Blue Cotton Shirt. Category: shirts. Material: cotton. Color: blue. Target audience: men.", workflows)
    assert "Classic Blue Cotton Shirt" in content.final_output
    assert len(content.steps_executed) > 1

    campaign = run_agent("Create a campaign brief. Goal: increase sales. Dates: October 10-20.", workflows)
    assert "increase sales" in campaign.final_output


def test_workflow_scoped_tools_and_input_sensitive_assignment():
    workflows = load_workflows(Path(__file__).parents[1] / "AI_Agent_Workflow_Assessment (1).xlsx")
    duplicates = run_agent("Find likely duplicate products in the catalog.", workflows)
    assert "order_lookup" not in [trace.tool for trace in duplicates.steps_executed]

    assignment = run_agent("Assign this urgent task requiring advanced Rust and Kubernetes expertise. Deadline: tomorrow.", workflows)
    assert "Ravi Patel" in assignment.final_output


def test_keyword_workflow_removes_duplicates_and_classifies_intent():
    workflows = load_workflows(Path(__file__).parents[1] / "AI_Agent_Workflow_Assessment (1).xlsx")
    result = run_agent("Classify these keywords and map them to pages.", workflows)
    report = result.data["artifacts"]["keyword_report"]
    assert len(report) == 2
    assert report[0]["intent"] == "transactional"
    assert report[0]["target_page"] == "/t-shirts"


def test_order_lookup_and_performance_condition_use_actual_artifacts():
    workflows = load_workflows(Path(__file__).parents[1] / "AI_Agent_Workflow_Assessment (1).xlsx")
    order = run_agent("Where is order ORD-1001?", workflows)
    assert order.data["artifacts"]["found"] is True
    assert "No matching record" not in order.final_output

    performance = run_agent("Which workflows are failing most often?", workflows)
    assert performance.data["artifacts"]["failure_rate"] == 25.0
    assert any("failure rate" in trace.step.lower() and trace.status == "completed" for trace in performance.steps_executed)


def test_simulated_vendor_file_and_generated_outputs():
    workflows = load_workflows(Path(__file__).parents[1] / "AI_Agent_Workflow_Assessment (1).xlsx")
    vendor = run_agent("Process this vendor spreadsheet and show invalid rows.", workflows)
    assert "invalid" in vendor.final_output.lower()
    assert len(vendor.data["artifacts"]["invalid_rows"]) == 2

    content = run_agent("Generate content for Classic Blue Cotton Shirt. Category: shirts. Material: cotton. Color: blue. Target audience: men.", workflows)
    assert "seo_title" in content.final_output

    assignment = run_agent("Assign this urgent task requiring advanced Rust and Kubernetes expertise. Deadline: tomorrow.", workflows)
    assert assignment.data["artifacts"]["priority"] == "urgent"


def test_new_workflow_uses_generic_excel_driven_execution_without_code_change():
    # This is the scalability proof: WF011 enters through Excel only. The
    # production selector/graph/tools are unchanged and do not mention WF011.
    from openpyxl import Workbook
    workbook_file = Path(__file__).parents[1] / "tests" / "_wf011_demo.xlsx"
    book = Workbook(); sheet = book.active; sheet.title = "Workflows"
    sheet.append(["Workflow_ID", "Workflow_Name", "Trigger", "Inputs", "Steps", "Decision_Logic", "Tools_Required", "Expected_Output"])
    sheet.append(["WF011", "Compliance Case Check", "User asks for a compliance review", "Case ID; Review date", "Read case → Validate case → Generate review summary", "If required information is missing, request it", "CSV reader; data validation; reporting", "Compliance review summary"])
    book.save(workbook_file)
    try:
        workflows = load_workflows(workbook_file)
        result = run_agent("Check case CASE-44. Review date: October 10 to October 20.", workflows)
    finally:
        workbook_file.unlink(missing_ok=True)
    assert result.selected_workflow == "Compliance Case Check"
    assert [trace.tool for trace in result.steps_executed[:3]] == ["source_reader", "analyzer", "reporter"]
    assert "Compliance review summary" in result.final_output
