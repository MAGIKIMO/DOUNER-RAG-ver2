"""Extract public campus guides without losing schedule/table associations."""
from bs4 import BeautifulSoup
from .crawl_common import clean_text, first_node


def extract(soup, library=False):
    node = first_node(soup, ['.contents-body'] if library else ['.contents_view_wrap', '#cont'])
    node = BeautifulSoup(str(node), 'html.parser')
    for table in list(node.select('table')):
        if table.find_parent('table'):
            continue
        lines, spans = [], {}
        headers = [c.get_text(' ', strip=True) for c in table.select('thead th')]
        calendar = '기간' in headers and '업무' in headers
        for row in table.select('tr'):
            cells = row.find_all(['th', 'td'], recursive=False)
            # The academic calendar uses aligned lists inside date/event cells.
            lists = [[li.get_text(' ', strip=True) for li in c.select('ul > li') if not li.select('ul')] for c in cells]
            lengths = [len(items) for items in lists if items]
            if calendar and lengths and max(lengths) > 1:
                if len(set(lengths)) != 1:
                    raise ValueError('unaligned_calendar_lists')
                for i in range(lengths[0]):
                    parts = [items[i] if items else c.get_text(' ', strip=True) for c, items in zip(cells, lists)]
                    if any(parts[j] for j, items in enumerate(lists) if items):
                        lines.append(' | '.join(parts))
                continue
            values, col = {}, 0
            for index, (value, remaining) in list(spans.items()):
                values[index] = value
                if remaining == 1:
                    del spans[index]
                else:
                    spans[index] = (value, remaining - 1)
            for cell in cells:
                while col in values:
                    col += 1
                value = cell.get_text(' ', strip=True)
                width, height = int(cell.get('colspan', 1)), int(cell.get('rowspan', 1))
                if not 1 <= width <= 100 or not 1 <= height <= 100:
                    raise ValueError('invalid_table_span')
                for index in range(col, col + width):
                    values[index] = value
                    if height > 1:
                        spans[index] = (value, height - 1)
                col += width
            lines.append(' | '.join(values.get(i, '') for i in range(max(values, default=-1) + 1)))
        table.replace_with('\n' + '\n'.join(lines) + '\n')
    text = clean_text(node)
    if len(text) < 30:
        raise ValueError('empty_or_image_only_content')
    return text
