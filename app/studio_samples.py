"""Starter documents include black-only and explicitly marked black/red media."""
import base64
from pathlib import Path


def starter_labels(fonts, default_font):
    preferred = 'DejaVu Sans,Bold'
    font = preferred if preferred in fonts else default_font
    base = {'sizeId': '62', 'orientation': 'standard', 'font': font,
            'fontSize': 56, 'align': 'center', 'color': 'black',
            'margin': 24, 'highRes': False}
    image = base64.b64encode((Path(__file__).parent / 'samples' / 'handling.png').read_bytes()).decode('ascii')
    barcode = base64.b64encode((Path(__file__).parent / 'samples' / 'inventory.png').read_bytes()).decode('ascii')
    fragile = base64.b64encode((Path(__file__).parent / 'samples' / 'fragile.png').read_bytes()).decode('ascii')
    return [
        ('storage-bin', 'Storage bin', {**base, 'content': {
            'kind': 'text', 'text': 'CABLES & ADAPTERS\nUSB / HDMI / POWER'}}),
        ('asset-tag', 'Asset tag · QR', {**base, 'fontSize': 42, 'content': {
            'kind': 'qr', 'code': 'ASSET-0042', 'caption': 'ASSET 0042'}}),
        ('handling', 'This way up · Image', {**base, 'fontSize': 42, 'content': {
            'kind': 'image', 'image': {'name': 'handling.png', 'mime': 'image/png', 'base64': image},
            'caption': 'THIS WAY UP', 'mode': 'bw', 'fit': True}}),
        ('mailing-address', 'Mailing address', {**base, 'font': default_font, 'fontSize': 42, 'align': 'left', 'content': {
            'kind': 'text', 'text': 'ALEX MORGAN\n123 EXAMPLE STREET\nTORONTO ON  A1A 1A1'}}),
        ('file-folder', 'File folder · Receipts', {**base, 'fontSize': 50, 'align': 'left', 'content': {
            'kind': 'text', 'text': '2026  /  RECEIPTS\nHOME & OFFICE'}}),
        ('visitor-badge', 'Visitor name badge', {**base, 'fontSize': 70, 'content': {
            'kind': 'text', 'text': 'HELLO\nI AM ALEX'}}),
        ('inventory-barcode', 'Inventory · Code 128', {**base, 'fontSize': 38, 'content': {
            'kind': 'image', 'image': {'name': 'SKU-0042-code128.png', 'mime': 'image/png', 'base64': barcode},
            'caption': 'SKU-0042  /  USB-C CABLE', 'mode': 'bw', 'fit': True}}),
        ('guest-wifi', 'Guest Wi-Fi · QR', {**base, 'fontSize': 30, 'content': {
            'kind': 'qr', 'code': 'WIFI:T:WPA;S:Guest Wi-Fi;P:change-me-123;;',
            'caption': 'GUEST WI-FI\nReplace sample network details'}}),
        ('fragile-red', 'Fragile · Black/red tape', {**base, 'sizeId': '62red', 'orientation': 'standard', 'margin': 12, 'content': {
            'kind': 'image', 'image': {'name': 'fragile.png', 'mime': 'image/png', 'base64': fragile},
            'caption': '', 'mode': 'red', 'fit': True}}),
    ]
