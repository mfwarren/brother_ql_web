"""CSV label merging. Substitution is literal, never an executable template."""
import copy
import csv
import io
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TOKEN = re.compile(r'\{\{([^{}]+)\}\}')
BUILTINS = ('@today', '@time', '@row', '@total')
LIMIT = 100


def parse_csv(text):
    if not isinstance(text, str) or len(text.encode('utf-8')) > 1_000_000:
        raise ValueError('Choose a UTF-8 CSV smaller than 1 MB.')
    reader = csv.reader(io.StringIO(text.lstrip('\ufeff'), newline=''), strict=True)
    try:
        headers = [value.strip() for value in next(reader)]
        if not headers or len(headers) > 50 or any(not value for value in headers):
            raise ValueError('Use 1–50 named columns. Every header needs a name.')
        if len(set(headers)) != len(headers):
            raise ValueError('Column names must be unique.')
        if any('{' in name or '}' in name or name.startswith('@') for name in headers):
            raise ValueError('Column names cannot contain braces or start with @.')
        rows = []
        for values in reader:
            if not values or all(not value.strip() for value in values):
                continue
            if len(rows) >= LIMIT:
                raise ValueError('Use at most 100 data rows per batch. Split larger CSV files.')
            error = None if len(values) == len(headers) else f'Expected {len(headers)} columns, found {len(values)}.'
            rows.append({'line': reader.line_num, 'values': dict(zip(headers, values)), 'error': error})
    except StopIteration:
        raise ValueError('The CSV is empty.')
    except csv.Error as error:
        raise ValueError(f'CSV line {reader.line_num}: {error}')
    if not rows:
        raise ValueError('The CSV has headers but no data rows.')
    return headers, rows


def merge(template, values):
    result = copy.deepcopy(template)

    def substitute(text):
        def replace(match):
            name = match[1].strip()
            if name not in values:
                raise ValueError(f'Unknown field {{{{{name}}}}}. Match the CSV column name exactly.')
            return values[name]
        # Validate syntax before replacing so CSV values stay literal.
        if '{{' in TOKEN.sub('', text) or '}}' in TOKEN.sub('', text):
            raise ValueError('Unclosed or nested field. Use {{Column name}}.')
        return TOKEN.sub(replace, text)

    content = result['content']
    if content['kind'] == 'text':
        if 'paragraphs' in content:
            paragraphs = []
            for paragraph in content['paragraphs']:
                runs = paragraph['runs']
                text = ''.join(run['text'] for run in runs)
                # Preserve the style at each placeholder's first character.
                spans = []
                offset = 0
                for run in runs:
                    spans.append((offset, offset + len(run['text']), run))
                    offset += len(run['text'])
                merged = []
                cursor = 0
                for match in TOKEN.finditer(text):
                    for start, end, run in spans:
                        part = text[max(cursor, start):min(match.start(), end)]
                        if max(cursor, start) < min(match.start(), end):
                            merged.append({**run, 'text': part})
                    style = next((run for start, end, run in spans if start <= match.start() < end), {})
                    merged.append({**style, 'text': substitute(match[0])})
                    cursor = match.end()
                for start, end, run in spans:
                    if max(cursor, start) < end:
                        merged.append({**run, 'text': text[max(cursor, start):end]})
                substitute(text)  # Also check malformed tokens.
                current = []
                for run in merged:
                    for index, line in enumerate(run['text'].replace('\r\n', '\n').replace('\r', '\n').split('\n')):
                        if index:
                            paragraphs.append({'runs': current})
                            current = []
                        current.append({**run, 'text': line})
                paragraphs.append({'runs': current})
            content['paragraphs'] = paragraphs
            content['text'] = '\n'.join(''.join(run['text'] for run in p['runs']) for p in paragraphs)
        else:
            content['text'] = substitute(content['text'])
    else:
        content['caption'] = substitute(content['caption'])
        if content['kind'] in ('qr', 'barcode'):
            content['code'] = substitute(content['code'])
    return result


def prepare(data):
    from app.studio import _validate_draft
    template = data.get('template')
    if not isinstance(template, dict) or not isinstance(template.get('content'), dict):
        raise ValueError('Choose a label template.')
    zone = data.get('timezone', 'UTC')
    if not isinstance(zone, str):
        raise ValueError('Invalid timezone.')
    try:
        now = datetime.now(ZoneInfo(zone))
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('Unknown timezone.')
    text = data.get('csv', '')
    if text:
        headers, rows = parse_csv(text)
    else:
        count = data.get('count', 1)
        if type(count) is not int or not 1 <= count <= LIMIT:
            raise ValueError('Choose 1–100 labels.')
        headers, rows = [], [{'line': i, 'values': {}, 'error': None} for i in range(1, count + 1)]
    results = []
    for number, row in enumerate(rows, 1):
        try:
            if row['error']:
                raise ValueError(row['error'])
            values = {**row['values'], '@today': now.strftime('%Y-%m-%d'),
                      '@time': now.strftime('%H:%M'), '@row': str(number), '@total': str(len(rows))}
            draft, _ = _validate_draft(merge(template, values))
            results.append({'row': number, 'line': row['line'], 'kind': 'ready', 'draft': draft})
        except (ValueError, KeyError, TypeError) as error:
            results.append({'row': number, 'line': row['line'], 'kind': 'error', 'message': str(error)})
    return {'headers': headers, 'rows': results, 'timestamp': now.isoformat(), 'jobId': str(uuid.uuid4())}
