from concurrent.futures import ThreadPoolExecutor

from test_studio import client, draft, assert_png
from app.studio import seed_starter_labels


def test_first_install_samples_render_and_print_in_simulator(client):
    client.application.config['STUDIO_SEED_SAMPLES'] = True
    labels = client.get('/studio/api/labels').json['labels']
    assert len(labels) == 9
    assert {label['draft']['content']['kind'] for label in labels} == {'text', 'qr', 'barcode', 'image'}
    for label in labels:
        assert label['draft']['sizeId'] == ('62red' if label['name'] == 'Fragile · Black/red tape' else '62')
        assert_png(client.post('/studio/api/preview', json=label['draft']))
        result = client.post('/studio/api/print', json={'draft': label['draft'], 'copies': 1, 'cut': 'each'})
        assert result.status_code == 200
        assert result.json['kind'] == 'simulated'
    assert [label['id'] for label in labels] == [label['id'] for label in client.get('/studio/api/labels').json['labels']]


def test_samples_do_not_return_after_deletion_or_overwrite_edits(client):
    client.application.config['STUDIO_SEED_SAMPLES'] = True
    labels = client.get('/studio/api/labels').json['labels']
    changed = labels[0]
    client.put('/studio/api/labels/' + changed['id'], json={'name': 'My custom label', 'draft': changed['draft']})
    for label in labels[1:]:
        client.delete('/studio/api/labels/' + label['id'])
    remaining = client.get('/studio/api/labels').json['labels']
    assert len(remaining) == 1
    assert remaining[0]['name'] == 'My custom label'
    client.delete('/studio/api/labels/' + changed['id'])
    assert client.get('/studio/api/labels').json['labels'] == []


def test_existing_library_is_left_alone_unless_explicitly_seeded(client):
    created = client.post('/studio/api/labels', json={'name': 'Existing', 'draft': draft(client)}).json
    client.application.config['STUDIO_SEED_SAMPLES'] = True
    assert client.get('/studio/api/labels').json['labels'] == [created]
    with client.application.app_context():
        seed_starter_labels(add_to_existing=True)
        seed_starter_labels(add_to_existing=True)
    labels = client.get('/studio/api/labels').json['labels']
    assert len(labels) == 10
    assert created in labels


def test_concurrent_initial_visits_create_one_set(client):
    client.application.config['STUDIO_SEED_SAMPLES'] = True
    def visit(_):
        with client.application.test_client() as session:
            return session.get('/studio/api/labels').json['labels']
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(visit, range(4)))
    assert all(len(labels) == 9 for labels in results)
    assert all(labels == results[0] for labels in results)


def test_adding_new_samples_does_not_restore_deleted_old_samples(client):
    client.application.config['STUDIO_SEED_SAMPLES'] = True
    labels = client.get('/studio/api/labels').json['labels']
    storage = next(label for label in labels if label['name'] == 'Storage bin')
    address = next(label for label in labels if label['name'] == 'Mailing address')
    client.delete('/studio/api/labels/' + storage['id'])
    client.delete('/studio/api/labels/' + address['id'])
    with client.application.app_context():
        seed_starter_labels(add_to_existing=True, slugs={'mailing-address'})
    names = {label['name'] for label in client.get('/studio/api/labels').json['labels']}
    assert 'Mailing address' in names
    assert 'Storage bin' not in names


def test_fragile_preserves_media_and_compact_landscape_layout(client):
    import io
    from PIL import Image
    client.application.config['STUDIO_SEED_SAMPLES'] = True
    labels = client.get('/studio/api/labels').json['labels']
    fragile = next(label for label in labels if label['name'] == 'Fragile · Black/red tape')
    client.put('/studio/api/labels/' + fragile['id'], json={'name': fragile['name'], 'draft': fragile['draft']})
    loaded = next(label for label in client.get('/studio/api/labels').json['labels'] if label['id'] == fragile['id'])
    assert loaded['draft'] == fragile['draft']
    assert loaded['draft']['sizeId'] == '62red'
    assert loaded['draft']['orientation'] == 'standard'
    assert loaded['draft']['highRes'] is False
    preview = client.post('/studio/api/preview', json=loaded['draft'])
    image = Image.open(io.BytesIO(preview.data)).convert('RGB')
    assert image.width > image.height
    assert image.height < 600  # Less than 51 mm of feed at 300 dpi, not a 500 mm strip.
    assert any(r > 150 and g < 80 and b < 80 for r, g, b in image.get_flattened_data())


def test_red_media_requires_confirmation_before_printing(client, monkeypatch):
    from app import studio
    client.application.config['STUDIO_SEED_SAMPLES'] = True
    fragile = next(label for label in client.get('/studio/api/labels').json['labels'] if label['draft']['sizeId'] == '62red')
    monkeypatch.setattr(studio, '_device', lambda: 'file:///dev/test-printer')
    calls = []
    def status(device, size):
        calls.append(size)
        return {'state': 'ready', 'message': 'Test ready'}
    monkeypatch.setattr(studio, '_status_locked', status)
    body = {'draft': fragile['draft'], 'copies': 1, 'cut': 'each'}
    assert client.post('/studio/api/print', json=body).status_code == 400
    assert calls == ['62red']
    monkeypatch.setattr(studio, '_status_locked', lambda device, size: {'state': 'offline', 'message': 'Offline'})
    assert client.post('/studio/api/print', json={**body, 'confirmRedMedia': True}).status_code == 503
    assert calls == ['62red']
