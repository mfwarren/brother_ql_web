import copy
import io
import json
from pathlib import Path

import pytest
import app as app_module
from app import create_app
from app.studio_preferences import data_dir
from test_studio import client, draft, assert_png


def test_defaults_persist_and_do_not_change_saved_labels(client):
    original = draft(client)
    saved = client.post('/studio/api/labels', json={'name': 'Keep this layout', 'draft': original}).json
    settings = client.get('/studio/api/config').json['defaults']
    settings.update(autoDetectRoll=False, orientation='rotated', margin=15, fontSize=45, sizeId='29')
    assert client.put('/studio/api/settings', json=settings).json['defaults'] == settings
    assert client.get('/studio/api/config').json['defaults'] == settings
    assert client.get('/studio/api/labels').json['labels'] == [saved]
    with client.application.app_context():
        persisted = json.loads((data_dir(client.application) / 'settings.json').read_text())
    assert persisted['defaults'] == settings
    restarted = create_app()
    restarted.config.update(STUDIO_LABELS_DIR=client.application.config['STUDIO_LABELS_DIR'])
    assert restarted.test_client().get('/studio/api/config').json['defaults'] == settings


@pytest.mark.parametrize('field,value', [('font','missing'), ('font', []), ('sizeId', {}), ('sizeId','unknown'), ('orientation','upside down'), ('margin',101), ('margin',True), ('fontSize',0), ('autoDetectRoll', 'yes'), ('autoDetectRoll', 1)])
def test_reject_invalid_defaults_without_overwriting(client, field, value):
    original = client.get('/studio/api/config').json['defaults']
    assert client.put('/studio/api/settings', json={**original, field: value}).status_code == 400
    assert client.get('/studio/api/config').json['defaults'] == original


@pytest.fixture
def isolated_fonts(monkeypatch):
    fonts = copy.deepcopy(app_module.FONTS)
    monkeypatch.setattr(app_module, 'FONTS', fonts)
    return fonts


def test_upload_font_renders_and_survives_restart(client, isolated_fonts):
    path = isolated_fonts.get_path(','.join(isolated_fonts.get_default_font()))
    result = client.post('/studio/api/fonts/upload', data={'font': (io.BytesIO(Path(path).read_bytes()), '../test.ttf')})
    assert result.status_code == 200
    label = draft(client)
    label['font'] = result.json['font']
    assert_png(client.post('/studio/api/preview', json=label))
    with client.application.app_context():
        root = data_dir(client.application)
    assert len(list((root / 'fonts').glob('upload-*/font.ttf'))) == 1
    from config import Config as Base
    class RestartConfig(Base):
        STUDIO_DATA_DIR = str(root)
    restarted = create_app(RestartConfig)
    font = app_module.FONTS.get_path(result.json['font'])
    assert str(root) in font
    assert result.json['font'] in {f['id'] for f in restarted.test_client().get('/studio/api/config').json['fonts']}


def test_bad_font_and_unknown_download_rejected(client):
    assert client.post('/studio/api/fonts/upload', data={'font': (io.BytesIO(b'bad font'), 'test.ttf')}).status_code == 400
    assert client.post('/studio/api/fonts/install', json={'id':'../../etc/passwd'}).status_code == 400


def test_google_catalog_and_install_keeps_license(client, isolated_fonts, monkeypatch):
    from app import studio_preferences as prefs
    fonts = client.get('/studio/api/fonts/catalog').json['families']
    assert len(fonts) > 1500
    roboto = next(font for font in fonts if font['name'] == 'Roboto')
    source = Path(isolated_fonts.get_path(','.join(isolated_fonts.get_default_font()))).read_bytes()
    monkeypatch.setattr(prefs, '_download', lambda path: source if path.endswith('.ttf') else b'Test license')
    result = client.post('/studio/api/fonts/install', json={'id':roboto['id']})
    assert result.status_code == 200
    with client.application.app_context():
        folder = prefs.font_dir(client.application) / ('google-' + roboto['id'].replace('/', '-'))
    assert (folder / 'OFL.txt').read_text() == 'Test license'
    assert (folder / 'source.json').exists()
    assert next(f for f in client.get('/studio/api/fonts/catalog').json['families'] if f['id'] == roboto['id'])['installed']


def test_detected_roll_matches_dimensions(client):
    from app.printer_service import status_from_raw
    raw = {'model':'QL-800', 'media_type':'Continuous length tape', 'media_width':62, 'media_length':0,
           'status_type':'Reply to status request', 'status_code':0, 'phase_type':'Waiting to receive'}
    with client.application.app_context():
        assert set(status_from_raw(raw, 'QL-800')['matchingSizes']) == {'62', '62red'}


def test_die_cut_roll_includes_length_and_has_one_match(client):
    from app.labeldesigner.usb_transport import decode_status
    from app.printer_service import status_from_raw
    raw = decode_status(bytes.fromhex('802042343830000000001d0b00000100005a0000000000000001000000000000'))
    with client.application.app_context():
        status = status_from_raw(raw, 'QL-800')
        assert status['media'] == '29 × 90 mm Die-cut labels (black only)'
        assert status['matchingSizes'] == ['29x90']
        assert status_from_raw(raw, 'QL-800', '29')['state'] == 'error'
        assert status_from_raw(raw, 'QL-800', '29x90')['state'] == 'ready'


def test_existing_settings_enable_detection_without_changing_fallback(client):
    settings = client.get('/studio/api/config').json['defaults']
    settings.pop('autoDetectRoll')
    with client.application.app_context():
        root = data_dir(client.application)
        root.mkdir(parents=True, exist_ok=True)
        (root / 'settings.json').write_text(json.dumps({'version': 1, 'defaults': settings}))
    loaded = client.get('/studio/api/config').json['defaults']
    assert loaded == {**settings, 'autoDetectRoll': True}



def test_catalog_keeps_regional_codes_on_one_geometry(client):
    from app.labeldesigner.media_catalog import CATALOG
    from brother_ql.labels import ALL_LABELS
    assert set(CATALOG) <= {label.identifier for label in ALL_LABELS}
    codes = [code for row in CATALOG.values() for code in row['codes']]
    assert len(codes) == len(set(codes))
    sizes = {size['id']: size for size in client.get('/studio/api/config').json['sizes']}
    assert sizes['29x90']['codes'] == ['DK-1201', 'DK-11201']
    assert sizes['62red']['codes'] == ['DK-2251', 'DK-22251']
    assert 'DK-2212' in sizes['62']['codes']
    assert not any(identifier.startswith('pt') for identifier in sizes)
    assert '102' not in sizes


def test_catalog_filters_printer_families_and_color_capability():
    from app.labeldesigner.media_catalog import supported_labels
    assert '62red' not in {label.identifier for label in supported_labels('QL-700')}
    wide = {label.identifier for label in supported_labels('QL-1100')}
    assert {'102', '102x51', '102x152'} <= wide
    assert {label.identifier for label in supported_labels('PT-P750W')} == {'pt12', 'pt18', 'pt24', 'pt36'}


@pytest.mark.parametrize('identifier,width,length,media_type', [
    ('17x54', 17, 54, 'Die-cut labels'),
    ('17x87', 17, 87, 'Die-cut labels'),
    ('23x23', 23, 23, 'Die-cut labels'),
    ('39x90', 38, 90, 'Die-cut labels'),
    ('62x29', 62, 29, 'Die-cut labels'),
    ('60x86', 60, 87, 'Die-cut labels'),
    ('62x100', 62, 100, 'Die-cut labels'),
    ('d12', 12, 12, 'Die-cut labels'),
    ('d24', 24, 24, 'Die-cut labels'),
    ('d58', 58, 58, 'Die-cut labels'),
    ('18', 18, 0, 'Continuous length tape'),
    ('29', 29, 0, 'Continuous length tape'),
    ('38', 38, 0, 'Continuous length tape'),
    ('50', 50, 0, 'Continuous length tape'),
    ('54', 54, 0, 'Continuous length tape'),
])
def test_other_roll_status_dimensions_match_existing_geometry(client, identifier, width, length, media_type):
    from app.printer_service import status_from_raw
    raw = {'model':'QL-800', 'media_type':media_type, 'media_width':width, 'media_length':length,
           'media_color':'black', 'status_type':'Reply to status request', 'status_code':0,
           'phase_type':'Waiting to receive'}
    with client.application.app_context():
        assert status_from_raw(raw, 'QL-800')['matchingSizes'] == [identifier]
