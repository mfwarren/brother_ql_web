"""Capture/compare render hashes on the same host and font installation.

Run: .venv/bin/python tools/render_reference.py capture /tmp/label-render.json
Then: .venv/bin/python tools/render_reference.py compare /tmp/label-render.json
"""
import argparse
import base64
import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from app import create_app


def capture():
    app = create_app()
    app.config.update(PRINTER_PRINTER='simulation', STUDIO_SEED_SAMPLES=False,
                      STUDIO_LABELS_DIR=tempfile.mkdtemp())
    client = app.test_client()
    font = client.get('/studio/api/config').json['defaultFont']
    pixels = io.BytesIO()
    Image.new('RGB', (32, 20), 'black').save(pixels, format='PNG')
    contents = {
        'plain': {'kind': 'text', 'text': 'Coffee\nbeans'},
        'rich': {'kind': 'text', 'text': 'Coffee\nbeans', 'paragraphs': [
            {'runs': [{'text': 'Coffee', 'size': 32, 'underline': True}]}, {'runs': [{'text': 'beans'}]}]},
        'qr': {'kind': 'qr', 'code': 'https://example.com', 'caption': 'Scan'},
        'barcode': {'kind': 'barcode', 'format': 'code128', 'code': 'A12', 'caption': 'Stock'},
        'image': {'kind': 'image', 'image': {'name': 'test.png', 'mime': 'image/png',
                  'base64': base64.b64encode(pixels.getvalue()).decode()}, 'mode': 'grayscale', 'fit': True, 'caption': 'Box'},
    }
    result = {}
    for size in ('62', '62x100', '62red'):
        for orientation in ('standard', 'rotated'):
            for high_res in (False, True) if size != '62red' else (False,):
                for kind, content in contents.items():
                    draft = {'content': content, 'sizeId': size, 'orientation': orientation,
                             'font': font, 'fontSize': 24, 'align': 'left', 'color': 'red' if size == '62red' else 'black',
                             'margin': 20, 'highRes': high_res}
                    if kind == 'rich':
                        draft.update(verticalAlign='top', lineSpacing=150, margins={'left': 30, 'right': 20, 'top': 15, 'bottom': 25})
                    response = client.post('/studio/api/preview', json=draft)
                    key = f'{size}/{orientation}/{high_res}/{kind}'
                    if response.status_code != 200:
                        raise RuntimeError(f'{key}: {response.data.decode()}')
                    result[key] = hashlib.sha256(response.data).hexdigest()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('capture', 'compare'))
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    sys.argv = sys.argv[:1]  # The app also supports CLI printer configuration.
    hashes = capture()
    if args.mode == 'capture':
        args.path.write_text(json.dumps(hashes, indent=2) + '\n')
        print(f'Captured {len(hashes)} renders.')
    else:
        baseline = json.loads(args.path.read_text())
        changed = [key for key in baseline.keys() | hashes.keys() if baseline.get(key) != hashes.get(key)]
        if changed:
            raise SystemExit('Changed renders:\n' + '\n'.join(sorted(changed)))
        print(f'All {len(hashes)} renders match byte for byte.')
