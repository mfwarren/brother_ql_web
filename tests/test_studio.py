import base64
import fcntl
import io
import json
import os
import pty
import signal
import threading
import time
import tty

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

from app import create_app
from app.studio import _status_from_raw
from app.labeldesigner.printer import query_printer_status
from app.utils import pdffile_to_image


@pytest.fixture
def client(tmp_path):
    app = create_app()
    app.config.update(TESTING=True, STUDIO_SEED_SAMPLES=False, STUDIO_LABELS_DIR=str(tmp_path / 'labels'),
                      STUDIO_PRINTER_LOCK=str(tmp_path / 'printer.lock'), PRINTER_PRINTER='simulation')
    return app.test_client()


def draft(client, content=None):
    config = client.get('/studio/api/config').json
    return {'content': content or {'kind': 'text', 'text': 'Kitchen shelves'},
            'sizeId': '62', 'orientation': 'standard', 'font': config['defaultFont'],
            'fontSize': 70, 'align': 'center', 'color': 'black', 'margin': 20, 'highRes': False}


def assert_png(response):
    assert response.status_code == 200
    assert response.content_type == 'image/png'
    image = Image.open(io.BytesIO(response.data))
    assert image.width > 0 and image.height > 0


def test_real_renderer_handles_text_qr_and_image(client):
    assert_png(client.post('/studio/api/preview', json=draft(client)))
    assert_png(client.post('/studio/api/preview', json=draft(client, {
        'kind': 'qr', 'code': 'https://example.com', 'caption': 'Pantry'})))
    source = io.BytesIO()
    Image.new('RGB', (30, 20), 'black').save(source, 'PNG')
    image = {'name': 'mark.png', 'mime': 'image/png',
             'base64': base64.b64encode(source.getvalue()).decode('ascii')}
    assert_png(client.post('/studio/api/preview', json=draft(client, {
        'kind': 'image', 'image': image, 'caption': 'Box', 'mode': 'grayscale', 'fit': True})))


def test_multiline_text_and_captions_render_without_a_border(client):
    text = draft(client, {'kind': 'text', 'text': 'Coffee beans\nOpened today'})
    response = client.post('/studio/api/preview', json=text)
    assert_png(response)
    image = Image.open(io.BytesIO(response.data))
    assert image.getpixel((0, 0)) == (255, 255, 255)
    assert_png(client.post('/studio/api/preview', json=draft(client, {
        'kind': 'qr', 'code': 'https://example.com', 'caption': 'Scan me\nFor details'})))


def test_high_resolution_preview_uses_larger_render_and_rejects_red_media(client):
    standard = draft(client)
    high = {**standard, 'highRes': True}
    standard_image = Image.open(io.BytesIO(client.post('/studio/api/preview', json=standard).data))
    high_response = client.post('/studio/api/preview', json=high)
    assert_png(high_response)
    high_image = Image.open(io.BytesIO(high_response.data))
    assert high_image.width == standard_image.width * 2
    assert client.post('/studio/api/preview', json={**high, 'sizeId': '62red'}).status_code == 400


def test_saved_image_round_trip_and_update(client, tmp_path):
    source = io.BytesIO()
    Image.new('RGB', (15, 15), 'red').save(source, 'PNG')
    image = {'name': 'sample.png', 'mime': 'image/png',
             'base64': base64.b64encode(source.getvalue()).decode('ascii')}
    original = draft(client, {'kind': 'image', 'image': image, 'caption': '', 'mode': 'bw', 'fit': True})
    created = client.post('/studio/api/labels', json={'name': 'Box', 'draft': original})
    assert created.status_code == 201
    saved = created.json
    label_id = saved['id']
    assert client.get('/studio/api/labels').json['labels'][0]['draft'] == original
    assert client.get(f'/studio/api/labels/{label_id}').json['draft'] == original
    assert_png(client.post('/studio/api/preview', json=saved['draft']))
    updated = client.put(f'/studio/api/labels/{label_id}', json={'name': 'Box 2', 'draft': original})
    assert updated.status_code == 200
    assert updated.json['id'] == label_id
    assert updated.json['name'] == 'Box 2'
    assert client.delete(f'/studio/api/labels/{label_id}').json == {'success': True}
    assert client.get('/studio/api/labels').json['labels'] == []


@pytest.mark.parametrize('change', [
    {'fontSize': 201}, {'margin': -1}, {'color': 'red'}, {'highRes': 'yes'},
    {'sizeId': 'made-up'}, {'font': 'made-up,Regular'},
    {'content': {'kind': 'text', 'text': ''}},
    {'content': {'kind': 'qr', 'code': '', 'caption': ''}},
    {'content': {'kind': 'image', 'image': {'name': 'x.png', 'mime': 'image/png', 'base64': '!!!!'},
                 'caption': '', 'mode': 'bw', 'fit': True}},
])
def test_invalid_drafts_are_rejected_by_preview_and_save(client, change):
    invalid = draft(client)
    invalid.update(change)
    assert client.post('/studio/api/preview', json=invalid).status_code == 400
    assert client.post('/studio/api/labels', json={'name': 'Invalid', 'draft': invalid}).status_code == 400


def test_simulator_is_explicit_and_physical_absence_is_rejected(client, tmp_path):
    assert client.get('/studio/api/status').json['state'] == 'simulation'
    simulated = client.post('/studio/api/print', json={'draft': draft(client), 'copies': 1, 'cut': 'each'})
    assert simulated.status_code == 200
    assert simulated.json['kind'] == 'simulated'
    client.application.config['PRINTER_PRINTER'] = 'file:///dev/usb/absent-studio-test'
    assert client.get('/studio/api/status').json['state'] == 'offline'
    refused = client.post('/studio/api/print', json={'draft': draft(client), 'copies': 1, 'cut': 'each'})
    assert refused.status_code == 503
    assert not refused.json.get('kind') == 'simulated'


def test_physical_lock_contention_reports_busy(client, tmp_path):
    client.application.config['PRINTER_PRINTER'] = 'file:///dev/usb/absent-studio-test'
    lock_path = client.application.config['STUDIO_PRINTER_LOCK']
    with open(lock_path, 'a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert client.get('/studio/api/status').json['state'] == 'busy'
        response = client.post('/studio/api/print', json={'draft': draft(client), 'copies': 1, 'cut': 'end'})
        assert response.status_code == 409
        fcntl.flock(lock, fcntl.LOCK_UN)


def test_print_limits_and_no_client_printer_override(client):
    for copies in (0, 101, True):
        assert client.post('/studio/api/print', json={'draft': draft(client), 'copies': copies, 'cut': 'each'}).status_code == 400
    client.application.config['PRINTER_PRINTER'] = 'file:///dev/usb/absent-studio-test'
    response = client.post('/studio/api/print', json={
        'draft': draft(client), 'copies': 1, 'cut': 'each', 'printer': 'simulation'})
    assert response.status_code == 503


def test_ql800_size_catalog_and_status_require_loaded_matching_roll(client):
    config = client.get('/studio/api/config').json
    ids = {entry['id'] for entry in config['sizes']}
    assert '62' in ids and '62red' in ids and '102' not in ids
    raw = {'model': 'QL-800', 'status_type': 'Reply to status request', 'status_code': 0,
           'phase_type': 'Waiting to receive', 'media_type': 'Continuous length tape',
           'media_width': 62, 'media_length': 0, 'errors': []}
    with client.application.app_context():
        ready = _status_from_raw(raw, 'QL-800', '62')
        assert ready['state'] == 'ready'
        assert ready['media'] == '62 mm Continuous length tape'
        assert _status_from_raw(raw, 'QL-800', '29')['state'] == 'error'
        assert _status_from_raw({**raw, 'media_type': 'No media', 'media_width': 0}, 'QL-800')['state'] == 'error'
        assert _status_from_raw({**raw, 'phase_type': 'Printing state'}, 'QL-800')['state'] == 'busy'
        assert _status_from_raw({**raw, 'model': 'QL-700'}, 'QL-800')['state'] == 'error'


def test_request_limit_rejects_large_json(client):
    response = client.post('/studio/api/preview', data=b'x' * (8 * 1024 * 1024 + 1),
                           content_type='application/json')
    assert response.status_code == 413
    assert response.json['message'] == 'Request is too large.'


def test_pdf_converter_uses_only_first_page(monkeypatch):
    import app.utils as utils
    requested = {}

    def convert(data, **options):
        requested.update(options)
        return [Image.new('RGB', (1, 1), 'white')]

    monkeypatch.setattr(utils, 'convert_from_bytes', convert)
    image = pdffile_to_image(FileStorage(stream=io.BytesIO(b'%PDF-test'), filename='test.pdf'), 300)
    assert image.size == (1, 1)
    assert requested['first_page'] == 1
    assert requested['last_page'] == 1


@pytest.mark.parametrize("transient_empty", [False, True])
def test_file_printer_status_reads_reply_and_times_out_when_silent(monkeypatch, transient_empty):
    master, slave = pty.openpty()
    tty.setraw(slave)
    path = os.ttyname(slave)
    raw = bytearray(32)
    raw[:3] = b'\x80\x20\x42'
    raw[3], raw[4], raw[10], raw[11] = 52, 56, 62, 10
    seen = []
    os.write(master, bytes(32))
    original_read = os.read
    pending_empty = [True] if transient_empty else []
    def read(fd, size):
        if seen and pending_empty:
            pending_empty.pop()
            return b''
        return original_read(fd, size)
    monkeypatch.setattr(os, 'read', read)

    def reply():
        seen.append(os.read(master, 3))
        os.write(master, raw[:12])
        os.write(master, raw[12:])

    old_handler = signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        thread = threading.Thread(target=reply)
        thread.start()
        status = query_printer_status('file://' + path, timeout=1)
        thread.join(timeout=1)
        assert seen == [b'\x1b\x69\x53']
        assert status['model'] == 'QL-800'
        assert status['media_width'] == 62
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            query_printer_status('file://' + path, timeout=0.05)
        assert time.monotonic() - started < 0.5
    finally:
        os.close(master)
        os.close(slave)
        signal.signal(signal.SIGHUP, old_handler)


def test_save_rejects_corrupt_image_with_valid_header(client):
    image = {'name': 'broken.png', 'mime': 'image/png',
             'base64': base64.b64encode(b'\x89PNG\r\n\x1a\ninvalid').decode('ascii')}
    invalid = draft(client, {'kind': 'image', 'image': image, 'caption': '', 'mode': 'bw', 'fit': True})
    assert client.post('/studio/api/labels', json={'name': 'Broken', 'draft': invalid}).status_code == 400
    assert client.get('/studio/api/labels').json['labels'] == []


@pytest.mark.parametrize('loaded', [
    {'media_width': 29, 'media_length': 0, 'media_color': 'black'},
    {'media_width': 62, 'media_length': 100, 'media_type': 'Die-cut labels', 'media_color': 'black'},
    {'media_width': 62, 'media_length': 0, 'media_color': 'black-red'},
])
def test_print_rechecks_changed_roll_before_render_or_send(client, monkeypatch, tmp_path, loaded):
    import app.studio as studio
    device = tmp_path / 'fake-usb'
    device.touch()
    client.application.config['PRINTER_PRINTER'] = 'file://' + str(device)
    raw = {'model': 'QL-800', 'status_type': 'Reply to status request', 'status_code': 0,
           'phase_type': 'Waiting to receive', 'media_type': 'Continuous length tape',
           'media_width': 62, 'media_length': 0, 'media_color': 'black', 'errors': []}
    calls = []
    def query(device):
        calls.append(device)
        return dict(raw)
    monkeypatch.setattr(studio, 'query_printer_status', query)
    label = draft(client)
    label['sizeId'] = '62'
    assert client.get('/studio/api/status').json['matchingSizes'] == ['62']
    raw.update(loaded)
    monkeypatch.setattr(studio, '_render', lambda *args: pytest.fail('Rendered a mismatched job'))
    monkeypatch.setattr(studio.PrinterQueue, 'process_queue', lambda *args: pytest.fail('Sent a mismatched job'))
    result = client.post('/studio/api/print', json={
        'draft': label, 'copies': 1, 'cut': 'each', 'confirmRedMedia': True})
    assert result.status_code == 503
    assert len(calls) == 2
