"""Render a validated Studio draft for preview or printing."""
import io
import json
from werkzeug.datastructures import FileStorage

def to_upstream(draft, image_bytes):
    content = draft['content']
    kind = content['kind']
    line_text = content['text'] if kind == 'text' else content.get('caption', '')
    lines = [{'text': text, 'font': draft['font'], 'size': str(draft['fontSize']),
              'align': draft['align'], 'color': draft['color'], 'line_spacing': str(draft.get('lineSpacing', 100))}
             for text in line_text.splitlines()]
    values = {'label_size': draft['sizeId'], 'orientation': draft['orientation'],
              'text': json.dumps(lines), 'print_type': {'text': 'text', 'qr': 'qrcode_text', 'barcode': 'qrcode_text', 'image': 'image'}[kind],
              **{f'margin_{side}': draft.get('margins', {}).get(side, draft['margin']) for side in ('top', 'right', 'bottom', 'left')},
              'high_res': int(draft['highRes']), 'print_color': draft['color'], 'border_thickness': 0}
    files = {}
    if kind in ('qr', 'barcode'):
        values.update(barcode_type='QR' if kind == 'qr' else content['format'], code_text=content['code'])
    if kind == 'barcode':
        values.update(image_crop=0)
    if kind == 'image':
        values.update(image_mode={'grayscale': 'grayscale', 'bw': 'bw', 'red': 'red_and_black'}[content['mode']],
                      image_fit=int(content['fit']))
        image = content['image']
        files['image'] = FileStorage(stream=io.BytesIO(image_bytes), filename=image['name'], content_type=image['mime'])
    return values, files


def render(draft, image_bytes):
    if draft['content']['kind'] == 'text' and ('paragraphs' in draft['content'] or 'verticalAlign' in draft or 'lineSpacing' in draft or 'margins' in draft):
        from app.rich_text import render_label
        if 'paragraphs' not in draft['content']:
            draft = {**draft, 'content': {**draft['content'], 'paragraphs': [{'runs': [{'text': line}]} for line in draft['content']['text'].split('\n')]}}
        return render_label(draft)
    from app.labeldesigner.rendering import build_label
    values, files = to_upstream(draft, image_bytes)
    label = build_label(values, files)
    label.expand_templates = False
    return label
