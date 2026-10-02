import copy
import io
import json

import pytest
from PIL import Image, ImageChops, ImageFont
from fontTools.ttLib import TTFont

import app as app_module
from app import create_app
from app.managed_fonts import inspect_faces
from app.rich_text import text_image
from app.studio_preferences import font_dir
from font_fixtures import variable_font
from test_studio import client, draft, assert_png
from test_studio_preferences import isolated_fonts


def install_test_family(client, monkeypatch, tmp_path):
    from app import studio_preferences as prefs
    regular=variable_font(tmp_path); italic=variable_font(tmp_path, italic=True)
    monkeypatch.setattr(prefs, '_download', lambda path: (italic if 'Italic' in path else regular) if path.endswith('.ttf') else b'Test license')
    result=client.post('/studio/api/fonts/install',json={'id':'ofl/roboto'})
    assert result.status_code == 200
    return result.json, regular, italic


def test_native_install_keeps_outlines_and_regular_weight(client, isolated_fonts, monkeypatch, tmp_path):
    result, regular, italic=install_test_family(client, monkeypatch, tmp_path)
    assert result['font'] == 'Roboto,Regular'
    assert {'Roboto,Regular','Roboto,Bold','Roboto,Italic','Roboto,Bold Italic'} <= {face['id'] for face in result['fonts']}
    assert app_module.FONTS.get_variations('Roboto,Regular') == (400,)
    assert app_module.FONTS.get_variations('Roboto,Bold') == (700,)
    path=app_module.FONTS.get_path('Roboto,Regular')
    assert open(path,'rb').read() == regular
    assert 'fvar' in TTFont(path)
    with client.application.app_context():
        directory=font_dir(client.application)
    from config import Config
    class RestartConfig(Config):
        STUDIO_DATA_DIR=str(directory.parent)
    restarted=create_app(RestartConfig)
    assert app_module.FONTS.get_variations('Roboto,Bold Italic') == (700,)
    monkeypatch.setattr('app.studio_preferences._download', lambda *args: pytest.fail('Downloaded an installed font'))
    assert restarted.test_client().post('/studio/api/fonts/install',json={'id':'ofl/roboto'}).json['font']=='Roboto,Regular'


def rich_draft(client):
    value=draft(client)
    value.update(sizeId='62',fontSize=40,margin=12)
    value['content']={'kind':'text','text':'A A\nA','paragraphs':[
        {'runs':[{'text':'A ', 'size':80,'bold':True},{'text':'A','italic':True}]},
        {'runs':[{'text':'A','size':24}]},
    ]}
    return value


def test_rich_text_saves_reopens_previews_and_rasterizes(client, isolated_fonts, monkeypatch, tmp_path):
    result, _, _=install_test_family(client, monkeypatch, tmp_path)
    value=rich_draft(client); value['font']=result['font']
    preview=client.post('/studio/api/preview',json=value); assert_png(preview)
    saved=client.post('/studio/api/labels',json={'name':'Mixed text','draft':value}).json
    assert client.get('/studio/api/labels').json['labels'][0]['draft']==value
    assert client.post('/studio/api/preview',json=saved['draft']).data==preview.data
    assert client.post('/studio/api/print',json={'draft':value,'copies':1,'cut':'each'}).status_code==200
    unstyled=copy.deepcopy(value)
    for paragraph in unstyled['content']['paragraphs']:
        for run in paragraph['runs']:
            run.pop('bold',None);run.pop('italic',None);run['size']=40
    changed=client.post('/studio/api/preview',json=unstyled)
    assert changed.data != preview.data


def test_variable_weight_changes_ink_not_just_names(tmp_path):
    data=variable_font(tmp_path)
    masks=[]
    for weight in [100,400,700]:
        font=ImageFont.truetype(io.BytesIO(data),80);font.set_variation_by_axes([weight])
        masks.append(sum(bytes(font.getmask('A'))))
    assert masks[0] < masks[1] < masks[2]
    assert inspect_faces(data,'font.ttf')[3]['style']=='Regular'


@pytest.mark.parametrize('bad', [
    [{'runs':[{'text':'Different'}]}],
    [{'runs':[{'text':'A A\nA'}]}],
    [{'runs':[{'text':'A A','size':999}]},{'runs':[{'text':'A'}]}],
    [{'runs':[{'text':'A A','bold':'yes'}]},{'runs':[{'text':'A'}]}],
])
def test_malformed_rich_text_is_rejected(client, bad):
    value=rich_draft(client);value['content']['paragraphs']=bad
    assert client.post('/studio/api/preview',json=value).status_code==400


def test_rich_text_overflow_is_reported_before_clipping(client):
    value=rich_draft(client); value['content']={'kind':'text','text':'A\n'*10+'A','paragraphs':[{'runs':[{'text':'A','size':200}]}]*11}
    value.update(sizeId='29x90')
    result=client.post('/studio/api/preview',json=value)
    assert result.status_code==400
    assert 'height' in result.json['message']


def test_font_file_rejects_arbitrary_paths(client):
    assert client.get('/studio/api/fonts/file?font=/etc/passwd').status_code==400


def test_legacy_light_family_names_resolve_to_regular(client, isolated_fonts, monkeypatch, tmp_path):
    from pathlib import Path
    from app.studio_preferences import data_dir
    with client.application.app_context():
        root=data_dir(client.application)
        folder=font_dir(client.application)/'google-ofl-roboto'
    folder.mkdir(parents=True)
    legacy=TTFont(io.BytesIO(variable_font(tmp_path)))
    for name_id, value in [(1,'Roboto Thin'),(2,'Regular')]:
        for record in legacy['name'].names:
            if record.nameID == name_id:
                record.string = value.encode(record.getEncoding())
    legacy.save(folder/'font.ttf')
    settings=client.get('/studio/api/config').json['defaults']; settings['font']='Roboto Thin,Regular'
    (root/'settings.json').write_text(json.dumps({'version':1,'defaults':settings}))
    install_test_family(client,monkeypatch,tmp_path)
    assert client.get('/studio/api/config').json['defaults']['font']=='Roboto,Regular'
    assert app_module.FONTS.get_path('Roboto Thin,Regular')==app_module.FONTS.get_path('Roboto,Regular')
    assert (folder/'font.ttf').exists()


def test_words_wrap_without_discarding_formatting(client):
    value=rich_draft(client)
    value['content']={'kind':'text','text':'A word '*30,'paragraphs':[{'runs':[{'text':'A word '*30,'size':40}]}]}
    result=client.post('/studio/api/preview',json=value)
    assert_png(result)
    image=Image.open(io.BytesIO(result.data))
    assert image.height > 100


def test_inline_fonts_survive_save_and_change_raster(client, isolated_fonts, monkeypatch, tmp_path):
    result, _, _ = install_test_family(client, monkeypatch, tmp_path)
    value = rich_draft(client)
    for paragraph in value['content']['paragraphs']:
        for run in paragraph['runs']:
            run.pop('italic', None)
    original = client.post('/studio/api/preview', json=value)
    assert_png(original)
    value['content']['paragraphs'][0]['runs'][0]['font'] = result['font']
    changed = client.post('/studio/api/preview', json=value)
    assert_png(changed)
    assert original.data != changed.data
    saved = client.post('/studio/api/labels', json={'name':'Mixed fonts','draft':value}).json
    assert saved['draft']['content'] == value['content']
    assert client.post('/studio/api/preview', json=saved['draft']).data == changed.data
    value['content']['paragraphs'][0]['runs'][0]['font'] = '/etc/passwd'
    assert client.post('/studio/api/preview', json=value).status_code == 400


def test_underline_is_saved_and_rendered(client):
    value = rich_draft(client)
    for paragraph in value['content']['paragraphs']:
        for run in paragraph['runs']:
            run.pop('italic', None)
    plain = client.post('/studio/api/preview', json=value)
    assert_png(plain)
    value['content']['paragraphs'][0]['runs'][0]['underline'] = True
    marked = client.post('/studio/api/preview', json=value)
    assert_png(marked)
    assert marked.data != plain.data
    saved = client.post('/studio/api/labels', json={'name':'Underlined','draft':value}).json
    assert client.post('/studio/api/preview', json=saved['draft']).data == marked.data
    assert client.post('/studio/api/print', json={'draft':value,'copies':1,'cut':'each'}).status_code == 200
    value['content']['paragraphs'][0]['runs'][0]['underline'] = 'yes'
    assert client.post('/studio/api/preview', json=value).status_code == 400


@pytest.mark.parametrize('orientation', ['standard', 'rotated'])
def test_fixed_text_vertical_alignment_preserves_paper_size(client, orientation):
    from PIL import ImageChops
    from app.rich_text import render_label
    value = rich_draft(client)
    value.update(sizeId='29x90', orientation=orientation, fontSize=32)
    value['content'] = {'kind':'text', 'text':'A', 'paragraphs':[{'runs':[{'text':'A'}]}]}
    bounds = []
    sizes = []
    for alignment in ['top', 'center', 'bottom']:
        value['verticalAlign'] = alignment
        image = render_label(value).generate(rotate=False).convert('RGB')
        box = ImageChops.difference(image, Image.new('RGB', image.size, 'white')).getbbox()
        bounds.append(box)
        sizes.append(image.size)
    assert sizes[0] == sizes[1] == sizes[2]
    assert bounds[0][1] < bounds[1][1] < bounds[2][1]
    assert abs((bounds[1][1] + bounds[1][3]) / 2 - sizes[1][1] / 2) <= 1
    saved = client.post('/studio/api/labels', json={'name':'Aligned','draft':value}).json
    assert saved['draft']['verticalAlign'] == 'bottom'
    value['verticalAlign'] = 'outside'
    assert client.post('/studio/api/preview', json=value).status_code == 400


def test_plain_initial_top_matches_top_after_edit(client):
    value = rich_draft(client)
    value.update(sizeId='29x90', verticalAlign='top', fontSize=32)
    value['content'] = {'kind':'text','text':'Coffee beans'}
    initial = client.post('/studio/api/preview', json=value)
    assert_png(initial)
    value['content']['paragraphs'] = [{'runs':[{'text':'Coffee beans'}]}]
    edited = client.post('/studio/api/preview', json=value)
    assert initial.data == edited.data
    value['verticalAlign'] = 'center'
    assert client.post('/studio/api/preview', json=value).data != initial.data


def test_line_spacing_changes_distance_and_survives_save(client):
    value = rich_draft(client)
    value['content'] = {'kind': 'text', 'text': 'First line\nSecond line', 'paragraphs': [{'runs': [{'text': 'First line'}]}, {'runs': [{'text': 'Second line'}]}]}
    value['lineSpacing'] = 180
    value['margins'] = {'top': 10, 'right': 20, 'bottom': 30, 'left': 40}
    wide = client.post('/studio/api/preview', json=value)
    assert_png(wide)
    saved = client.post('/studio/api/labels', json={'name': 'Spaced', 'draft': value}).json
    assert saved['draft'] == value
    assert client.post('/studio/api/preview', json=saved['draft']).data == wide.data
    tight = client.post('/studio/api/preview', json={**value, 'lineSpacing': 100})
    assert Image.open(io.BytesIO(wide.data)).height > Image.open(io.BytesIO(tight.data)).height


@pytest.mark.parametrize('orientation', ['standard', 'rotated'])
def test_asymmetric_margins_bound_text_and_position_top(client, orientation):
    from app.rendering import render
    value = rich_draft(client)
    value.update(sizeId='29x90', fontSize=20, orientation=orientation, align='left', verticalAlign='top',
                 margins={'top': 17, 'right': 22, 'bottom': 31, 'left': 43})
    value['content'] = {'kind': 'text', 'text': 'Hello', 'paragraphs': [{'runs': [{'text': 'Hello'}]}]}
    with client.application.app_context():
        image = render(value, None).generate()
    bounds = ImageChops.difference(image, Image.new('RGB', image.size, 'white')).getbbox()
    assert bounds[1] == 17
    assert 43 <= bounds[0] <= 48
    assert bounds[2] <= image.width - 22
    assert bounds[3] <= image.height - 31


@pytest.mark.parametrize('patch', [ {'lineSpacing': 99}, {'lineSpacing': 301}, {'lineSpacing': '150'},
    {'margins': {'top': 10}}, {'margins': {'top': -1, 'right': 0, 'bottom': 0, 'left': 0}} ])
def test_invalid_spacing_and_margins_rejected(client, patch):
    value = rich_draft(client)
    value.update(patch)
    assert client.post('/studio/api/preview', json=value).status_code == 400


def test_old_editor_redirects_and_error_page_has_no_bootstrap(client):
    response = client.get('/labeldesigner/')
    assert response.status_code == 302
    assert response.location.endswith('/studio/')
    missing = client.get('/not-a-page')
    assert missing.status_code == 404
    assert b'bootstrap' not in missing.data.lower()
