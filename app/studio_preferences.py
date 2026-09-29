"""Persistent defaults and locally installed fonts for Label Studio."""
import hashlib
import io
import json
import os
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from flask import current_app, request
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import ImageFont

import app as app_module
from app.studio import bp, InputError, _body, _int, _sizes, _string, _write_record

FONT_LIMIT = 8 * 1024 * 1024
_font_lock = threading.Lock()


def data_dir(app):
    if app.config.get('STUDIO_DATA_DIR'):
        return Path(app.config['STUDIO_DATA_DIR'])
    if app.config.get('STUDIO_LABELS_DIR'):
        return Path(app.config['STUDIO_LABELS_DIR']).parent
    return Path(app.instance_path)


def font_dir(app):
    return data_dir(app) / 'fonts'


def font_list():
    # Publish a new mapping after each installation; readers keep a stable snapshot.
    fonts = app_module.FONTS.fonts
    return [{'id': f'{family},{style}', 'name': f'{family} {style}'}
            for family in sorted(fonts, key=str.casefold) for style in fonts[family]]


def defaults():
    config = current_app.config
    value = {'font': ','.join(app_module.FONTS.get_default_font()),
             'sizeId': config['LABEL_DEFAULT_SIZE'],
             'autoDetectRoll': True,
             'orientation': config['LABEL_DEFAULT_ORIENTATION'],
             'margin': config['LABEL_DEFAULT_MARGIN_TOP'],
             'fontSize': config['LABEL_DEFAULT_FONT_SIZE']}
    path = data_dir(current_app) / 'settings.json'
    if path.exists():
        value.update(json.loads(path.read_text())['defaults'])
    if value['font'] not in {font['id'] for font in font_list()}:
        value['font'] = ','.join(app_module.FONTS.get_default_font())
    return value


@bp.route('/api/settings', methods=['PUT'])
def save_defaults():
    value = _body()
    _string(value.get('font'), 'font', 200)
    _string(value.get('sizeId'), 'label roll', 32)
    if value.get('font') not in {font['id'] for font in font_list()}:
        raise InputError('Choose an installed font.')
    if value.get('sizeId') not in {size.identifier for size in _sizes()}:
        raise InputError('Choose a supported label roll.')
    if value.get('orientation') not in ('standard', 'rotated'):
        raise InputError('Choose a valid orientation.')
    clean = {key: value[key] for key in ('font', 'sizeId', 'orientation')}
    if not isinstance(value.get('autoDetectRoll', True), bool):
        raise InputError('Automatic roll detection must be on or off.')
    clean['autoDetectRoll'] = value.get('autoDetectRoll', True)
    clean['margin'] = _int(value.get('margin'), 'Margin', 0, 100)
    clean['fontSize'] = _int(value.get('fontSize'), 'Font size', 8, 200)
    directory = data_dir(current_app)
    directory.mkdir(parents=True, exist_ok=True)
    _write_record(directory / 'settings.json', {'version': 1, 'defaults': clean})
    return {'defaults': clean}


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent / 'data/google-fonts.json').read_text())


@bp.route('/api/fonts/catalog')
def google_catalog():
    directory = font_dir(current_app)
    return {'families': [{'id': f['id'], 'name': f['name'],
                          'installed': (directory / ('google-' + f['id'].replace('/', '-')) / 'source.json').exists()}
                         for f in catalog()['families']]}


def _download(path):
    url = 'https://raw.githubusercontent.com/google/fonts/' + catalog()['revision'] + '/' + quote(path, safe='/')
    try:
        with urlopen(url, timeout=25) as response:
            value = response.read(FONT_LIMIT + 1)
        if len(value) > FONT_LIMIT:
            raise InputError('This font exceeds the 8 MB download limit.')
        return value
    except (OSError, TimeoutError) as error:
        raise InputError('Font download failed. Check the Pi internet connection and try again.') from error


def _prepare_font(data, *, regular=False):
    try:
        font = TTFont(io.BytesIO(data))
        if font.flavor is not None:
            raise ValueError('Use TTF or OTF')
        if regular and 'fvar' in font:
            axes = {axis.axisTag: min(axis.maxValue, max(axis.minValue, 400 if axis.axisTag == 'wght' else axis.defaultValue))
                    for axis in font['fvar'].axes}
            font = instantiateVariableFont(font, axes, inplace=True)
        family = font['name'].getDebugName(1)
        style = font['name'].getDebugName(2)
        if not family or not style or ',' in family or len(f'{family},{style}') > 200:
            raise ValueError('Invalid font names')
        output = io.BytesIO()
        font.save(output)
        font.close()
        data = output.getvalue()
        ImageFont.truetype(io.BytesIO(data), 30).getmask('Label 123')
        return family, style, data
    except Exception as error:
        raise InputError('This font cannot be used. Choose a valid TTF or OTF font with printable outlines.') from error


def _publish_font(family, style, path):
    fonts = {name: dict(styles) for name, styles in app_module.FONTS.fonts.items()}
    fonts.setdefault(family, {})[style] = str(path)
    app_module.FONTS.fonts = fonts


def _install(data, directory, *, regular=False, extra=None):
    family, style, prepared = _prepare_font(data, regular=regular)
    parent = font_dir(current_app)
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / directory
    with _font_lock:
        if not destination.exists():
            with tempfile.TemporaryDirectory(dir=parent, prefix='.install-') as tmp:
                stage = Path(tmp)
                (stage / 'font.ttf').write_bytes(prepared)
                for name, contents in (extra or {}).items():
                    (stage / name).write_bytes(contents)
                os.rename(stage, destination)
        _publish_font(family, style, destination / 'font.ttf')
    return {'font': f'{family},{style}', 'fonts': font_list()}


@bp.route('/api/fonts/install', methods=['POST'])
def install_google_font():
    family_id = _string(_body().get('id'), 'font family', 150)
    family = next((f for f in catalog()['families'] if f['id'] == family_id), None)
    if family is None:
        raise InputError('Choose a font from the catalog.')
    files = [name for name in family['files'] if name.endswith('.ttf')]
    files.sort(key=lambda name: ('Italic' in name, 'Regular' not in name, '[' not in name, name))
    selected = files[0]
    extra = {name: _download(family_id + '/' + name) for name in family['files'] if name.endswith('.txt')}
    extra['source.json'] = json.dumps({'family': family['name'], 'revision': catalog()['revision'], 'file': selected}).encode()
    return _install(_download(family_id + '/' + selected), 'google-' + family_id.replace('/', '-'), regular=True, extra=extra)


@bp.route('/api/fonts/upload', methods=['POST'])
def upload_font():
    request.max_content_length = FONT_LIMIT + 65536
    upload = request.files.get('font')
    if upload is None or not (upload.filename or '').lower().endswith(('.ttf', '.otf')):
        raise InputError('Choose a TTF or OTF font.')
    data = upload.read(FONT_LIMIT + 1)
    if not data or len(data) > FONT_LIMIT:
        raise InputError('Font must be no larger than 8 MB.')
    return _install(data, 'upload-' + hashlib.sha256(data).hexdigest())
