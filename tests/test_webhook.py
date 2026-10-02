import base64
import fcntl
import io

import pytest

from PIL import Image

from test_studio import client


def image_payload():
    output = io.BytesIO()
    Image.new('RGB', (80, 40), 'black').save(output, format='PNG')
    return {'images': [base64.b64encode(output.getvalue()).decode()], 'label_size': '62'}


def test_webhook_authentication_and_raster_print(client, monkeypatch, tmp_path):
    monkeypatch.setattr('app.labeldesigner.printer.SIMULATED_LABELS_DIR', str(tmp_path))
    endpoint = '/labeldesigner/api/webhook/print'
    payload = image_payload()
    assert client.post(endpoint, json=payload).status_code == 403
    client.application.config['WEBHOOK_PASSWORD'] = 'test-webhook-password'
    assert client.post(endpoint, json=payload).status_code == 401
    response = client.post(endpoint, json=payload, headers={'Authorization': 'Bearer test-webhook-password'})
    assert response.status_code == 200
    assert response.json['success'] is True
    assert list(tmp_path.glob('*.png'))


def test_webhook_respects_print_lock(client, monkeypatch):
    client.application.config.update(WEBHOOK_PASSWORD='test-password', PRINTER_PRINTER='file:///dev/usb/lp0')
    monkeypatch.setattr('app.labeldesigner.printer.PrinterQueue.process_queue',
                        lambda self: pytest.fail('Printed while lock was held'))
    with open(client.application.config['STUDIO_PRINTER_LOCK'], 'a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        response = client.post('/labeldesigner/api/webhook/print', json={**image_payload(), 'password': 'test-password'})
    assert response.status_code == 400
    assert response.json['message'] == 'Printer busy'


def test_retired_editor_endpoints_are_not_registered(client):
    paths = {rule.rule for rule in client.application.url_map.iter_rules()}
    assert {path for path in paths if path.startswith('/labeldesigner/')} == {
        '/labeldesigner/', '/labeldesigner/api/webhook/print',
    }


def test_webhook_checks_roll_before_sending(client, monkeypatch):
    client.application.config.update(WEBHOOK_PASSWORD='test-password', PRINTER_PRINTER='file:///dev/usb/lp0')
    monkeypatch.setattr('app.printer_service.status_locked', lambda *args, **kwargs: {
        'state': 'error', 'message': 'Loaded roll does not match the requested label.'})
    monkeypatch.setattr('app.labeldesigner.printer.PrinterQueue.process_queue',
                        lambda self: pytest.fail('Sent a label on mismatched media'))
    response = client.post('/labeldesigner/api/webhook/print', json={**image_payload(), 'password': 'test-password'})
    assert response.status_code == 400
    assert 'does not match' in response.json['message']
