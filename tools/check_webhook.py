#!/usr/bin/env python3
"""Verify the optional image webhook against a disposable simulation server."""
import argparse
import base64
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('checks', Path(__file__).with_name('check_rust_api.py'))
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', required=True)
parser.add_argument('--password', required=True)
args = parser.parse_args()
client = checks.Client(args.url)
client.assert_simulation()
endpoint = '/labeldesigner/api/webhook/print'
image = (Path(__file__).parents[1] / 'server/tests/fixtures/2.png').read_bytes()
body = {'images': [base64.b64encode(image).decode()], 'label_size': '62', 'image_mode': 'grayscale'}
assert client.request(endpoint, 'POST', body, expected=401)[0]['success'] is False
assert client.request(endpoint, 'POST', {**body, 'password': 'incorrect'}, expected=401)[0]['success'] is False
result, _ = client.request(endpoint, 'POST', body, headers={'Authorization': 'Bearer ' + args.password})
assert result == {'success': True, 'count': 1}, result
result, _ = client.request(endpoint, 'POST', {**body, 'password': args.password, 'orientation': 'rotated'})
assert result == {'success': True, 'count': 1}, result
boundary = 'LabelStudioWebhookBoundary'
parts = []
for name, value in [('password', args.password), ('label_size', '29x90'), ('image_mode', 'bw')]:
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="images"; filename="sample.png"\r\nContent-Type: image/png\r\n\r\n'.encode() + image + b'\r\n')
parts.append(f'--{boundary}--\r\n'.encode())
result, _ = client.request(endpoint, 'POST', b''.join(parts), headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
assert result == {'success': True, 'count': 1}, result

# A full Letter page at 600 dpi exceeds the decoder's intermediate-image limit.
# The webhook must rasterize the vector PDF directly at the label dimensions.
stream = b'0 g 396 20 0.4 752 re f 396.8 20 0.4 752 re f\n'
objects = [
    b'<< /Type /Catalog /Pages 2 0 R >>',
    b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>',
    b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'endstream',
]
pdf = bytearray(b'%PDF-1.4\n')
offsets = []
for number, obj in enumerate(objects, 1):
    offsets.append(len(pdf))
    pdf.extend(f'{number} 0 obj\n'.encode() + obj + b'\nendobj\n')
xref = len(pdf)
pdf.extend(b'xref\n0 5\n0000000000 65535 f \n')
for offset in offsets:
    pdf.extend(f'{offset:010} 00000 n \n'.encode())
pdf.extend(f'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
for size in ['62', '29x90']:
    result, _ = client.request(endpoint, 'POST', {
        'password': args.password, 'label_size': size, 'high_res': 1,
        'images': [base64.b64encode(pdf).decode()],
    })
    assert result == {'success': True, 'count': 1}, result
print('PASS webhook authentication, JSON images, rotation, multipart upload, and high-resolution Letter PDFs on continuous/fixed labels; simulation only')
