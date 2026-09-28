"""Refresh only the reviewed public campus-life catalog."""
import argparse
from pathlib import Path
from .crawl_public import run

CATALOG = Path(__file__).with_name('campus_life_sources.json')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=365)
    parser.add_argument('--max-pages', type=int, default=30)
    parser.add_argument('--retry-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.days <= 3650 or not 1 <= args.max_pages <= 2000:
        parser.error('Invalid days/max-pages')
    run(CATALOG, args.days, args.max_pages, args.retry_only)
