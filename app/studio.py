"""HTTP endpoints for Label Studio."""
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from flask import current_app, jsonify, make_response, send_from_directory
from app.studio_api import bp, body
from app.validation import InputError, integer, sizes, validate_draft
from app.label_store import directory, saved, record_path, write_json, seed_starter_labels, name_and_draft
from app.rendering import render
from app.printer_service import device, printer_lock, status_locked
from app.labeldesigner.printer import PrinterQueue
from app.labeldesigner.media_catalog import label_info
from app.utils import image_to_png_bytes

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
    selected_device = device()
    if selected_device != 'simulation':
        lock = printer_lock()
    else:
        @contextmanager
        def unlocked():
            yield True
        lock = unlocked()
    with lock as acquired:
        if not acquired:
            return jsonify(message='Printer busy'), 409
        if selected_device != 'simulation':
            state = status_locked(selected_device, draft['sizeId'])
            if state['state'] != 'ready':
                return jsonify(message=state['message']), 503
            if draft['sizeId'] == '62red' and state.get('mediaColor') != 'black-red' and data.get('confirmRedMedia') is not True:
                raise InputError('Confirm that 62 mm black/red tape is loaded before printing.')
        queue = PrinterQueue(current_app.config['PRINTER_MODEL'], selected_device, draft['sizeId'])
        try:
            for number in range(copies):
                queue.add_label_to_queue(render(draft, image_bytes), cut == 'each' or number == copies - 1, draft['highRes'])
            error = queue.process_queue()
        except Exception as error:
            current_app.logger.exception('Studio print failed')
            return jsonify(message=str(error)), 400
        if error:
            return jsonify(message=error), 502
        kind = 'simulated' if selected_device == 'simulation' else 'printed'
        message = 'Test image saved' if kind == 'simulated' else 'Printed'
        return {'kind': kind, 'copies': copies, 'message': message}


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
    paper = {(draft['sizeId'], draft['highRes']) for draft, _ in validated}
    if len(paper) != 1:
        raise InputError('All labels in a batch must use the same paper and resolution.')
    selected_device = device()
    with printer_lock() as acquired:
        if not acquired:
            return jsonify(message='Printer busy. No labels were sent.'), 409
        jobs = directory().parent / 'bulk-jobs'
        jobs.mkdir(exist_ok=True)
        record = jobs / (job_id + '.json')
        if record.exists():
            return jsonify(message='This batch was already submitted. Check the printed labels before starting another batch.'), 409
        size, high_res = next(iter(paper))
        if selected_device != 'simulation':
            state = status_locked(selected_device, size)
            if state['state'] != 'ready':
                return jsonify(message=state['message']), 503
            if size == '62red' and state.get('mediaColor') != 'black-red':
                raise InputError('Load detected black/red tape before bulk printing.')
        queue = PrinterQueue(current_app.config['PRINTER_MODEL'], selected_device, size)
        # Render the entire batch before the first label can be sent.
        total_pixels = 0
        for number, (draft, image_bytes) in enumerate(validated, 1):
            try:
                label = render(draft, image_bytes)
                rendered = label.generate(rotate=False)
                total_pixels += rendered.width * rendered.height
                if total_pixels > 64_000_000:
                    raise InputError('Batch images are too large. Select fewer labels.')
                label.generate = lambda rotate=False, image=rendered: image
                queue.add_label_to_queue(label, cut == "each" or number == len(validated), high_res)
            except Exception as error:
                raise InputError(f'Label {number}: {error}. No labels were sent.')
        try:
            queue.validate_queue()
        except Exception as error:
            raise InputError(f'Printer conversion failed: {error}. No labels were sent.')
        record.write_text(json.dumps({'state': 'submitted', 'count': len(entries)}))
        try:
            error = queue.process_queue()
            if error:
                raise RuntimeError(error)
        except Exception as error:
            return jsonify(message=f'Printing stopped: {error}. Some labels may have printed. Check the printer before starting another batch.'), 502
        record.write_text(json.dumps({'state': 'complete', 'count': len(entries)}))
        return {'kind': 'simulated' if selected_device == 'simulation' else 'printed', 'copies': len(entries), 'message': 'Batch complete'}


@bp.route('/api/bulk/image', methods=['POST'])
def bulk_image():
    from app.remote_images import fetch_image
    try:
        return fetch_image(body().get('url'))
    except Exception as error:
        raise InputError(f'Could not load image: {error}')
