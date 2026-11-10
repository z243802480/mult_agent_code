import csv
import io


def parse_csv(text):
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def validate(entries):
    for entry in entries:
        entry['amount'] = float(entry['amount'])
    return entries


def load(text):
    return validate(parse_csv(text))
