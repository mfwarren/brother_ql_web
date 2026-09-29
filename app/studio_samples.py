"""Starter documents use installed fonts and standard 62 mm black tape."""
import base64
from pathlib import Path


def starter_labels(fonts, default_font):
    preferred = 'DejaVu Sans,Bold'
    font = preferred if preferred in fonts else default_font
    base = {'sizeId': '62', 'orientation': 'standard', 'font': font,
            'fontSize': 56, 'align': 'center', 'color': 'black',
            'margin': 24, 'highRes': False}
    image = base64.b64encode((Path(__file__).parent / 'samples' / 'handling.png').read_bytes()).decode('ascii')
    return [
        ('storage-bin', 'Storage bin', {**base, 'content': {
            'kind': 'text', 'text': 'CABLES & ADAPTERS\nUSB / HDMI / POWER'}}),
        ('asset-tag', 'Asset tag · QR', {**base, 'fontSize': 42, 'content': {
            'kind': 'qr', 'code': 'ASSET-0042', 'caption': 'ASSET 0042'}}),
        ('handling', 'This way up · Image', {**base, 'fontSize': 42, 'content': {
            'kind': 'image', 'image': {'name': 'handling.png', 'mime': 'image/png', 'base64': image},
            'caption': 'THIS WAY UP', 'mode': 'bw', 'fit': True}}),
    ]
