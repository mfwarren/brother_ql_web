"""Bounded, complete transfers through Linux usblp; callers serialize the device."""
import os
import select
import time

from brother_ql.reader import interpret_response

HEADER = b'\x80\x20\x42'


def decode_status(packet):
    state = interpret_response(packet)
    state['raw_status'] = bytes(packet).hex()
    state['media_color_code'] = packet[25]
    # Field-observed QL two-colour flag; older firmware can leave it unset.
    state['media_color'] = ('black-red' if state['model'] in ('QL-800', 'QL-810W', 'QL-820NWB')
                            and packet[25] & 0x80 else 'unknown')
    return state


def write_all(fd, data, deadline):
    remaining = memoryview(data)
    while remaining:
        if time.monotonic() >= deadline:
            raise TimeoutError('USB write timed out; the job may be incomplete. Do not automatically reprint.')
        try:
            written = os.write(fd, remaining[:16384])
        except BlockingIOError:
            written = 0
        if written:
            remaining = remaining[written:]
        else:
            select.select([], [fd], [], min(.05, max(0, deadline - time.monotonic())))
            time.sleep(.001)


def read_status(fd, buffer, deadline):
    while time.monotonic() < deadline:
        start = buffer.find(HEADER)
        if start >= 0:
            del buffer[:start]
            if len(buffer) >= 32:
                packet = bytes(buffer[:32])
                del buffer[:32]
                return decode_status(packet)
        elif len(buffer) > 2:
            del buffer[:-2]
        if not select.select([fd], [], [], min(.05, max(0, deadline - time.monotonic())))[0]:
            continue
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            chunk = b''
        if chunk:
            buffer.extend(chunk)
        else:
            time.sleep(.005)
    raise TimeoutError('Printer response timed out')


def drain(fd):
    deadline = time.monotonic() + .1
    while time.monotonic() < deadline:
        try:
            os.read(fd, 4096)
        except BlockingIOError:
            pass
        time.sleep(.005)


def query_status(device, timeout=3):
    fd = os.open(device[7:], os.O_RDWR | os.O_NONBLOCK)
    try:
        drain(fd)
        deadline = time.monotonic() + timeout
        write_all(fd, b'\x1biS', deadline)
        buffer = bytearray()
        while True:
            state = read_status(fd, buffer, deadline)
            if state['status_code'] == 0:
                return state
    finally:
        os.close(fd)


def send_raster(device, data, timeout=90, expected_jobs=1):
    fd = os.open(device[7:], os.O_RDWR | os.O_NONBLOCK)
    try:
        drain(fd)
        deadline = time.monotonic() + timeout
        write_all(fd, data, deadline)
        buffer = bytearray()
        completed = 0
        ready_count = 0
        while completed < expected_jobs or ready_count < expected_jobs:
            try:
                state = read_status(fd, buffer, deadline)
            except TimeoutError as error:
                raise TimeoutError('Print completion was not confirmed. Check the label before retrying; power-cycle the printer if it remains busy.') from error
            if state['errors']:
                raise RuntimeError(', '.join(state['errors']))
            if state['status_code'] == 1:
                completed += 1
            if state['status_code'] == 6 and state['phase_type'] == 'Waiting to receive':
                ready_count += 1
        return {'did_print': completed == expected_jobs, 'ready_for_next_job': ready_count >= expected_jobs}
    finally:
        os.close(fd)
