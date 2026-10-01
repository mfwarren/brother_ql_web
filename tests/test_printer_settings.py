import os
import pty
import threading
import tty

import pytest

from printer_settings import QL800Power, SettingsError, decode_reply

STATUS_REPLY = bytes.fromhex('802042343830000000003e0a0000150000000000000000000001000000000000')
POWER_REPLY = bytes.fromhex('802042343830000000003e0a000015000000f000000000000000000000000601')


def test_observed_ql800_reply_decodes_sixty_minutes():
    assert decode_reply(POWER_REPLY, 0xf0) == 60


@pytest.mark.parametrize('index,value', [(4, 0x35), (8, 1), (18, 0), (19, 1), (30, 255), (31, 0)])
def test_rejects_other_models_errors_and_unrecognized_settings(index, value):
    reply = bytearray(POWER_REPLY)
    reply[index] = value
    with pytest.raises(SettingsError):
        decode_reply(bytes(reply), 0xf0)


def test_linux_exchange_sets_only_auto_off_and_verifies_readback():
    master, slave = pty.openpty()
    tty.setraw(slave)
    os.set_blocking(slave, False)
    os.write(master, POWER_REPLY)
    commands = []
    errors = []
    disabled = POWER_REPLY[:30] + b'\0\1'
    exchanges = [(3, STATUS_REPLY), (5, POWER_REPLY), (6, None), (3, STATUS_REPLY), (5, disabled)]
    def emulate():
        try:
            for length, response in exchanges:
                data = b''
                while len(data) < length:
                    data += os.read(master, length - len(data))
                commands.append(data)
                if response:
                    os.write(master, response[:9])
                    os.write(master, response[9:])
        except OSError as exc:
            errors.append(exc)
    worker = threading.Thread(target=emulate, daemon=True)
    worker.start()
    try:
        result = QL800Power(slave).set(0)
        assert result['before']['minutes'] == 60
        assert result['after']['minutes'] == 0
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert not errors
        assert [command.hex() for command in commands] == ['1b6953', '1b69554101', '1b6955410000', '1b6953', '1b69554101']
    finally:
        os.close(slave)
        os.close(master)


def test_silent_printer_times_out():
    master, slave = pty.openpty()
    tty.setraw(slave)
    os.set_blocking(slave, False)
    try:
        with pytest.raises(SettingsError, match='timed out'):
            QL800Power(slave, timeout=0.02).read()
    finally:
        os.close(slave)
        os.close(master)


@pytest.mark.parametrize('minutes', [-10, 1, 70, True])
def test_invalid_value_never_touches_usb(minutes):
    with pytest.raises(ValueError):
        QL800Power(-1).set(minutes)


def test_zero_length_usb_read_is_transient(monkeypatch):
    master, slave = pty.openpty()
    tty.setraw(slave)
    os.set_blocking(slave, False)
    original = os.read
    empty = [True]
    def read(fd, size):
        if fd == slave and empty:
            empty.pop()
            return b''
        return original(fd, size)
    monkeypatch.setattr(os, 'read', read)
    try:
        os.write(master, POWER_REPLY)
        value, _ = QL800Power(slave, timeout=0.2).query(bytes.fromhex('1b69554101'), 0xf0)
        assert value == 60
    finally:
        os.close(slave)
        os.close(master)
