"""Print a registration plan from an operator-reviewed JSON record."""
import argparse
import json
from pathlib import Path

from bct_maintenance.cli import Maintenance
from bct_maintenance.registration import registration_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--source-worktree", required=True, type=Path)
    args = parser.parse_args()
    with args.review.open(encoding="utf-8") as stream:
        review = json.load(stream)
    print(json.dumps(registration_plan(Maintenance(args.config), review, args.source_worktree),
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
