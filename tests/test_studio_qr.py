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
