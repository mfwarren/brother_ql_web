"""Fetch bounded public HTTPS images, pinning the validated destination."""
import base64
import http.client
import io
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit, urljoin

from PIL import Image, UnidentifiedImageError

MAX_BYTES = 5 * 1024 * 1024


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=8, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def destination(url):
    parts = urlsplit(url)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
            or parts.port not in (None, 443)):
        raise ValueError('Use a public HTTPS image URL without a login or custom port.')
    addresses = {entry[4][0] for entry in socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError('Image URLs must point to a public internet address.')
    return parts, sorted(addresses)[0]


def _fetch_image(url):
    if not isinstance(url, str) or len(url) > 2000:
        raise ValueError('Invalid image URL.')
    for _ in range(4):
        parts, address = destination(url)
        connection = PinnedHTTPSConnection(parts.hostname, address)
        try:
            path = parts.path or '/'
            if parts.query:
                path += '?' + parts.query
            connection.request('GET', path, headers={'Accept': 'image/png,image/jpeg', 'User-Agent': 'LabelStudio/0.1'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError('Image redirect has no destination.')
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(f'Image server returned HTTP {response.status}. Use a direct image link.')
            payload = response.read(MAX_BYTES + 1)
            if len(payload) > MAX_BYTES:
                raise ValueError('Image exceeds 5 MB.')
            with Image.open(io.BytesIO(payload)) as image:
                if image.format not in ('PNG', 'JPEG'):
                    raise ValueError('Image URLs must return PNG or JPEG files.')
                if image.width * image.height > 16_000_000:
                    raise ValueError('Image exceeds 16 megapixels.')
                mime = 'image/png' if image.format == 'PNG' else 'image/jpeg'
                image.verify()
            return {'name': 'downloaded.png' if mime == 'image/png' else 'downloaded.jpg',
                    'mime': mime, 'base64': base64.b64encode(payload).decode('ascii')}
        finally:
            connection.close()
    raise ValueError('Too many image redirects.')


def fetch_image(url):
    try:
        return _fetch_image(url)
    except socket.gaierror:
        raise ValueError('Image host could not be found. Check the URL.') from None
    except ssl.SSLError:
        raise ValueError("The image site's HTTPS certificate could not be verified.") from None
    except TimeoutError:
        raise ValueError('Image download timed out. Try again or use a smaller image.') from None
    except UnidentifiedImageError:
        raise ValueError('URL did not return a PNG or JPEG. Use a direct image link, not a web page.') from None
