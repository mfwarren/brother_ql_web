import io

import pytest
import zxingcpp
from PIL import Image
from test_studio import client, draft


@pytest.mark.parametrize('value', ['https://example.com', 'Café / kitchen', 'WIFI:T:WPA;S:Guest;P:example-only;;'])
def test_qr_decodes_to_exact_user_content(client, value):
    label = draft(client, {'kind': 'qr', 'code': value, 'caption': 'Scan for details'})
    response = client.post('/studio/api/preview', json=label)
    assert response.status_code == 200
    decoded = zxingcpp.read_barcode(Image.open(io.BytesIO(response.data)))
    assert decoded is not None
    assert decoded.text == value


@pytest.mark.parametrize('name,value', [('Inventory · Code 128', 'SKU-0042'), ('Guest Wi-Fi · QR', 'WIFI:T:WPA;S:Guest Wi-Fi;P:change-me-123;;')])
def test_sample_codes_decode(client, name, value):
    client.application.config['STUDIO_SEED_SAMPLES'] = True
    labels = client.get('/studio/api/labels').json['labels']
    label = next(label for label in labels if label['name'] == name)
    response = client.post('/studio/api/preview', json=label['draft'])
    decoded = zxingcpp.read_barcode(Image.open(io.BytesIO(response.data)))
    assert decoded is not None
    assert decoded.text == value
