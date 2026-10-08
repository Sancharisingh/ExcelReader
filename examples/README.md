# Example Requests and Results

The supplied workflow examples below use requests from the `Test_Questions` sheet in the company-provided workbook. Run any request from the repository root with:

```bash
python -m app.cli "<request>"
```

The CLI returns JSON containing `selected_workflow`, `steps_executed`, `final_output`, and structured `data`.

## Supplied workflow examples

| ID | Command | Expected result |
|---|---|---|
| WF001 | `python -m app.cli "Which products need restocking?"` | `Inventory Restock Check`; Widget A is below threshold and has reorder quantity 6. |
| WF002 | `python -m app.cli "Find products where vendor price differs by more than 10%."` | `Product Price Validation`; SKU-202 is flagged at 15%. |
| WF003 | `python -m app.cli "Process this vendor spreadsheet and show invalid rows."` | `Vendor File Processing`; two invalid rows are reported and one row is valid. |
| WF004 | `python -m app.cli "Generate SEO content for this product."` | `Product Description Generator`; missing product attributes are requested. |
| WF005 | `python -m app.cli "Where is order ORD-1001?"` | `Customer Order Status`; order is shipped and tracking is `TRK-12345`. |
| WF006 | `python -m app.cli "Find likely duplicate products in the catalog."` | `Duplicate Product Detection`; duplicate products are identified using matching fields and confidence. |
| WF007 | `python -m app.cli "Create a campaign brief for the new collection."` | `Marketing Campaign Brief`; required goal and dates are requested. |
| WF008 | `python -m app.cli "Classify these keywords and map them to pages."` | `SEO Keyword Classification`; duplicate keywords are removed and intent/pages are returned. |
| WF009 | `python -m app.cli "Assign this urgent task to the best available developer."` | `Employee Task Assignment`; best available employee is recommended. |
| WF010 | `python -m app.cli "Which workflows are failing most often?"` | `Workflow Performance Report`; success/failure rate, average time, errors, and recommendations are returned. |

## Natural-language variations

These are intentionally different from the workbook wording and demonstrate semantic routing:

```text
I want to know which items in our inventory are below the required stock level.
Please identify anything we need to replenish in the warehouse.
```

Both select `Inventory Restock Check` and identify Widget A with a reorder quantity of 6.

## Negative routing examples

```text
Can you process this for me?
Write a Python program to reverse a linked list.
```

Both return `selected_workflow: null` with a clarification message rather than executing an unrelated business workflow.

## Representative JSON result

```json
{
  "selected_workflow": "Inventory Restock Check",
  "selection_reason": "Selected by offline relevance...",
  "steps_executed": [
    {"step": "Load inventory", "status": "completed", "tool": "source_reader"},
    {"step": "calculate reorder quantity", "status": "completed", "tool": "analyzer"}
  ],
  "final_output": "...Widget A...reorder quantity: 6...",
  "data": {"artifacts": {"matches": [{"product": "Widget A", "reorder_quantity": 6}]}}
}
```

The exact `selection_reason` differs depending on whether an LLM provider or the offline fallback is configured.

## 11th-workflow scalability example

The automated test creates a temporary Excel row for `WF011 Compliance Case Check`, loads it through the same loader, and executes it with the existing generic engine. It does not add WF011-specific production code. A new WF011 can be added by inserting a row in the workbook with its inputs, steps, decision logic, tools, and expected output.
