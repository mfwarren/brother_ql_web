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
    from app.studio import _status_from_raw
    raw = {'model':'QL-800', 'media_type':'Continuous length tape', 'media_width':62, 'media_length':0,
           'status_type':'Reply to status request', 'status_code':0, 'phase_type':'Waiting to receive'}
    with client.application.app_context():
        assert set(_status_from_raw(raw, 'QL-800')['matchingSizes']) == {'62', '62red'}


def test_die_cut_roll_includes_length_and_has_one_match(client):
    from app.labeldesigner.usb_transport import decode_status
    from app.studio import _status_from_raw
    raw = decode_status(bytes.fromhex('802042343830000000001d0b00000100005a0000000000000001000000000000'))
    with client.application.app_context():
        status = _status_from_raw(raw, 'QL-800')
        assert status['media'] == '29 × 90 mm Die-cut labels (black only)'
        assert status['matchingSizes'] == ['29x90']
        assert _status_from_raw(raw, 'QL-800', '29')['state'] == 'error'
        assert _status_from_raw(raw, 'QL-800', '29x90')['state'] == 'ready'


def test_existing_settings_enable_detection_without_changing_fallback(client):
    settings = client.get('/studio/api/config').json['defaults']
    settings.pop('autoDetectRoll')
    with client.application.app_context():
        root = data_dir(client.application)
        root.mkdir(parents=True, exist_ok=True)
        (root / 'settings.json').write_text(json.dumps({'version': 1, 'defaults': settings}))
    loaded = client.get('/studio/api/config').json['defaults']
    assert loaded == {**settings, 'autoDetectRoll': True}
