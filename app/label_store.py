"""Atomic label storage and first-install sample seeding."""
import fcntl
import json
import os
import tempfile
import uuid
from pathlib import Path
from flask import current_app
import app as app_module
from app.validation import InputError, string, validate_draft
from app.rendering import render

def directory():
    path = Path(current_app.config.get('STUDIO_LABELS_DIR') or Path(current_app.instance_path) / 'studio-labels')
    path.mkdir(parents=True, exist_ok=True)
    return path


def saved(record):
    saved = {key: record[key] for key in ('id', 'name', 'updatedAt', 'draft')}
    saved['draft'] = {**record['draft'], 'font': app_module.FONTS.canonical_font(record['draft']['font'])}
    return saved


def record_path(label_id):
    try:
        valid = str(uuid.UUID(label_id))
    except (ValueError, TypeError):
        raise InputError('Invalid label ID.')
    return directory() / (valid + '.json')


def write_json(path, record):
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


def seed_starter_labels(*, add_to_existing=False, slugs=None):
    from app.studio_samples import starter_labels

    label_dir = directory()
    marker = label_dir / '.starter-labels-v1'
    with (label_dir / '.starter-labels.lock').open('a+b') as lock:
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
        existing = {path.name for path in label_dir.glob('*.json')}
        if add_to_existing or existing <= sample_files:
            for record in records:
                path = label_dir / (record['id'] + '.json')
                if not path.exists():
                    name_and_draft(record)
                    write_json(path, record)
        write_json(marker, {'version': 1})


def name_and_draft(data):
    name = string(data.get('name'), 'name', 100).strip()
    draft, image_bytes = validate_draft(data.get('draft'))
    try:
        render(draft, image_bytes).generate(rotate=True)
    except Exception as error:
        raise InputError(str(error))
    return name, draft


