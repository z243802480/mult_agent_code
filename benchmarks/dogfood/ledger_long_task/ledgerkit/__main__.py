import argparse
import json
from pathlib import Path

from .importer import load
from .ledger import account_totals, filter_entries
from .reports import monthly_totals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--kind', choices=['income', 'expense'])
    parser.add_argument('--format', choices=['json', 'csv'], default='json')
    parser.add_argument('--monthly', action='store_true')
    args = parser.parse_args()
    rows = load(Path(args.input).read_text(encoding='utf-8'))
    rows = filter_entries(rows, args.start, args.end, args.kind)
    result = monthly_totals(rows) if args.monthly else account_totals(rows)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
