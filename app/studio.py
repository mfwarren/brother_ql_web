"""HTTP endpoints for Label Studio."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from flask import current_app, jsonify, make_response, send_from_directory
from app.studio_api import bp, body
from app.validation import InputError, integer, sizes, validate_draft
from app.label_store import directory, saved, record_path, write_json, seed_starter_labels, name_and_draft
from app.rendering import render
from app.printer_service import device, printer_lock, status_locked
from app.printing import PrintFailure, print_drafts
from app.labeldesigner.media_catalog import label_info
from app.utils import image_to_png_bytes

@bp.errorhandler(PrintFailure)
def print_failed(error):
    return jsonify(message=str(error)), error.status


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
            'sizes': [label_info(label) for label in sizes()],
            'defaultFont': preferences['font'], 'defaultSize': preferences['sizeId'],
            'defaults': preferences,
            'mode': 'simulation' if device() == 'simulation' else 'physical'}


@bp.route('/api/status')
def status():
    selected_device = device()
    if selected_device == 'simulation':
        return status_locked(selected_device)
    with printer_lock() as acquired:
        if not acquired:
            return {'state': 'busy', 'model': current_app.config['PRINTER_MODEL'], 'message': 'Printer busy', 'media': None}
        return status_locked(selected_device)


@bp.route('/api/preview', methods=['POST'])
def preview():
    draft, image_bytes = validate_draft(body())
    try:
        png = image_to_png_bytes(render(draft, image_bytes).generate(rotate=True))
    except Exception as error:
        current_app.logger.exception('Studio preview failed')
        raise InputError(str(error))
    response = make_response(png)
    response.headers['Content-Type'] = 'image/png'
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/api/print', methods=['POST'])
def print_label():
    data = body()
    draft, image_bytes = validate_draft(data.get('draft'))
    copies = integer(data.get('copies'), 'Copies', 1, 100)
    cut = data.get('cut')
    if cut not in ('each', 'end'):
        raise InputError('Invalid cut option.')
    return print_drafts([(draft, image_bytes)] * copies, cut, confirm_red=data.get('confirmRedMedia') is True)


@bp.route('/api/labels')
def list_labels():
    if current_app.config.get('STUDIO_SEED_SAMPLES', True):
        seed_starter_labels()
    labels = []
    for path in sorted(directory().glob('*.json')):
        try:
            with path.open(encoding='utf-8') as source:
                labels.append(saved(json.load(source)))
        except (OSError, ValueError, KeyError):
            current_app.logger.warning('Skipping damaged studio label %s', path)
    labels.sort(key=lambda item: item['updatedAt'], reverse=True)
    return {'labels': labels}


@bp.route('/api/labels', methods=['POST'])
def save_label():
    name, draft = name_and_draft(body())
    label_id = str(uuid.uuid4())
    record = {'version': 1, 'id': label_id, 'name': name,
              'updatedAt': datetime.now(timezone.utc).isoformat(), 'draft': draft}
    write_json(record_path(label_id), record)
    return saved(record), 201


@bp.route('/api/labels/<label_id>')
def load_label(label_id):
    path = record_path(label_id)
    if not path.exists():
        return jsonify(message='Label not found'), 404
    with path.open(encoding='utf-8') as source:
        return saved(json.load(source))


@bp.route('/api/labels/<label_id>', methods=['PUT'])
def update_label(label_id):
    path = record_path(label_id)
    if not path.exists():
        return jsonify(message='Label not found'), 404
    name, draft = name_and_draft(body())
    record = {'version': 1, 'id': label_id, 'name': name,
              'updatedAt': datetime.now(timezone.utc).isoformat(), 'draft': draft}
    write_json(path, record)
    return saved(record)


@bp.route('/api/labels/<label_id>', methods=['DELETE'])
def delete_label(label_id):
    path = record_path(label_id)
    try:
        path.unlink()
    except FileNotFoundError:
        return jsonify(message='Label not found'), 404
    return {'success': True}


@bp.route('/api/bulk/prepare', methods=['POST'])
def prepare_bulk():
    from app.bulk_labels import prepare
    try:
        return prepare(body())
    except ValueError as error:
        raise InputError(str(error))


@bp.route('/api/bulk/print', methods=['POST'])
def print_bulk():
    data = body()
    cut = data.get('cut', 'each')
    if cut not in ('each', 'end'):
        raise InputError('Invalid cut option.')
    entries = data.get('drafts')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise InputError('Select 1–100 labels.')
    try:
        job_id = str(uuid.UUID(data.get('jobId', '')))
    except (ValueError, TypeError, AttributeError):
        raise InputError('Invalid batch ID.')
    validated = [validate_draft(entry) for entry in entries]
    return print_drafts(validated, cut, job_id=job_id)


@bp.route('/api/bulk/image', methods=['POST'])
def bulk_image():
    from app.remote_images import fetch_image
    try:
        return fetch_image(body().get('url'))
    except Exception as error:
        raise InputError(f'Could not load image: {error}')
