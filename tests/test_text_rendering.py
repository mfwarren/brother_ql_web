import copy

import pytest

from app.text_rendering import TextLayout, normalize_text, render_text
from test_studio import client, draft


def test_old_text_normalizes_without_rewriting_saved_input(client):
    value = draft(client, {'kind': 'text', 'text': 'First\nSecond\n'})
    original = copy.deepcopy(value)
    normalized = normalize_text(value)
    assert normalized.layout is TextLayout.LEGACY_PLAIN
    assert normalized.draft['content']['paragraphs'] == [
        {'runs': [{'text': 'First'}]}, {'runs': [{'text': 'Second'}]}, {'runs': [{'text': ''}]}]
    assert value == original
    saved = client.post('/studio/api/labels', json={'name': 'Old label', 'draft': value}).json
    assert client.get('/studio/api/labels/' + saved['id']).json['draft'] == original


@pytest.mark.parametrize('orientation', ['standard', 'rotated'])
@pytest.mark.parametrize('size', ['62', '29x90'])
@pytest.mark.parametrize('alignment', ['top', 'center', 'bottom'])
def test_plain_and_formatted_text_share_layout(client, orientation, size, alignment):
    value = draft(client, {'kind': 'text', 'text': 'Coffee\nbeans'})
    value.update(fontSize=24, orientation=orientation, sizeId=size, verticalAlign=alignment,
                 lineSpacing=150, margins={'left': 30, 'right': 20, 'top': 15, 'bottom': 25})
    formatted = copy.deepcopy(value)
    formatted['content']['paragraphs'] = [{'runs': [{'text': 'Coffee'}]}, {'runs': [{'text': 'beans'}]}]
    assert normalize_text(value).layout is TextLayout.FLOW
    with client.application.app_context():
        plain = render_text(value).generate(rotate=True)
        rich = render_text(formatted).generate(rotate=True)
    assert plain.size == rich.size
    assert plain.tobytes() == rich.tobytes()
