#!/usr/bin/env python3
"""Verify request admission happens before large bodies are buffered."""
import argparse
import http.client
import json
import socket
import time
from urllib.parse import urlsplit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', required=True)
args = parser.parse_args()
url = urlsplit(args.url)
assert url.scheme == 'http', 'This local simulation check uses plain HTTP.'
host, port = url.hostname, url.port or 80


def request(path):
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request('GET', path)
        response = connection.getresponse()
        return response.status, response.read(), response.getheader('Retry-After')
    finally:
        connection.close()


assert json.loads(request('/studio/api/config')[1])['mode'] == 'simulation'
pending = []
try:
    for _ in range(4):
        connection = socket.create_connection((host, port), timeout=5)
        pending.append(connection)
        # Leave the body incomplete so the extractor must retain its slot.
        connection.sendall((
            f'POST /studio/api/preview HTTP/1.1\r\nHost: {host}\r\n'
            'Content-Type: application/json\r\nContent-Length: 8388608\r\n'
            'Expect: 100-continue\r\n\r\n'
        ).encode())
        # Hyper sends Continue only when the admitted handler begins reading.
        # Otherwise the probe can take the fourth slot before this upload does.
        response = b''
        while b'\r\n\r\n' not in response:
            chunk = connection.recv(4096)
            assert chunk, 'Upload connection closed before admission.'
            response += chunk
        assert response.startswith(b'HTTP/1.1 100 '), response
        connection.sendall(b'{"text":"' + b'A' * 262144)
    status, body, retry = request('/studio/api/config')
    assert status == 503 and retry == '1', (status, body, retry)
    assert 'busy' in json.loads(body)['message'].lower()
    assert request('/studio/')[0] == 200, 'Static interface must remain available.'
    # Leave every client connected. The server must release stalled body slots itself.
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        if request('/studio/api/config')[0] == 200:
            break
        time.sleep(0.25)
    else:
        raise AssertionError('Stalled uploads did not time out and release their slots.')
finally:
    for connection in pending:
        connection.close()

for _ in range(40):
    status, _, _ = request('/studio/api/config')
    if status == 200:
        break
    time.sleep(0.05)
assert status == 200, 'Disconnected uploads must release their admission slots.'
print('PASS four concurrent incomplete 8 MiB requests hold admission slots; further API requests receive HTTP 503 with Retry-After, static UI stays available, and stalled uploads time out without client disconnection')
