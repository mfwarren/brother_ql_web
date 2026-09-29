import os
import pty
import signal
import threading
import time
import tty

import pytest
from app.labeldesigner import usb_transport as usb


@pytest.fixture(autouse=True)
def ignore_pty_hangup():
    previous = signal.signal(signal.SIGHUP, signal.SIG_IGN)
    yield
    signal.signal(signal.SIGHUP, previous)


def packet(code=0, phase=0, color=1):
    raw = bytearray.fromhex('80 20 42 34 38 30 00 00 00 00 3e 0a 00 00 15 00 00 00 00 00 00 00 00 00 00 01 00 00 00 00 00 00')
    raw[18], raw[19], raw[25] = code, phase, color
    return bytes(raw)


def test_known_ql800_colors_and_unknown_color_codes():
    assert usb.decode_status(packet(color=0x81))['media_color'] == 'black-red'
    assert usb.decode_status(packet(color=1))['media_color'] == 'black'
    assert usb.decode_status(packet(color=0))['media_color'] == 'unknown'


def test_write_all_handles_partial_writes_and_backpressure(monkeypatch):
    received = bytearray()
    attempts = []
    def write(fd, data):
        attempts.append(1)
        if len(attempts) == 2:
            raise BlockingIOError()
        count = min(7, len(data))
        received.extend(data[:count])
        return count
    monkeypatch.setattr(os, 'write', write)
    monkeypatch.setattr(usb.select, 'select', lambda *args: ([], [], []))
    usb.write_all(9, bytes(range(255)), time.monotonic()+1)
    assert received == bytes(range(255))


def test_write_timeout_is_bounded(monkeypatch):
    monkeypatch.setattr(os, 'write', lambda *args: 0)
    monkeypatch.setattr(usb.select, 'select', lambda *args: ([], [], []))
    with pytest.raises(TimeoutError):
        usb.write_all(9, b'abc', time.monotonic()+.01)


def test_status_query_skips_async_phase_notifications():
    master, slave = pty.openpty(); tty.setraw(slave)
    def printer():
        assert os.read(master, 3) == b'\x1biS'
        os.write(master, packet(6, 1) + packet(0, 0))
    worker = threading.Thread(target=printer); worker.start()
    try:
        result = usb.query_status('file://' + os.ttyname(slave), .5)
        assert result['status_code'] == 0
        assert result['phase_type'] == 'Waiting to receive'
    finally:
        worker.join(1); os.close(master); os.close(slave)


def test_send_waits_for_all_jobs_and_reassembles_fragmented_responses():
    master, slave = pty.openpty(); tty.setraw(slave)
    def printer():
        assert os.read(master, 3) == b'job'
        statuses = packet(0) + packet(6) + packet(1) + packet(1) + packet(6)
        for i in range(0, len(statuses), 7):
            os.write(master, statuses[i:i+7]); time.sleep(.001)
    worker = threading.Thread(target=printer); worker.start()
    try:
        result = usb.send_raster('file://' + os.ttyname(slave), b'job', timeout=1, expected_jobs=2)
        assert result == {'did_print': True, 'ready_for_next_job': True}
    finally:
        worker.join(1); os.close(master); os.close(slave)


def test_silent_printer_does_not_leave_open_usb_handle(monkeypatch):
    master, slave = pty.openpty(); tty.setraw(slave)
    closed = []
    original = os.close
    def close(fd):
        closed.append(fd); original(fd)
    monkeypatch.setattr(os, 'close', close)
    try:
        with pytest.raises(TimeoutError, match='Check the label before retrying'):
            usb.send_raster('file://' + os.ttyname(slave), b'job', timeout=.02)
        assert len(closed) == 1
    finally:
        original(master); original(slave)


def test_detected_red_stock_selects_exact_roll_and_rejects_wrong_job():
    from app import create_app
    from app.studio import _status_from_raw
    app = create_app()
    with app.app_context():
        raw = usb.decode_status(packet(color=0x81))
        detected = _status_from_raw(raw, 'QL-800')
        assert detected['matchingSizes'] == ['62red']
        assert detected['mediaColor'] == 'black-red'
        assert '(black/red)' in detected['media']
        assert _status_from_raw(raw, 'QL-800', '62')['state'] == 'error'
        assert _status_from_raw(raw, 'QL-800', '62red')['state'] == 'ready'


def test_verified_black_roll_excludes_red_and_rejects_red_job():
    from app import create_app
    from app.studio import _status_from_raw
    app = create_app()
    raw = usb.decode_status(bytes.fromhex('802042343830000000003e0a0000150000000000000000000001000000000000'))
    with app.app_context():
        assert _status_from_raw(raw, 'QL-800')['matchingSizes'] == ['62']
        assert _status_from_raw(raw, 'QL-800')['mediaColor'] == 'black'
        assert _status_from_raw(raw, 'QL-800', '62red')['state'] == 'error'
        assert _status_from_raw(raw, 'QL-800', '62')['state'] == 'ready'


def test_verified_red_roll_has_one_match():
    from app import create_app
    from app.studio import _status_from_raw
    app = create_app()
    raw = usb.decode_status(bytes.fromhex('802042343830000000003e0a0000230000000000000000000081000000000000'))
    with app.app_context():
        assert _status_from_raw(raw, 'QL-800')['matchingSizes'] == ['62red']
        assert _status_from_raw(raw, 'QL-800')['mediaColor'] == 'black-red'
