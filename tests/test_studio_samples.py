from concurrent.futures import ThreadPoolExecutor

from test_studio import client, draft, assert_png
from app.studio import seed_starter_labels


def test_first_install_samples_render_and_print_in_simulator(client):
    client.application.config['STUDIO_SEED_SAMPLES'] = True
    labels = client.get('/studio/api/labels').json['labels']
    assert len(labels) == 8
    assert {label['draft']['content']['kind'] for label in labels} == {'text', 'qr', 'image'}
    for label in labels:
        assert label['draft']['sizeId'] == '62'
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
    assert len(labels) == 9
    assert created in labels


def test_concurrent_initial_visits_create_one_set(client):
    client.application.config['STUDIO_SEED_SAMPLES'] = True
    def visit(_):
        with client.application.test_client() as session:
            return session.get('/studio/api/labels').json['labels']
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(visit, range(4)))
    assert all(len(labels) == 8 for labels in results)
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
