import base64
import io

import pytest
from PIL import Image

from app import remote_images
from app.bulk_labels import merge
from test_studio import client, draft


@pytest.mark.parametrize('url', ['http://example.com/a.png', 'https://user:pass@example.com/a.png', 'https://example.com:8443/a.png'])
def test_reject_unsupported_urls(url):
    with pytest.raises(ValueError):
        remote_images.destination(url)


@pytest.mark.parametrize('address', ['127.0.0.1', '192.168.1.2', '169.254.169.254', '::1'])
def test_private_destinations_blocked(monkeypatch, address):
    monkeypatch.setattr(remote_images.socket, 'getaddrinfo', lambda *a, **k: [(None, None, None, None, (address, 443))])
    with pytest.raises(ValueError, match='public'):
        remote_images.destination('https://example.com/image.png')


def test_download_pins_resolved_address_and_validates_image(monkeypatch):
    png = io.BytesIO()
    Image.new('RGB', (20, 20), 'red').save(png, 'PNG')
    monkeypatch.setattr(remote_images.socket, 'getaddrinfo', lambda *a, **k: [(None, None, None, None, ('93.184.216.34', 443))])
    class Response:
        status = 200
        def read(self, limit): return png.getvalue()
    class Connection:
        def __init__(self, host, address):
            assert host == 'example.com' and address == '93.184.216.34'
        def request(self, *a, **k): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(remote_images, 'PinnedHTTPSConnection', Connection)
    image = remote_images.fetch_image('https://example.com/photo.png')
    assert base64.b64decode(image['base64']) == png.getvalue()
    assert image['mime'] == 'image/png'


def test_redirect_to_private_destination_blocked(monkeypatch):
    def resolve(host, *a, **k):
        return [(None, None, None, None, ('127.0.0.1' if host == 'local.test' else '93.184.216.34', 443))]
    monkeypatch.setattr(remote_images.socket, 'getaddrinfo', resolve)
    class Response:
        status = 302
        def getheader(self, key): return 'https://local.test/private'
    class Connection:
        def __init__(self, host, address): assert host == 'example.com'
        def request(self, *a, **k): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(remote_images, 'PinnedHTTPSConnection', Connection)
    with pytest.raises(ValueError, match='public'):
        remote_images.fetch_image('https://example.com/photo.png')


def test_image_column_prepares_for_download_and_freezes_payload(client, monkeypatch):
    label = draft(client, {'kind': 'image', 'image': None, 'imageUrl': '{{Photo}}', 'caption': '{{Name}}', 'mode': 'bw', 'fit': True})
    response = client.post('/studio/api/bulk/prepare', json={
        'template': label, 'csv': 'Photo,Name\nhttps://example.com/a.png,First\nhttps://example.com/b.png,Second'})
    rows = response.json['rows']
    assert rows[0]['draft']['content']['imageUrl'] == 'https://example.com/a.png'
    assert rows[1]['draft']['content']['caption'] == 'Second'
    png = io.BytesIO()
    Image.new('RGB', (20, 20), 'black').save(png, 'PNG')
    image = {'name':'a.png', 'mime':'image/png', 'base64':base64.b64encode(png.getvalue()).decode()}
    monkeypatch.setattr(remote_images, 'fetch_image', lambda url: image)
    downloaded = client.post('/studio/api/bulk/image', json={'url':'https://example.com/a.png'})
    assert downloaded.json == image
    frozen = rows[0]['draft']
    frozen['content'].pop('imageUrl')
    frozen['content']['image'] = downloaded.json
    monkeypatch.setattr(remote_images, 'fetch_image', lambda url: pytest.fail('Preview must not fetch again'))
    assert client.post('/studio/api/preview', json=frozen).status_code == 200
