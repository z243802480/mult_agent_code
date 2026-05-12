#!/usr/bin/env python3
"""
Sales Report Generator
Reads report_config.json and sales.csv to generate a markdown sales summary.
"""

import sys
import csv
import json
from pathlib import Path

# Currency symbol mapping
CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "¥",
    "KRW": "₩",
    "INR": "₹",
    "BRL": "R$",
    "CAD": "C$",
    "AUD": "A$",
}


def get_currency_symbol(currency_code: str) -> str:
    """Get currency symbol from ISO currency code."""
    return CURRENCY_SYMBOLS.get(currency_code.upper(), currency_code + " ")


def parse_csv_headers(headers: list) -> dict:
    """Detect column indices for date, product, and amount columns (case-insensitive)."""
    column_map = {}
    header_lower = [h.lower().strip() for h in headers]
    
    for idx, h in enumerate(header_lower):
        if 'date' in h:
            column_map['date'] = idx
        elif 'product' in h:
            column_map['product'] = idx
        elif 'amount' in h or 'total' in h or 'price' in h:
            column_map['amount'] = idx
    
    return column_map


def parse_amount(value: str) -> float:
    """Parse amount from string, handling currency symbols and commas."""
    cleaned = value.strip()
    # Remove currency symbols and commas
    for char in ['$', '€', '£', '¥', '₹', '₩', ',']:
        cleaned = cleaned.replace(char, '')
    return float(cleaned)


def validate_columns(column_map: dict) -> bool:
    """Check that required columns are found."""
    required = ['product', 'amount']
    return all(key in column_map for key in required)


def generate_report(config_path: Path, output_path: Path) -> None:
    """Generate the sales report from configuration and CSV data."""
    
    # Load configuration
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in config file '{config_path}': {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: Could not read config file '{config_path}': {e}")
        sys.exit(1)
    
    # Extract config values
    currency = config.get('currency', 'USD')
    minimum_total = float(config.get('minimum_total', 0))
    
    # Determine sales.csv path
    input_csv = config.get('input_csv')
    if input_csv:
        sales_csv_path = Path(input_csv)
        # If relative path, resolve from config directory
        if not sales_csv_path.is_absolute():
            sales_csv_path = config_path.parent / sales_csv_path
    else:
        # Default to same directory as config
        sales_csv_path = config_path.parent / 'sales.csv'
    
    # Override output path if specified in config
    output_markdown = config.get('output_markdown')
    if output_markdown:
        output_path = Path(output_markdown)
        if not output_path.is_absolute():
            output_path = config_path.parent / output_path
    
    # Validate sales.csv exists
    if not sales_csv_path.exists():
        print(f"Error: Sales CSV file not found: '{sales_csv_path}'")
        sys.exit(1)
    
    # Read and process CSV
    try:
        with open(sales_csv_path, 'r', encoding='utf-8', newline='') as f:
            reader = csv.reader(f)
            headers = next(reader)
            column_map = parse_csv_headers(headers)
            
            if not validate_columns(column_map):
                print(f"Error: Required columns (product, amount) not found in '{sales_csv_path}'")
                print(f"Available columns: {headers}")
                sys.exit(1)
            
            # Process rows
            product_totals = {}
            filtered_count = 0
            grand_total = 0.0
            
            for row in reader:
                if len(row) <= max(column_map['product'], column_map['amount']):
                    continue
                
                try:
                    product = row[column_map['product']].strip()
                    amount = parse_amount(row[column_map['amount']])
                except (ValueError, IndexError):
                    continue
                
                # Filter by minimum_total
                if amount < minimum_total:
                    filtered_count += 1
                    continue
                
                # Aggregate by product
                if product in product_totals:
                    product_totals[product] += amount
                else:
                    product_totals[product] = amount
                
                grand_total += amount
            
    except Exception as e:
        print(f"Error: Could not read sales file '{sales_csv_path}': {e}")
        sys.exit(1)
    
    # Generate markdown report
    currency_symbol = get_currency_symbol(currency)
    
    lines = [
        "# Sales Report",
        "",
        f"**Total Sales Count:** {len(product_totals)}",
        f"**Grand Total:** {currency_symbol}{grand_total:,.2f}",
        "",
        "## Sales by Product",
        "",
        "| Product | Total |",
        "|---------|-------|",
    ]
    
    for product, total in sorted(product_totals.items()):
        lines.append(f"| {product} | {currency_symbol}{total:,.2f} |")
    
    lines.append("")
    
    if filtered_count > 0:
        lines.append(f"*Note: {filtered_count} row(s) excluded for being below minimum total of {minimum_total}*")
    
    # Write output
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print(f"Report generated successfully: {output_path}")
    except Exception as e:
        print(f"Error: Could not write report to '{output_path}': {e}")
        sys.exit(1)


def main():
    """CLI entry point - validates config file path argument."""
    
    # Check for required argument
    if len(sys.argv) < 2:
        print("Error: Missing required argument")
        print("Usage: python report_from_config.py <path_to_report_config.json>")
        sys.exit(1)
    
    config_path_str = sys.argv[1]
    config_path = Path(config_path_str)
    
    # Validate config file exists
    if not config_path.exists():
        print(f"Error: Config file not found: '{config_path_str}'")
        sys.exit(1)
    
    if not config_path.is_file():
        print(f"Error: Config path is not a file: '{config_path_str}'")
        sys.exit(1)
    
    # Determine output path (default: report.md in config directory)
    output_path = config_path.parent / 'report.md'
    
    # Generate the report
    generate_report(config_path, output_path)


if __name__ == '__main__':
    main()
