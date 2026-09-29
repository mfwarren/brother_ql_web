"""Small JSON interface for the household label editor."""

import base64
import binascii
import fcntl
import io
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from brother_ql.labels import ALL_LABELS
from flask import Blueprint, current_app, jsonify, make_response, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.datastructures import FileStorage

import app as app_module
from app.labeldesigner.printer import PrinterQueue, query_printer_status
from app.utils import image_to_png_bytes

bp = Blueprint('studio', __name__)
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = 8 * 1024 * 1024


class InputError(ValueError):
    pass


@bp.errorhandler(InputError)
def bad_input(error):
    return jsonify(message=str(error)), 400


@bp.errorhandler(RequestEntityTooLarge)
def too_large(error):
    return jsonify(message='Request is too large.'), 413


def _body():
    request.max_content_length = MAX_REQUEST_BYTES
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise InputError('Expected a JSON object.')
    return data


def _string(value, name, max_length, *, allow_empty=False):
    if not isinstance(value, str) or len(value) > max_length or (not allow_empty and not value.strip()):
        raise InputError(f'Invalid {name}.')
    return value


def _int(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise InputError(f'{name} must be between {low} and {high}.')
    return value


def _bool(value, name):
    if type(value) is not bool:
        raise InputError(f'Invalid {name}.')
    return value


def _sizes():
    model = current_app.config['PRINTER_MODEL']
    return [label for label in ALL_LABELS if not label.restricted_to_models or model in label.restricted_to_models]


def _validate_draft(draft):
    if not isinstance(draft, dict):
        raise InputError('Expected a label draft.')
    size = _string(draft.get('sizeId'), 'label size', 32)
    sizes = {label.identifier for label in _sizes()}
    if size not in sizes:
        raise InputError('Unknown label size.')
    orientation = draft.get('orientation')
    if orientation not in ('standard', 'rotated'):
        raise InputError('Invalid orientation.')
    font = _string(draft.get('font'), 'font', 200)
    if font not in {f"{family},{style}" for family, styles in app_module.FONTS.fonts.items() for style in styles}:
        raise InputError('Unknown font.')
    size_px = _int(draft.get('fontSize'), 'Font size', 8, 200)
    align = draft.get('align')
    if align not in ('left', 'center', 'right'):
        raise InputError('Invalid alignment.')
    color = draft.get('color')
    if color not in ('black', 'red'):
        raise InputError('Invalid color.')
    margin = _int(draft.get('margin'), 'Margin', 0, 100)
    high_res = _bool(draft.get('highRes'), 'highRes')
    if (color == 'red' or (isinstance(draft.get('content'), dict) and draft['content'].get('mode') == 'red')) and size != '62red':
        raise InputError('Red requires 62red media.')
    if high_res and size == '62red':
        raise InputError('High resolution is unavailable for red media.')
    content = draft.get('content')
    if not isinstance(content, dict):
        raise InputError('Choose text, QR, or image content.')
    kind = content.get('kind')
    image_bytes = None
    if kind == 'text':
        _string(content.get('text'), 'text', 10000)
    elif kind == 'qr':
        _string(content.get('code'), 'QR code', 2000)
        _string(content.get('caption'), 'caption', 10000, allow_empty=True)
    elif kind == 'image':
        _string(content.get('caption'), 'caption', 10000, allow_empty=True)
        if content.get('mode') not in ('grayscale', 'bw', 'red'):
            raise InputError('Invalid image mode.')
        _bool(content.get('fit'), 'image fit')
        image = content.get('image')
        if not isinstance(image, dict):
            raise InputError('Choose an image.')
        name = _string(image.get('name'), 'image name', 255)
        mime = image.get('mime')
        suffixes = {'image/png': '.png', 'image/jpeg': '.jpg', 'application/pdf': '.pdf'}
        if mime not in suffixes:
            raise InputError('Unsupported image type.')
        encoded = _string(image.get('base64'), 'image data', 7_000_000)
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise InputError('Invalid image data.')
        if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
            raise InputError('Image must be no larger than 5 MiB.')
        if not name.lower().endswith(('.png',) if mime == 'image/png' else ('.jpg', '.jpeg') if mime == 'image/jpeg' else ('.pdf',)):
            raise InputError('Image filename must match its file type.')
        if mime == 'image/png' and not image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
            raise InputError('Invalid PNG image.')
        if mime == 'image/jpeg' and not image_bytes.startswith(b'\xff\xd8'):
            raise InputError('Invalid JPEG image.')
        if mime == 'application/pdf' and not image_bytes.startswith(b'%PDF-'):
            raise InputError('Invalid PDF image.')
    else:
        raise InputError('Invalid content type.')
    return draft, image_bytes


def _to_upstream(draft, image_bytes):
    content = draft['content']
    kind = content['kind']
    line_text = content['text'] if kind == 'text' else content.get('caption', '')
    lines = [{'text': text, 'font': draft['font'], 'size': str(draft['fontSize']),
              'align': draft['align'], 'color': draft['color'], 'line_spacing': '100'}
             for text in line_text.splitlines()]
    values = {'label_size': draft['sizeId'], 'orientation': draft['orientation'],
              'text': json.dumps(lines), 'print_type': {'text': 'text', 'qr': 'qrcode_text', 'image': 'image'}[kind],
              'margin_top': draft['margin'], 'margin_bottom': draft['margin'],
              'margin_left': draft['margin'], 'margin_right': draft['margin'],
              'high_res': int(draft['highRes']), 'print_color': draft['color'], 'border_thickness': 0}
    files = {}
    if kind == 'qr':
        values.update(barcode_type='QR', code_text=content['code'])
    if kind == 'image':
        values.update(image_mode={'grayscale': 'grayscale', 'bw': 'bw', 'red': 'red_and_black'}[content['mode']],
                      image_fit=int(content['fit']))
        image = content['image']
        files['image'] = FileStorage(stream=io.BytesIO(image_bytes), filename=image['name'], content_type=image['mime'])
    return values, files


def _render(draft, image_bytes):
    from app.labeldesigner.routes import create_label_from_request
    values, files = _to_upstream(draft, image_bytes)
    return create_label_from_request(values, files)


def _repo_dir():
    path = Path(current_app.config.get('STUDIO_LABELS_DIR') or Path(current_app.instance_path) / 'studio-labels')
    path.mkdir(parents=True, exist_ok=True)
    return path


def _saved(record):
    return {key: record[key] for key in ('id', 'name', 'updatedAt', 'draft')}


def _record_path(label_id):
    try:
        valid = str(uuid.UUID(label_id))
    except (ValueError, TypeError):
        raise InputError('Invalid label ID.')
    return _repo_dir() / (valid + '.json')


def _write_record(path, record):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.studio-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(record, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _lock_path():
    return Path(current_app.config.get('STUDIO_PRINTER_LOCK') or Path(current_app.instance_path) / 'studio-printer.lock')


@contextmanager
def _printer_lock():
    path = _lock_path()
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


def _device():
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


def _status_from_raw(raw, model, expected_size=None):
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
        label = next(item for item in _sizes() if item.identifier == expected_size)
        if color == 'black-red' and expected_size != '62red':
            return {'state': 'error', 'model': reported_model, 'message': 'Black/red tape is loaded. Choose 62 mm black/red for this label.', 'media': media}
        if color == 'black' and expected_size == '62red':
            return {'state': 'error', 'model': reported_model, 'message': 'Black-only tape is loaded. Choose a black-only label roll.', 'media': media}
        expected_width, expected_length = label.tape_size
        if (media_width, media_length) != (expected_width, expected_length):
            return {'state': 'error', 'model': reported_model, 'message': 'Loaded roll does not match label size', 'media': media}
    matching = [label.identifier for label in _sizes() if tuple(label.tape_size) == (media_width, media_length)]
    if color == 'black-red':
        matching = [size for size in matching if size == '62red']
    elif color == 'black':
        matching = [size for size in matching if size != '62red']
    return {'state': 'ready', 'model': reported_model, 'message': 'Printer ready', 'media': media, 'matchingSizes': matching, 'mediaColor': color}


def _status_locked(device, expected_size=None):
    model = current_app.config['PRINTER_MODEL']
    if device == 'simulation':
        return {'state': 'simulation', 'model': model, 'message': 'Test print to file', 'media': None}
    if not device or (device.startswith('file://') and not os.path.exists(device[7:])):
        return {'state': 'offline', 'model': model, 'message': 'Printer offline', 'media': None}
    if device.startswith('tcp://'):
        return {'state': 'unknown', 'model': model, 'message': 'Network printer status unavailable', 'media': None}
    try:
        raw = query_printer_status(device)
        return _status_from_raw(raw, model, expected_size)
    except Exception:
        current_app.logger.exception('Printer status failed')
        return {'state': 'offline', 'model': model, 'message': 'Printer unavailable', 'media': None}


@bp.route('/')
def index():
    return send_from_directory(Path(current_app.static_folder) / 'studio', 'index.html')


@bp.route('/assets/<path:asset>')
def assets(asset):
    return send_from_directory(Path(current_app.static_folder) / 'studio' / 'assets', asset)


@bp.route('/api/config')
def config():
    from app.studio_preferences import defaults, font_list
    preferences = defaults()
    return {'model': current_app.config['PRINTER_MODEL'], 'fonts': font_list(),
            'sizes': [{'id': label.identifier, 'name': label.name} for label in _sizes()],
            'defaultFont': preferences['font'], 'defaultSize': preferences['sizeId'],
            'defaults': preferences,
            'mode': 'simulation' if _device() == 'simulation' else 'physical'}


@bp.route('/api/status')
def status():
    device = _device()
    if device == 'simulation':
        return _status_locked(device)
    with _printer_lock() as acquired:
        if not acquired:
            return {'state': 'busy', 'model': current_app.config['PRINTER_MODEL'], 'message': 'Printer busy', 'media': None}
        return _status_locked(device)


@bp.route('/api/preview', methods=['POST'])
def preview():
    draft, image_bytes = _validate_draft(_body())
    try:
        png = image_to_png_bytes(_render(draft, image_bytes).generate(rotate=True))
    except Exception as error:
        current_app.logger.exception('Studio preview failed')
        raise InputError(str(error))
    response = make_response(png)
    response.headers['Content-Type'] = 'image/png'
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/api/print', methods=['POST'])
def print_label():
    data = _body()
    draft, image_bytes = _validate_draft(data.get('draft'))
    copies = _int(data.get('copies'), 'Copies', 1, 100)
    cut = data.get('cut')
    if cut not in ('each', 'end'):
        raise InputError('Invalid cut option.')
    device = _device()
    if device != 'simulation':
        lock = _printer_lock()
    else:
        @contextmanager
        def unlocked():
            yield True
        lock = unlocked()
    with lock as acquired:
        if not acquired:
            return jsonify(message='Printer busy'), 409
        if device != 'simulation':
            state = _status_locked(device, draft['sizeId'])
            if state['state'] != 'ready':
                return jsonify(message=state['message']), 503
            if draft['sizeId'] == '62red' and state.get('mediaColor') != 'black-red' and data.get('confirmRedMedia') is not True:
                raise InputError('Confirm that 62 mm black/red tape is loaded before printing.')
        queue = PrinterQueue(current_app.config['PRINTER_MODEL'], device, draft['sizeId'])
        try:
            for number in range(copies):
                queue.add_label_to_queue(_render(draft, image_bytes), cut == 'each' or number == copies - 1, draft['highRes'])
            error = queue.process_queue()
        except Exception as error:
            current_app.logger.exception('Studio print failed')
            return jsonify(message=str(error)), 400
        if error:
            return jsonify(message=error), 502
        kind = 'simulated' if device == 'simulation' else 'printed'
        message = 'Test image saved' if kind == 'simulated' else 'Printed'
        return {'kind': kind, 'copies': copies, 'message': message}


def seed_starter_labels(*, add_to_existing=False, slugs=None):
    from app.studio_samples import starter_labels

    directory = _repo_dir()
    marker = directory / '.starter-labels-v1'
    with (directory / '.starter-labels.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if marker.exists() and not add_to_existing:
            return
        fonts = {f'{family},{style}' for family, styles in app_module.FONTS.fonts.items() for style in styles}
        default = ','.join(app_module.FONTS.get_default_font())
        samples = starter_labels(fonts, default)
        if slugs is not None:
            samples = [sample for sample in samples if sample[0] in slugs]
        records = []
        for slug, name, draft in samples:
            label_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'https://github.com/mfwarren/brother_ql_web/starter/' + slug))
            records.append({'version': 1, 'id': label_id, 'name': name,
                            'updatedAt': '2026-01-01T00:00:00+00:00', 'draft': draft})
        sample_files = {record['id'] + '.json' for record in records}
        existing = {path.name for path in directory.glob('*.json')}
        if add_to_existing or existing <= sample_files:
            for record in records:
                path = directory / (record['id'] + '.json')
                if not path.exists():
                    _name_and_draft(record)
                    _write_record(path, record)
        _write_record(marker, {'version': 1})


@bp.route('/api/labels')
def list_labels():
    if current_app.config.get('STUDIO_SEED_SAMPLES', True):
        seed_starter_labels()
    labels = []
    for path in sorted(_repo_dir().glob('*.json')):
        try:
            with path.open(encoding='utf-8') as source:
                labels.append(_saved(json.load(source)))
        except (OSError, ValueError, KeyError):
            current_app.logger.warning('Skipping damaged studio label %s', path)
    labels.sort(key=lambda item: item['updatedAt'], reverse=True)
    return {'labels': labels}


def _name_and_draft(data):
    name = _string(data.get('name'), 'name', 100).strip()
    draft, image_bytes = _validate_draft(data.get('draft'))
    try:
        _render(draft, image_bytes).generate(rotate=True)
    except Exception as error:
        raise InputError(str(error))
    return name, draft


@bp.route('/api/labels', methods=['POST'])
def save_label():
    name, draft = _name_and_draft(_body())
    label_id = str(uuid.uuid4())
    record = {'version': 1, 'id': label_id, 'name': name,
              'updatedAt': datetime.now(timezone.utc).isoformat(), 'draft': draft}
    _write_record(_record_path(label_id), record)
    return _saved(record), 201


@bp.route('/api/labels/<label_id>')
def load_label(label_id):
    path = _record_path(label_id)
    if not path.exists():
        return jsonify(message='Label not found'), 404
    with path.open(encoding='utf-8') as source:
        return _saved(json.load(source))


@bp.route('/api/labels/<label_id>', methods=['PUT'])
def update_label(label_id):
    path = _record_path(label_id)
    if not path.exists():
        return jsonify(message='Label not found'), 404
    name, draft = _name_and_draft(_body())
    record = {'version': 1, 'id': label_id, 'name': name,
              'updatedAt': datetime.now(timezone.utc).isoformat(), 'draft': draft}
    _write_record(path, record)
    return _saved(record)


@bp.route('/api/labels/<label_id>', methods=['DELETE'])
def delete_label(label_id):
    path = _record_path(label_id)
    try:
        path.unlink()
    except FileNotFoundError:
        return jsonify(message='Label not found'), 404
    return {'success': True}
