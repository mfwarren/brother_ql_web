#!/usr/bin/env python3
"""Exercise a disposable Label Studio simulation server over HTTP.

Works against either backend. Never run against production: the checks install a
font and leave simulation job records. Printing is gated on both configuration
and live status reporting simulation. Saved test labels and defaults are restored.

  python tools/check_rust_api.py --url http://127.0.0.1:8016
  python tools/check_rust_api.py --url http://127.0.0.1:8015 --capture /tmp/python-renders
  python tools/check_rust_api.py --url http://127.0.0.1:8016 --compare /tmp/python-renders

Only the standard library is required. Pillow and zxing-cpp, when installed,
add pixel comparisons and QR/barcode decoding checks. --require-decode makes
missing decoder dependencies an error. Capture stores drafts and PNGs so reference
checks still work after removal of the Python application.
"""
import argparse
import base64
import copy
import hashlib
import io
import json
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from pathlib import Path


class Client:
    def __init__(self, url):
        self.url = url.rstrip('/')
        self.requests = 0

    def request(self, path, method='GET', body=None, expected=200, headers=None):
        headers = dict(headers or {})
        if body is not None and not isinstance(body, bytes):
            headers['Content-Type'] = 'application/json'
            body = json.dumps(body, ensure_ascii=False).encode()
        request = urllib.request.Request(self.url + path, data=body, method=method, headers=headers)
        self.requests += 1
        try:
            response = urllib.request.urlopen(request, timeout=90)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            payload = response.read()
            assert response.status == expected, f'{method} {path}: expected {expected}, got {response.status}: {payload[:600]!r}'
            content_type = response.headers.get('content-type', '')
            if 'application/json' in content_type:
                payload = json.loads(payload)
            return payload, {key.lower(): value for key, value in response.headers.items()}

    def json(self, path, method='GET', body=None, expected=200):
        headers = {'Content-Type': 'application/json'} if isinstance(body, bytes) else None
        payload, _ = self.request(path, method, body, expected, headers=headers)
        assert isinstance(payload, dict), f'{path}: expected a JSON object, got {payload!r}'
        if expected >= 400:
            assert isinstance(payload.get('message'), str), f'{path}: missing error message'
        return payload

    def preview(self, draft):
        data, headers = self.request('/studio/api/preview', 'POST', draft)
        assert headers.get('content-type', '').startswith('image/png')
        assert 'no-store' in headers.get('cache-control', '')
        png_size(data)
        return data

    def assert_simulation(self):
        assert self.json('/studio/api/config')['mode'] == 'simulation', 'Refusing to mutate a physical printer server'
        assert self.json('/studio/api/status')['state'] == 'simulation', 'Refusing to send jobs to a physical printer'


def png_size(data):
    assert isinstance(data, bytes) and data.startswith(b'\x89PNG\r\n\x1a\n'), 'Expected a PNG'
    width, height = struct.unpack('>II', data[16:24])
    assert 0 < width <= 11000 and 0 < height <= 11000
    assert width * height <= 16_000_000
    return width, height


def sample_image():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    # Deliberately asymmetric artwork exercises rotation as well as image fitting.
    pixels = b''.join(b'\x00' + b''.join(bytes((0, 0, 0) if x < 12 or y < 4 else (255, 255, 255)) for x in range(32)) for y in range(20))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 32, 20, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')


def draft(font, content=None, **settings):
    return {'content': content or {'kind': 'text', 'text': 'Coffee\nbeans'},
            'sizeId': '62', 'orientation': 'standard', 'font': font,
            'fontSize': 24, 'align': 'left', 'color': 'black', 'margin': 20,
            'highRes': False, **settings}


def decode(data, expected, require=False):
    try:
        from PIL import Image
        import zxingcpp
    except ImportError:
        if require:
            raise AssertionError('Install Pillow and zxing-cpp for required decoder checks')
        return False
    result = zxingcpp.read_barcode(Image.open(io.BytesIO(data)))
    assert result is not None, f'Unable to decode {expected!r}'
    assert result.text == expected, f'Decoded {result.text!r}, expected {expected!r}'
    return True


def check_api(client, require_decode=False):
    client.assert_simulation()
    config = client.json('/studio/api/config')
    font = config['defaultFont']
    font_ids = {f['id'] for f in config['fonts']}
    assert font in font_ids and config['defaults']['font'] in font_ids
    assert config['defaultSize'] in {size['id'] for size in config['sizes']}
    for face in config['fonts']:
        assert {'id', 'name', 'weight', 'italic'} <= face.keys()
    for size in config['sizes']:
        assert {'id', 'name', 'codes', 'description', 'fixedSize'} <= size.keys()
    assert {'font', 'sizeId', 'orientation', 'margin', 'fontSize', 'autoDetectRoll'} <= config['defaults'].keys()
    basic = draft(font)
    client.preview(basic)
    invalids = [None, [], {}, {**basic, 'fontSize': True}, {**basic, 'fontSize': 0},
                {**basic, 'sizeId': 'missing'}, {**basic, 'font': 'missing'},
                {**basic, 'orientation': 'up'}, {**basic, 'margin': -1},
                {**basic, 'color': 'red'}, {**basic, 'content': {'kind': 'unknown'}}]
    for invalid in invalids:
        # Serialize null explicitly instead of treating it as an absent request body.
        client.json('/studio/api/preview', 'POST', json.dumps(invalid).encode(), 400)
    for identifier in ['../settings', '..\\settings', '/etc/passwd', 'not-a-uuid']:
        path = '/studio/api/labels/' + urllib.parse.quote(identifier, safe='')
        client.json(path, expected=400)
        client.json(path, 'DELETE', expected=400)
        client.json(path, 'PUT', {'name': 'Invalid path', 'draft': basic}, 400)
    assert client.json('/studio/api/config')['defaults'] == config['defaults']
    saved_id = None
    original_defaults = config['defaults']
    try:
        saved = client.json('/studio/api/labels', 'POST', {'name': 'Rust HTTP contract test', 'draft': basic}, 201)
        saved_id = saved['id']
        uuid.UUID(saved_id)
        assert saved['draft'] == basic, 'Legacy labels must not gain rich layout defaults'
        assert client.json('/studio/api/labels/' + saved_id)['draft'] == basic
        assert client.json('/studio/api/labels/' + saved_id.upper())['id'] == saved_id
        assert any(item['id'] == saved_id for item in client.json('/studio/api/labels')['labels'])
        rich = draft(font, {'kind': 'text', 'text': 'Mixed type', 'paragraphs': [{'runs': [{'text': 'Mixed ', 'size': 30}, {'text': 'type', 'size': 18, 'underline': True}]}]}, verticalAlign='bottom', lineSpacing=120, margins={'top': 12, 'right': 23, 'bottom': 34, 'left': 15})
        updated = client.json('/studio/api/labels/' + saved_id, 'PUT', {'name': 'Updated HTTP contract test', 'draft': rich})
        assert updated['draft'] == rich and updated['name'] == 'Updated HTTP contract test'
        assert client.json('/studio/api/labels/' + saved_id)['draft'] == rich
        client.preview(rich)
        preferences = {**original_defaults, 'font': font, 'fontSize': 38, 'margin': 11, 'orientation': 'rotated', 'autoDetectRoll': False}
        assert client.json('/studio/api/settings', 'PUT', preferences)['defaults'] == preferences
        assert client.json('/studio/api/config')['defaults'] == preferences
        assert client.json('/studio/api/labels/' + saved_id)['draft'] == rich
        client.json('/studio/api/settings', 'PUT', {**preferences, 'margin': True}, 400)
        assert client.json('/studio/api/config')['defaults'] == preferences
        print('PASS configuration, validation, saved-label round trips, persistent preferences')
        check_bulk(client, basic, font)
        check_codes(client, font, require_decode)
        check_fonts(client, font)
        check_printing(client, basic)
        for address in ['http://example.com/test.png', 'https://127.0.0.1/a.png', 'https://[::1]/a.png', 'https://user:pass@example.com/a.png']:
            client.json('/studio/api/bulk/image', 'POST', {'url': address}, 400)
        print('PASS unsafe remote-image URL rejection')
    finally:
        client.json('/studio/api/settings', 'PUT', original_defaults)
        if saved_id:
            client.json('/studio/api/labels/' + saved_id, 'DELETE')
            client.json('/studio/api/labels/' + saved_id, expected=404)


def check_bulk(client, basic, font):
    template = draft(font, {'kind': 'text', 'text': 'Hi {{Product}}!', 'paragraphs': [{'runs': [{'text': 'Hi '}, {'text': '{{Pro', 'underline': True}, {'text': 'duct}}!'}]}]})
    result = client.json('/studio/api/bulk/prepare', 'POST', {'template': template, 'csv': 'Product\n"Coffee\nTea"\n{{env:SECRET}}', 'timezone': 'America/Toronto'})
    assert result['headers'] == ['Product']
    uuid.UUID(result['jobId'])
    first, second = result['rows']
    assert first['kind'] == second['kind'] == 'ready'
    assert first['line'] == 3 and second['line'] == 4
    assert first['draft']['content']['text'] == 'Hi Coffee\nTea!'
    assert first['draft']['content']['paragraphs'][0]['runs'][1] == {'text': 'Coffee', 'underline': True}
    assert second['draft']['content']['text'] == 'Hi {{env:SECRET}}!'
    client.preview(first['draft'])
    for csv in ['A,A\n1,2', ',B\n1,2', '@row\n1', 'Name\n', 'Name\n"unclosed', '\ufeff"Name"junk\nCoffee', '\nName\nCoffee']:
        client.json('/studio/api/bulk/prepare', 'POST', {'template': basic, 'csv': csv}, 400)
    multiline = draft(font, {'kind': 'text', 'text': '{{Name}} {{SKU}}'})
    rows = client.json('/studio/api/bulk/prepare', 'POST', {
        'template': multiline, 'csv': 'Name,SKU\r\n"Coffee\rbeans\r\nbag\nlarge",0012\r\nTea,0013'})['rows']
    assert [row['line'] for row in rows] == [5, 6], 'CSV errors/previews must identify physical source lines'
    assert rows[0]['draft']['content']['text'] == 'Coffee\rbeans\r\nbag\nlarge 0012'
    barcode = draft(font, {'kind': 'barcode', 'format': 'ean8', 'code': '{{SKU}}', 'caption': '{{Name}}'})
    rows = client.json('/studio/api/bulk/prepare', 'POST', {'template': barcode, 'csv': '\ufeffSKU,Name\n9638507,Tea\nwrong,Coffee\nshort', 'timezone': 'UTC'})['rows']
    assert [row['kind'] for row in rows] == ['ready', 'error', 'error']
    assert [row['line'] for row in rows] == [2, 3, 4]
    missing = client.json('/studio/api/bulk/prepare', 'POST', {'template': barcode, 'csv': 'SKU\n9638507'})['rows'][0]
    assert missing['kind'] == 'error' and '{{Name}}' in missing['message']
    builtin = draft(font, {'kind': 'text', 'text': '{{@row}}/{{@total}} {{@today}} {{@time}}'})
    rows = client.json('/studio/api/bulk/prepare', 'POST', {'template': builtin, 'count': 3})['rows']
    texts = [row['draft']['content']['text'] for row in rows]
    assert [text.split()[0] for text in texts] == ['1/3', '2/3', '3/3']
    assert len({text.partition(' ')[2] for text in texts}) == 1
    print('PASS CSV errors, multiline rows, split rich placeholders, literal values, frozen builtins')


def check_codes(client, font, require_decode):
    image = {'kind': 'image', 'image': {'name': 'test.png', 'mime': 'image/png', 'base64': base64.b64encode(sample_image()).decode()}, 'caption': 'Box', 'fit': True, 'mode': 'grayscale'}
    client.preview(draft(font, image))
    count = 0
    cases = [({'kind': 'qr', 'code': 'https://example.com/label?id=001', 'caption': 'Scan'},
              'https://example.com/label?id=001')]
    for fmt, code, expected in [('code128', 'SKU-0042', 'SKU-0042'),
                                ('ean13', '590123412345', '5901234123457'),
                                ('ean8', '9638507', '96385074'),
                                ('upca', '03600029145', '0036000291452')]:
        cases.append(({'kind': 'barcode', 'format': fmt, 'code': code, 'caption': 'Stock'}, expected))
    for content, expected in cases:
        for size, orientation in [('62', 'standard'), ('29x90', 'standard'), ('29x90', 'rotated')]:
            count += decode(client.preview(draft(font, content, sizeId=size, orientation=orientation)), expected, require_decode)
    for fmt, code in [('ean13', '5901234123458'), ('ean8', '123'), ('upca', 'abc'), ('code128', 'Café'), ('unknown', '123')]:
        client.json('/studio/api/preview', 'POST', draft(font, {'kind': 'barcode', 'format': fmt, 'code': code, 'caption': ''}), 400)
    print(f'PASS image, QR and four barcode previews ({count} machine-decoded images)')


def check_fonts(client, font):
    catalog = client.json('/studio/api/fonts/catalog')['families']
    assert len(catalog) > 1500
    client.json('/studio/api/fonts/install', 'POST', {'id': '../../etc/passwd'}, 400)
    data, _ = client.request('/studio/api/fonts/file?' + urllib.parse.urlencode({'font': font}))
    assert isinstance(data, bytes) and len(data) > 100
    boundary = 'font-' + uuid.uuid4().hex
    def upload(data):
        body = f'--{boundary}\r\nContent-Disposition: form-data; name="font"; filename="test.ttf"\r\nContent-Type: font/ttf\r\n\r\n'.encode() + data + f'\r\n--{boundary}--\r\n'.encode()
        return body, {'Content-Type': 'multipart/form-data; boundary=' + boundary}
    body, headers = upload(data)
    result, _ = client.request('/studio/api/fonts/upload', 'POST', body, headers=headers)
    assert result['font'] in {face['id'] for face in result['fonts']}
    returned, _ = client.request('/studio/api/fonts/file?' + urllib.parse.urlencode({'font': result['font']}))
    assert returned == data, 'Installation must retain original font outlines'
    client.preview(draft(result['font']))
    body, headers = upload(b'broken font')
    failure, _ = client.request('/studio/api/fonts/upload', 'POST', body, expected=400, headers=headers)
    assert isinstance(failure.get('message'), str)
    print('PASS font catalog, original-file upload, registry reload, invalid font rejection')


def check_printing(client, basic):
    client.assert_simulation()
    for cut in ['each', 'end']:
        result = client.json('/studio/api/print', 'POST', {'draft': basic, 'copies': 2, 'cut': cut})
        assert result['kind'] == 'simulated' and result['copies'] == 2
    payload = {'jobId': str(uuid.uuid4()), 'drafts': [basic, basic], 'cut': 'end'}
    result = client.json('/studio/api/bulk/print', 'POST', payload)
    assert result['kind'] == 'simulated' and result['copies'] == 2
    client.json('/studio/api/bulk/print', 'POST', payload, 409)
    client.json('/studio/api/bulk/print', 'POST', {'jobId': str(uuid.uuid4()), 'drafts': [basic, {**basic, 'sizeId': '29x90'}]}, 400)
    for copies in [0, 101, True]:
        client.json('/studio/api/print', 'POST', {'draft': basic, 'copies': copies, 'cut': 'each'}, 400)
    print('PASS simulation-only single/bulk printing, cut options, duplicate suppression, mixed-roll rejection')


def reference_cases(font):
    contents = {
        'plain': {'kind': 'text', 'text': 'Coffee\nbeans'},
        'rich': {'kind': 'text', 'text': 'Coffee\nbeans', 'paragraphs': [{'runs': [{'text': 'Coffee', 'size': 32, 'underline': True}]}, {'runs': [{'text': 'beans'}]}]},
        'qr': {'kind': 'qr', 'code': 'https://example.com', 'caption': 'Scan'},
        'barcode': {'kind': 'barcode', 'format': 'code128', 'code': 'A12', 'caption': 'Stock'},
        'image': {'kind': 'image', 'image': {'name': 'test.png', 'mime': 'image/png', 'base64': base64.b64encode(sample_image()).decode()}, 'mode': 'grayscale', 'fit': True, 'caption': 'Box'},
    }
    for size in ['62', '62x100', '62red']:
        for orientation in ['standard', 'rotated']:
            for high_res in [False, True] if size != '62red' else [False]:
                for kind, content in contents.items():
                    label = draft(font, copy.deepcopy(content), sizeId=size, orientation=orientation, highRes=high_res, color='red' if size == '62red' else 'black')
                    if kind == 'rich':
                        label.update(verticalAlign='top', lineSpacing=150, margins={'left': 30, 'right': 20, 'top': 15, 'bottom': 25})
                    yield f'{size}-{orientation}-{high_res}-{kind}', label


def capture(client, directory):
    directory.mkdir(parents=True, exist_ok=True)
    config = client.json('/studio/api/config')
    font = config['defaultFont']
    manifest = {'font': font, 'cases': []}
    for key, label in reference_cases(font):
        image = client.preview(label)
        filename = key + '.png'
        (directory / filename).write_bytes(image)
        manifest['cases'].append({'key': key, 'draft': label, 'png': filename, 'sha256': hashlib.sha256(image).hexdigest(), 'size': png_size(image)})
    (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Captured {len(manifest["cases"])} reference drafts and PNGs in {directory}')


def compare(client, directory, allow_qr_mask=False):
    manifest = json.loads((directory / 'manifest.json').read_text())
    differences = []
    exact = pixels_equal = qr_equivalent = 0
    for case in manifest['cases']:
        image = client.preview(case['draft'])
        reference = (directory / case['png']).read_bytes()
        if image == reference:
            exact += 1
            pixels_equal += 1
            continue
        mismatch = {'key': case['key'], 'referenceSize': png_size(reference), 'actualSize': png_size(image)}
        try:
            from PIL import Image, ImageChops
            before = Image.open(io.BytesIO(reference)).convert('RGB')
            after = Image.open(io.BytesIO(image)).convert('RGB')
            if before.size == after.size:
                diff = ImageChops.difference(before, after)
                if diff.getbbox() is None:
                    pixels_equal += 1
                    continue
                pixels = diff.tobytes()
                mismatch['changedPixels'] = sum(pixels[i:i + 3] != b'\x00\x00\x00' for i in range(0, len(pixels), 3))
        except ImportError:
            mismatch['pixelComparison'] = 'Install Pillow to compare independently of PNG encoding'
        if allow_qr_mask and case['draft']['content']['kind'] == 'qr' and png_size(reference) == png_size(image):
            import zxingcpp
            from PIL import Image
            decoded = [code.text for code in zxingcpp.read_barcodes(Image.open(io.BytesIO(image)))]
            if case['draft']['content']['code'].strip() in decoded:
                qr_equivalent += 1
                continue
        (directory / ('actual-' + case['png'])).write_bytes(image)
        differences.append(mismatch)
    report = {'total': len(manifest['cases']), 'identicalPng': exact, 'identicalPixels': pixels_equal, 'equivalentQrMasks': qr_equivalent, 'differences': differences}
    (directory / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Render comparison: {pixels_equal}/{len(manifest["cases"])} identical pixels, {exact} identical PNG files')
    print(f'QR encoding differences verified by decoding: {qr_equivalent}')
    for difference in differences:
        print('DIFF ' + json.dumps(difference))
    assert not differences, f'Render differences saved to {directory / "comparison.json"}'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', required=True)
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--render-only', action='store_true', help='Only capture/compare previews; do not run mutating API checks')
    parser.add_argument('--require-decode', action='store_true')
    parser.add_argument('--allow-qr-mask', action='store_true', help='Accept a different QR mask only when dimensions and machine-decoded contents match')
    args = parser.parse_args()
    client = Client(args.url)
    if not args.render_only:
        check_api(client, args.require_decode)
    if args.capture:
        capture(client, args.capture)
    if args.compare:
        compare(client, args.compare, args.allow_qr_mask)
    print(f'PASS {client.requests} HTTP requests against {args.url}')


if __name__ == '__main__':
    try:
        main()
    except (AssertionError, urllib.error.URLError) as error:
        print(f'FAIL {error}', file=sys.stderr)
        raise SystemExit(1)
