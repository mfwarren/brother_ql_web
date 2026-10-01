"""QL-800 auto power-off configuration over Linux usblp.

Protocol discovery: Marc Schuetze, brother-ql700-settings (MIT).
QL-800 replies independently observed on 2026-09-28. No generic settings scan.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import select
import time

STATUS = bytes.fromhex('1b6953')
GET_AUTO_OFF = bytes.fromhex('1b69554101')
SET_AUTO_OFF = bytes.fromhex('1b69554100')
MODEL_HEADER = bytes.fromhex('802042343830')


class SettingsError(RuntimeError):
    pass


def decode_reply(reply, status_type):
    if len(reply) != 32 or reply[:6] != MODEL_HEADER:
        raise SettingsError('Expected a complete QL-800 reply')
    if reply[18] != status_type or reply[8:10] != b'\0\0' or reply[19] != 0:
        raise SettingsError('Printer replied with an unexpected status, error, or busy phase')
    if status_type == 0xf0:
        if reply[31] != 1 or reply[30] > 6:
            raise SettingsError('Unrecognized auto power-off value or acknowledgement')
        return reply[30] * 10
    return None


class QL800Power:
    def __init__(self, fd, timeout=3):
        self.fd = fd
        self.timeout = timeout

    def write(self, command):
        deadline = time.monotonic() + self.timeout
        remaining = memoryview(command)
        while remaining:
            wait = deadline - time.monotonic()
            if wait <= 0 or not select.select([], [self.fd], [], wait)[1]:
                raise SettingsError('USB write timed out; do not retry a setting write blindly')
            try:
                count = os.write(self.fd, remaining)
            except BlockingIOError:
                continue
            if not count:
                raise SettingsError('USB connection closed')
            remaining = remaining[count:]

    def query(self, command, status_type):
        self.write(command)
        deadline = time.monotonic() + self.timeout
        reply = b''
        while len(reply) < 32:
            wait = deadline - time.monotonic()
            if wait <= 0 or not select.select([self.fd], [], [], wait)[0]:
                raise SettingsError('USB reply timed out')
            try:
                chunk = os.read(self.fd, 32 - len(reply))
            except BlockingIOError:
                continue
            if not chunk:
                time.sleep(min(0.01, max(0, deadline - time.monotonic())))
                continue
            reply += chunk
        value = decode_reply(reply, status_type)
        return value, reply.hex()

    def drain(self):
        deadline = time.monotonic() + 0.1
        while time.monotonic() < deadline:
            if select.select([self.fd], [], [], 0)[0]:
                try:
                    os.read(self.fd, 4096)
                except BlockingIOError:
                    pass
            time.sleep(0.005)

    def read(self):
        self.drain()
        self.query(STATUS, 0)
        minutes, raw = self.query(GET_AUTO_OFF, 0xf0)
        return {'minutes': minutes, 'reply': raw}

    def set(self, minutes):
        if type(minutes) is not int or minutes not in range(0, 61, 10):
            raise ValueError('Minutes must be 0, 10, 20, 30, 40, 50, or 60')
        before = self.read()
        if before['minutes'] == minutes:
            return {'changed': False, 'before': before, 'after': before}
        self.write(SET_AUTO_OFF + bytes([minutes // 10]))
        time.sleep(0.5)
        try:
            after = self.read()
        except (OSError, SettingsError) as exc:
            raise SettingsError('Setting was sent but verification failed; read it before retrying') from exc
        if after['minutes'] != minutes:
            raise SettingsError(f"Read-back mismatch: requested {minutes}, received {after['minutes']}")
        return {'changed': True, 'before': before, 'after': after}


def main():
    parser = argparse.ArgumentParser(description='Read/set QL-800 auto power-off on Linux. 0 disables it.')
    parser.add_argument('operation', choices=['get', 'set'])
    parser.add_argument('minutes', nargs='?', type=int, choices=range(0, 61, 10))
    parser.add_argument('--device', default='/dev/usb/lp0')
    parser.add_argument('--lock', default=str(Path(__file__).resolve().parent / 'instance/studio-printer.lock'))
    args = parser.parse_args()
    if (args.operation == 'set') != (args.minutes is not None):
        parser.error('Supply minutes only with set')
    try:
        Path(args.lock).parent.mkdir(parents=True, exist_ok=True)
        with open(args.lock, 'a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd = os.open(args.device, os.O_RDWR | os.O_NONBLOCK)
            try:
                printer = QL800Power(fd)
                result = printer.read() if args.operation == 'get' else printer.set(args.minutes)
                print(json.dumps(result))
            finally:
                os.close(fd)
    except (OSError, SettingsError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
