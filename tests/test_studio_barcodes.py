import io

import pytest
import zxingcpp
from PIL import Image
from test_studio import client, draft


@pytest.mark.parametrize('format,value,expected', [
    ('code128', 'SKU-0042', 'SKU-0042'),
    ('ean13', '590123412345', '5901234123457'),
    ('ean8', '9638507', '96385074'),
    ('upca', '03600029145', '0036000291452'),
])
@pytest.mark.parametrize('caption', ['', 'Inventory shelf'])
def test_barcode_preview_save_and_print(client, format, value, expected, caption):
    label = draft(client, {'kind': 'barcode', 'format': format, 'code': value, 'caption': caption})
    response = client.post('/studio/api/preview', json=label)
    assert response.status_code == 200
    decoded = zxingcpp.read_barcode(Image.open(io.BytesIO(response.data)))
    assert decoded is not None
    assert decoded.text == expected
    saved = client.post('/studio/api/labels', json={'name': 'Inventory', 'draft': label})
    assert saved.status_code == 201
    loaded = client.get('/studio/api/labels/' + saved.json['id']).json['draft']
    assert loaded == label
    result = client.post('/studio/api/print', json={'draft': loaded, 'copies': 1, 'cut': 'each'})
    assert result.status_code == 200
    assert result.json['kind'] == 'simulated'


@pytest.mark.parametrize('format,value', [
    ('ean13', '5901234123458'), ('ean8', '123'), ('upca', 'abc'),
    ('code128', 'Café'), ('code128', 'X' * 80), ('unknown', '123'), ('code128', ''),
])
def test_invalid_barcodes_rejected_on_preview_save_and_print(client, format, value):
    label = draft(client, {'kind': 'barcode', 'format': format, 'code': value, 'caption': ''})
    assert client.post('/studio/api/preview', json=label).status_code == 400
    assert client.post('/studio/api/labels', json={'name': 'Invalid', 'draft': label}).status_code == 400
    assert client.post('/studio/api/print', json={'draft': label, 'copies': 1, 'cut': 'each'}).status_code == 400


@pytest.mark.parametrize('size,orientation', [('29x90', 'standard'), ('29x90', 'rotated'), ('62', 'rotated')])
def test_barcode_on_die_cut_and_rotated_labels(client, size, orientation):
    label = draft(client, {'kind': 'barcode', 'format': 'code128', 'code': 'SKU-0042', 'caption': 'Stock'})
    label.update(sizeId=size, orientation=orientation, fontSize=30)
    response = client.post('/studio/api/preview', json=label)
    assert response.status_code == 200
    decoded = zxingcpp.read_barcode(Image.open(io.BytesIO(response.data)))
    assert decoded is not None
    assert decoded.text == 'SKU-0042'
