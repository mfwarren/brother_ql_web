"""Shared printer locking, device selection, and media status."""
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from flask import current_app
from app.labeldesigner.printer import query_printer_status
from app.validation import sizes

def lock_path():
    return Path(current_app.config.get('STUDIO_PRINTER_LOCK') or Path(current_app.instance_path) / 'studio-printer.lock')


@contextmanager
def printer_lock():
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def device():
    spec = current_app.config['PRINTER_PRINTER']
    if spec == 'simulation':
        return 'simulation'
    if spec == '?':
        for number in range(11):
            path = f'/dev/usb/lp{number}'
            if os.path.exists(path):
                return 'file://' + path
        return None
    return spec


def status_from_raw(raw, model, expected_size=None):
    errors = raw.get('errors') or []
    reported_model = raw.get('model') or 'Unknown'
    media_type = raw.get('media_type')
    media_width = raw.get('media_width')
    media_length = raw.get('media_length')
    dimensions = f'{media_width} × {media_length}' if media_length else str(media_width)
    media = f'{dimensions} mm {media_type}' if media_width and media_type else None
    color = raw.get('media_color', 'unknown')
    if color in ('black', 'black-red') and media:
        media += ' (black/red)' if color == 'black-red' else ' (black only)'
    if errors:
        return {'state': 'error', 'model': reported_model, 'message': ', '.join(map(str, errors)), 'media': media}
    if raw.get('phase_type') == 'Printing state':
        return {'state': 'busy', 'model': reported_model, 'message': 'Printer busy', 'media': media}
    if reported_model != model:
        return {'state': 'error', 'model': reported_model, 'message': 'Connected printer model does not match configuration', 'media': media}
    if media_type in (None, 'No media', 'Incompatible tape') or not media_width:
        return {'state': 'error', 'model': reported_model, 'message': 'No compatible label roll loaded', 'media': media}
    if raw.get('status_type') != 'Reply to status request' or raw.get('status_code') != 0 or raw.get('phase_type') != 'Waiting to receive':
        return {'state': 'unknown', 'model': reported_model, 'message': 'Printer readiness is unknown', 'media': media}
    if expected_size:
        label = next(item for item in sizes() if item.identifier == expected_size)
        if color == 'black-red' and expected_size != '62red':
            return {'state': 'error', 'model': reported_model, 'message': 'Black/red tape is loaded. Choose 62 mm black/red for this label.', 'media': media}
        if color == 'black' and expected_size == '62red':
            return {'state': 'error', 'model': reported_model, 'message': 'Black-only tape is loaded. Choose a black-only label roll.', 'media': media}
        expected_width, expected_length = label.tape_size
        if (media_width, media_length) != (expected_width, expected_length):
            return {'state': 'error', 'model': reported_model, 'message': 'Loaded roll does not match label size', 'media': media}
    matching = [label.identifier for label in sizes() if tuple(label.tape_size) == (media_width, media_length)]
    if color == 'black-red':
        matching = [size for size in matching if size == '62red']
    elif color == 'black':
        matching = [size for size in matching if size != '62red']
    return {'state': 'ready', 'model': reported_model, 'message': 'Printer ready', 'media': media, 'matchingSizes': matching, 'mediaColor': color}


def status_locked(device, expected_size=None):
    model = current_app.config['PRINTER_MODEL']
    if device == 'simulation':
        return {'state': 'simulation', 'model': model, 'message': 'Test print to file', 'media': None}
    if not device or (device.startswith('file://') and not os.path.exists(device[7:])):
        return {'state': 'offline', 'model': model, 'message': 'Printer offline', 'media': None}
    if device.startswith('tcp://'):
        return {'state': 'unknown', 'model': model, 'message': 'Network printer status unavailable', 'media': None}
    try:
        raw = query_printer_status(device)
        return status_from_raw(raw, model, expected_size)
    except Exception:
        current_app.logger.exception('Printer status failed')
        return {'state': 'offline', 'model': model, 'message': 'Printer unavailable', 'media': None}


