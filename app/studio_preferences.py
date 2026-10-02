"""Persistent defaults and locally installed fonts for Label Studio."""
import hashlib
import json
import os
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from flask import current_app, request, send_file
from fontTools.ttLib import TTFont

from app.managed_fonts import inspect_faces, register_faces
import app as app_module
from app.studio_api import bp, body
from app.validation import InputError, integer, sizes, string
from app.label_store import write_json

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
    return [{'id': f'{family},{style}', 'name': f'{family} {style}', **app_module.FONTS.describe(f'{family},{style}')}
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
    value['font'] = app_module.FONTS.canonical_font(value['font'])
    if value['font'] not in {font['id'] for font in font_list()}:
        value['font'] = ','.join(app_module.FONTS.get_default_font())
    return value


@bp.route('/api/settings', methods=['PUT'])
def save_defaults():
    value = body()
    string(value.get('font'), 'font', 200)
    string(value.get('sizeId'), 'label roll', 32)
    if value.get('font') not in {font['id'] for font in font_list()}:
        raise InputError('Choose an installed font.')
    if value.get('sizeId') not in {size.identifier for size in sizes()}:
        raise InputError('Choose a supported label roll.')
    if value.get('orientation') not in ('standard', 'rotated'):
        raise InputError('Choose a valid orientation.')
    clean = {key: value[key] for key in ('font', 'sizeId', 'orientation')}
    if not isinstance(value.get('autoDetectRoll', True), bool):
        raise InputError('Automatic roll detection must be on or off.')
    clean['autoDetectRoll'] = value.get('autoDetectRoll', True)
    clean['margin'] = integer(value.get('margin'), 'Margin', 0, 100)
    clean['fontSize'] = integer(value.get('fontSize'), 'Font size', 8, 200)
    directory = data_dir(current_app)
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / 'settings.json', {'version': 1, 'defaults': clean})
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


def _installed_result(destination):
    faces = json.loads((destination / 'faces.json').read_text())
    register_faces(app_module.FONTS, destination, faces)
    regular = min(faces, key=lambda face: (face['italic'], abs(face['weight'] - 400)))
    return {'font': f"{regular['family']},{regular['style']}", 'fonts': font_list()}


def _install_files(files, directory, *, family_name=None, extra=None):
    destination = font_dir(current_app) / directory
    faces = []
    try:
        for filename, data in files.items():
            faces.extend(inspect_faces(data, filename, family_name))
    except Exception as error:
        raise InputError('This font cannot be used. Choose a valid TTF or OTF font with printable outlines.') from error
    with _font_lock:
        destination.mkdir(parents=True, exist_ok=True)
        old_font = destination / 'font.ttf'
        if family_name and old_font.exists():
            with TTFont(old_font) as old:
                old_name = f"{old['name'].getDebugName(1)},{old['name'].getDebugName(2)}"
            regular = min(faces, key=lambda face: (face['italic'], abs(face['weight']-400)))
            new_name = f"{regular['family']},{regular['style']}"
            if old_name != new_name:
                write_json(destination / 'aliases.json', {old_name: new_name})
        # Data files precede the manifest; each original font stays unchanged.
        for filename, data in {**files, **(extra or {})}.items():
            fd, temporary = tempfile.mkstemp(dir=destination, prefix='.font-')
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                os.replace(temporary, destination / filename)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        write_json(destination / 'faces.json', faces)
        return _installed_result(destination)


@bp.route('/api/fonts/install', methods=['POST'])
def install_google_font():
    family_id = string(body().get('id'), 'font family', 150)
    family = next((f for f in catalog()['families'] if f['id'] == family_id), None)
    if family is None:
        raise InputError('Choose a font from the catalog.')
    directory = 'google-' + family_id.replace('/', '-')
    destination = font_dir(current_app) / directory
    if (destination / 'faces.json').exists():
        with _font_lock:
            return _installed_result(destination)
    names = [name for name in family['files'] if name.endswith('.ttf')]
    variable = [name for name in names if '[' in name]
    if variable:
        selected = variable
    else:
        selected = [name for name in names if any(name.endswith('-' + style + '.ttf') for style in ('Regular', 'Bold', 'Italic', 'BoldItalic'))]
        selected = selected or names[:1]
    extra = {name: _download(family_id + '/' + name) for name in family['files'] if name.endswith('.txt')}
    extra['source.json'] = json.dumps({'family': family['name'], 'revision': catalog()['revision'], 'files': selected, 'nativeVariations': True}).encode()
    files = {}
    for name in selected:
        data = _download(family_id + '/' + name)
        files[hashlib.sha256(data).hexdigest() + '.ttf'] = data
    return _install_files(files, directory, family_name=family['name'], extra=extra)


@bp.route('/api/fonts/file')
def font_file():
    name = request.args.get('font', '')
    try:
        path = app_module.FONTS.get_path(name)
    except (ValueError, LookupError):
        raise InputError('Choose an installed font.')
    return send_file(path, mimetype='font/ttf', conditional=True)


@bp.route('/api/fonts/upload', methods=['POST'])
def upload_font():
    request.max_content_length = FONT_LIMIT + 65536
    upload = request.files.get('font')
    if upload is None or not (upload.filename or '').lower().endswith(('.ttf', '.otf')):
        raise InputError('Choose a TTF or OTF font.')
    data = upload.read(FONT_LIMIT + 1)
    if not data or len(data) > FONT_LIMIT:
        raise InputError('Font must be no larger than 8 MB.')
    return _install_files({'font.ttf': data}, 'upload-' + hashlib.sha256(data).hexdigest())
