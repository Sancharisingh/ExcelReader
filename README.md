# Excel-driven AI Workflow Agent

An extensible Python agent that converts business workflows defined in Excel into traceable executions. The project uses one workflow engine for all workflows; it does not create one hard-coded chatbot per business process.

The company-provided workbook is the source of truth: `AI_Agent_Workflow_Assessment (1).xlsx`. It contains the ten workflow definitions in `Workflows` and the supplied evaluation prompts in `Test_Questions`.

## Architecture

```text
USER → Natural-language request
  ↓
Workflow Router (Groq/Gemini LLM or offline fallback)
  ↓
Selected workflow
  ↓
Input Extraction (Excel-defined schema + LLM/fallback)
  ↓
Required-input check
  ↓
LangGraph workflow engine
  ↓
Read steps from Excel
  ↓
Generic tool resolver
  ├── source_reader
  ├── analyzer
  └── reporter / text_generator / validator
  ↓
Condition evaluation → Continue or Stop
  ↓
Final renderer → Final result
```

The agent returns a structured execution result containing the selected workflow when one is found, the selection explanation, ordered step trace, condition outcomes, structured tool data, and final business result. Early exits such as no-match and missing-input responses are represented explicitly.

## Design principles

- **Configuration over duplication.** Workflow names, inputs, steps, tools, decisions, and expected output are loaded from Excel.
- **Workflow-scoped tools.** The resolver maps only the selected row's `Tools_Required` values to reusable adapters.
- **Explicit state.** LangGraph carries request, extracted inputs, source records, artifacts, completed steps, and errors.
- **Safe routing.** LLM routing requires a permitted workflow ID and confidence threshold. Offline routing rejects weak or unrelated matches.
- **Replaceable integrations.** Simulated records are isolated in `config/simulated_sources.json`; production clients can replace adapters without changing the graph.

## Repository layout

| Path                                      | Responsibility                                                                                        |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `AI_Agent_Workflow_Assessment (1).xlsx` | Company-provided workflow catalogue and test prompts.                                                 |
| `app/excel_loader.py`                   | Reads workbook rows/sheets into `Workflow` models.                                                   |
| `app/models.py`                         | Pydantic models for workflows, traces, and results.                                                   |
| `app/selector.py`                       | LLM router and deterministic offline fallback.                                                        |
| `app/graph.py`                          | LangGraph orchestration.                                                                              |
| `app/tools.py`                          | Generic tool adapters, input extraction, condition evaluation, and result rendering.                  |
| `app/cli.py`                            | Command-line entry point.                                                                             |
| `config/simulated_sources.json`         | Local sample records for unavailable systems.                                                         |
| `tests/test_workflow_agent.py`          | Functional, negative, condition, and scalability tests.                                               |
| `examples/README.md`                    | Evaluator-facing example requests, expected results, natural-language variations, and negative cases. |
| `.env.example`                          | Provider configuration template.                                                                      |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

The application works offline. For LLM routing and structured input extraction, configure Groq or Gemini in `.env`:

```env
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_key
GROQ_MODEL=llama-3.3-70b-versatile
```

Or:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-2.0-flash
```

Never commit `.env` or real API keys.

## Run the agent

```bash
python -m app.cli "I want to know which items in our inventory are below the required stock level."
python -m app.cli --list
python -m app.cli --workbook /path/to/workflows.xlsx "your business request"
```

The JSON response includes `selected_workflow`, `selection_reason`, `steps_executed`, `final_output`, and structured `data`.

## Example inputs and outputs

See [examples/README.md](examples/README.md) for all ten supplied requests, representative expected results, arbitrary natural-language variations, negative routing examples, and a sample JSON response.

## Verify the implementation

```bash
python -m pytest -q
```

The suite validates all ten supplied workflows, arbitrary natural-language requests, no-match requests, missing-input branches, condition handling, workflow-scoped tools, keyword classification, simulated source processing, and an Excel-only WF011 scalability case that executes through the existing generic engine without WF011-specific production code.

## Adding an 11th workflow

Add a row to the Excel `Workflows` sheet containing `Workflow_ID`, `Workflow_Name`, `Trigger`, `Inputs`, `Steps`, `Decision_Logic`, `Tools_Required`, and `Expected_Output`.

For workflows that use existing supported tool categories, no new chatbot, router branch, LangGraph graph, or CLI command is required. The loader creates the workflow object, the router includes it in its catalogue, and the generic resolver maps its declared tools to reusable adapters.

If a new workflow introduces a completely new external capability, implement that capability once as a reusable adapter; the workflow still does not require a separate agent. For assignment/demo workflows that require unavailable external data, corresponding simulated records can be added to `config/simulated_sources.json`. The existing WF011 test creates a new Excel row and executes it without WF011-specific engine code.

## Tool and condition behavior

| Excel tool category                                         | Generic adapter    |
| ----------------------------------------------------------- | ------------------ |
| CSV/XLSX/database/source readers                            | `source_reader`  |
| Calculator, validation, similarity, ranking, classification | `analyzer`       |
| LLM/text generation                                         | `text_generator` |
| Reporting/export                                            | `reporter`       |

Conditions are evaluated against artifacts produced by the current workflow. Examples include record existence, missing required information, inventory thresholds, duplicate confidence, assignment availability, and failure-rate thresholds.

## Production considerations

The included source data is simulated for the assignment. A production deployment should add authenticated API clients, external-response schema validation, retries/timeouts, structured logging, secret management, execution-history persistence, and authorization around mutating tools.
