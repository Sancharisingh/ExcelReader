from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from dotenv import load_dotenv

from .excel_loader import load_workflows
from .graph import run_agent


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run Excel-defined business workflows.")
    parser.add_argument("request", nargs="?", help="The user's business request")
    parser.add_argument("--workbook", default=os.getenv("WORKBOOK_PATH", "AI_Agent_Workflow_Assessment (1).xlsx"))
    parser.add_argument("--list", action="store_true", help="List loaded workflows")
    args = parser.parse_args()
    workflows = load_workflows(Path(args.workbook))
    if args.list:
        print(json.dumps([w.model_dump() for w in workflows], indent=2))
        return
    if not args.request:
        parser.error("request is required unless --list is supplied")
    print(json.dumps(run_agent(args.request, workflows).model_dump(), indent=2, default=str))


if __name__ == "__main__":
    main()
