import copy
import csv
import io
import json
import subprocess
import sys
from decimal import Decimal

import pytest

from ledgerkit.importer import load, parse_csv, validate
from ledgerkit.ledger import account_totals, filter_entries
from ledgerkit.reports import monthly_totals


HEADER = 'id,account,kind,amount,currency,date\n'
DATA = HEADER + (
    't1,Work,income,10.10,USD,2026-01-01\n'
    't2,Work,expense,0.10,USD,2026-01-31\n'
    't3,Work,income,7.25,EUR,2026-02-01\n'
    't4,Home,expense,2.30,USD,2026-01-15\n'
    't5,Home,income,0.30,USD,2026-02-28\n'
)


def test_parse_bom_whitespace_and_quoted_comma():
    rows = parse_csv('\ufeff id , account , kind , amount , currency , date \n1," A,B ", income , 1.10 , USD , 2026-01-01 \n')
    assert rows[0]['account'] == 'A,B'
    assert rows[0]['id'] == '1'
    assert rows[0]['kind'] == 'income'


def test_decimal_input_and_nonmutation():
    rows = parse_csv(DATA)
    original = copy.deepcopy(rows)
    parsed = validate(rows)
    assert rows == original
    assert parsed[0]['amount'] == Decimal('10.10')
    assert isinstance(parsed[0]['amount'], Decimal)


@pytest.mark.parametrize('field,value', [
    ('id', ''), ('account', ''), ('kind', 'refund'), ('amount', '0'),
    ('amount', '-1.00'), ('amount', 'NaN'), ('amount', 'Infinity'),
    ('amount', '1.001'), ('amount', 'nonsense'), ('currency', 'usd'),
    ('currency', 'US'), ('currency', '123'), ('date', '2026-02-30'),
    ('date', '2026-1-1'),
])
def test_validation_rejects_bad_fields(field, value):
    row = dict(id='one', account='A', kind='income', amount='1.00', currency='USD', date='2026-01-01')
    row[field] = value
    with pytest.raises(ValueError):
        validate([row])


def test_duplicate_ids_identified():
    with pytest.raises(ValueError, match='duplicate.*t1|t1.*duplicate'):
        load(DATA + 't1,Other,income,1.00,USD,2026-01-01\n')


def test_missing_header_rejected():
    with pytest.raises(ValueError):
        load('id,amount\none,1.00\n')


def test_totals_group_sort_sign_and_precision():
    rows = load(DATA)
    before = copy.deepcopy(rows)
    assert account_totals(rows) == [
        {'account': 'Home', 'currency': 'USD', 'total': Decimal('-2.00')},
        {'account': 'Work', 'currency': 'EUR', 'total': Decimal('7.25')},
        {'account': 'Work', 'currency': 'USD', 'total': Decimal('10.00')},
    ]
    assert rows == before
    assert all(row['total'].as_tuple().exponent == -2 for row in account_totals(rows))


@pytest.mark.parametrize('start,end,kind,expected', [
    ('2026-01-01', '2026-01-31', None, ['t1', 't2', 't4']),
    (None, '2026-01-01', None, ['t1']),
    ('2026-02-01', None, None, ['t3', 't5']),
    (None, None, 'expense', ['t2', 't4']),
    ('2026-01-31', '2026-02-01', 'income', ['t3']),
])
def test_filter_bounds_and_kind(start, end, kind, expected):
    assert [row['id'] for row in filter_entries(load(DATA), start, end, kind)] == expected


def test_inverted_range_rejected():
    with pytest.raises(ValueError):
        filter_entries(load(DATA), '2026-02-01', '2026-01-01')


def test_monthly_totals():
    assert monthly_totals(load(DATA)) == [
        {'month': '2026-01', 'currency': 'USD', 'total': Decimal('7.70')},
        {'month': '2026-02', 'currency': 'EUR', 'total': Decimal('7.25')},
        {'month': '2026-02', 'currency': 'USD', 'total': Decimal('0.30')},
    ]


def run_cli(tmp_path, text, *args):
    path = tmp_path / 'ledger.csv'
    path.write_text(text, encoding='utf-8')
    return subprocess.run([sys.executable, '-m', 'ledgerkit', str(path), *args], capture_output=True, text=True)


def test_cli_json_strings_and_filters(tmp_path):
    result = run_cli(tmp_path, DATA, '--start', '2026-01-01', '--end', '2026-01-31', '--kind', 'expense')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        {'account': 'Home', 'currency': 'USD', 'total': '-2.30'},
        {'account': 'Work', 'currency': 'USD', 'total': '-0.10'},
    ]


def test_cli_csv(tmp_path):
    result = run_cli(tmp_path, DATA, '--format', 'csv')
    assert result.returncode == 0, result.stderr
    rows = list(csv.DictReader(io.StringIO(result.stdout)))
    assert list(rows[0]) == ['account', 'currency', 'total']
    assert rows[-1] == {'account': 'Work', 'currency': 'USD', 'total': '10.00'}


def test_cli_monthly(tmp_path):
    result = run_cli(tmp_path, DATA, '--monthly')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[0] == {'month': '2026-01', 'currency': 'USD', 'total': '7.70'}


def test_cli_invalid_input(tmp_path):
    result = run_cli(tmp_path, HEADER + 'x,A,income,NaN,USD,2026-01-01\n')
    assert result.returncode == 2
    assert result.stderr.strip()
    assert 'Traceback' not in result.stderr


def test_empty_ledger():
    assert load(HEADER) == []
    assert account_totals([]) == []
    assert monthly_totals([]) == []
