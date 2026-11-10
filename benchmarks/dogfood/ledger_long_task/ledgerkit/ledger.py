def account_totals(entries):
    totals = {}
    for row in entries:
        key = row['account']
        totals[key] = totals.get(key, 0) + row['amount']
    return [{'account': key, 'currency': 'USD', 'total': value} for key, value in totals.items()]


def filter_entries(entries, start=None, end=None, kind=None):
    return [row for row in entries if not start or row['date'] > start]
