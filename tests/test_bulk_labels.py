import io
import uuid

import pytest
from PIL import Image

from app.bulk_labels import merge, parse_csv
from test_studio import client, draft


def test_csv_quotes_bom_multiline_and_zeroes():
    headers, rows = parse_csv('\ufeffProduct,SKU\r\n"Coffee, dark",0012\r\n"Two\nlines",0023\r\n\r\n')
    assert headers == ['Product', 'SKU']
    assert rows[0]['values'] == {'Product': 'Coffee, dark', 'SKU': '0012'}
    assert rows[1]['values']['Product'] == 'Two\nlines'
    assert rows[1]['line'] == 4


@pytest.mark.parametrize('text', ['', 'Name,Name\na,b', ',SKU\na,b', '@row\n1', 'Name\n', 'Name\n"unclosed'])
def test_invalid_csv_structure(text):
    with pytest.raises(ValueError):
        parse_csv(text)


def test_row_shape_errors_are_attached_to_source_line():
    _, rows = parse_csv('A,B\na,b\nbad\nc,d,e')
    assert rows[0]['error'] is None
    assert rows[1]['line'] == 3 and 'found 1' in rows[1]['error']
    assert rows[2]['line'] == 4 and 'found 3' in rows[2]['error']


def test_split_formatted_placeholder_and_multiline_values(client):
    label = draft(client, {'kind': 'text', 'text': 'Hi {{Product}}!',
                          'paragraphs': [{'runs': [{'text': 'Hi '}, {'text': '{{Pro', 'bold': True}, {'text': 'duct}}!'}]}]})
    merged = merge(label, {'Product': 'Coffee\nTea'})
    assert merged['content']['text'] == 'Hi Coffee\nTea!'
    assert merged['content']['paragraphs'][0]['runs'][1] == {'text': 'Coffee', 'bold': True}
    assert client.post('/studio/api/preview', json=merged).status_code == 200


def test_prepare_100_rows_with_frozen_builtins_and_errors(client):
    template = draft(client, {'kind': 'text', 'text': '{{Name}} {{@row}}/{{@total}} {{@today}} {{@time}}'})
    response = client.post('/studio/api/bulk/prepare', json={
        'template': template, 'csv': 'Name\n' + '\n'.join('Item' + str(i) for i in range(100)), 'timezone': 'America/Toronto'})
    assert response.status_code == 200
    rows = response.json['rows']
    assert len(rows) == 100
    assert all(row['kind'] == 'ready' for row in rows)
    assert '1/100' in rows[0]['draft']['content']['text']
    assert '100/100' in rows[-1]['draft']['content']['text']
    assert rows[0]['draft']['content']['text'].split()[-2:] == rows[-1]['draft']['content']['text'].split()[-2:]
    for row in rows:
        assert client.post('/studio/api/preview', json=row['draft']).status_code == 200


def test_field_errors_and_invalid_barcode_are_per_row(client):
    label = draft(client, {'kind': 'barcode', 'format': 'ean8', 'code': '{{SKU}}', 'caption': '{{Name}}'})
    response = client.post('/studio/api/bulk/prepare', json={
        'template': label, 'csv': 'SKU,Name\n9638507,Tea\nwrong,Coffee', 'timezone': 'UTC'})
    rows = response.json['rows']
    assert rows[0]['kind'] == 'ready'
    assert rows[1]['kind'] == 'error' and rows[1]['line'] == 3
    missing = client.post('/studio/api/bulk/prepare', json={'template': label, 'csv': 'SKU\n9638507'})
    assert 'Unknown field {{Name}}' in missing.json['rows'][0]['message']


def test_csv_values_are_not_evaluated_as_legacy_macros(client, monkeypatch):
    monkeypatch.setenv('BULK_SECRET', 'DO-NOT-RENDER')
    label = draft(client, {'kind': 'qr', 'code': 'example', 'caption': '{{Name}}'})
    merged = merge(label, {'Name': '{{env:BULK_SECRET}}'})
    from app.studio import _render
    with client.application.app_context():
        renderer = _render(merged, None)
        renderer.generate()
        assert renderer.text[0]['text'] == '{{env:BULK_SECRET}}'


def test_builtin_only_batch(client):
    response = client.post('/studio/api/bulk/prepare', json={
        'template': draft(client, {'kind': 'text', 'text': 'Box {{@row}} of {{@total}}'}), 'count': 3})
    assert [row['draft']['content']['text'] for row in response.json['rows']] == ['Box 1 of 3', 'Box 2 of 3', 'Box 3 of 3']


def test_print_batch_and_duplicate_submission(client):
    payload = {'jobId': str(uuid.uuid4()), 'drafts': [draft(client), draft(client)]}
    response = client.post('/studio/api/bulk/print', json=payload)
    assert response.status_code == 200 and response.json['copies'] == 2
    assert client.post('/studio/api/bulk/print', json=payload).status_code == 409


def test_bad_last_label_prevents_entire_batch(client, monkeypatch):
    from app.labeldesigner.printer import PrinterQueue
    def forbidden(*args, **kwargs):
        pytest.fail('Must not send any label')
    monkeypatch.setattr(PrinterQueue, 'process_queue', forbidden)
    bad = draft(client, {'kind': 'barcode', 'format': 'code128', 'code': 'X' * 80, 'caption': ''})
    response = client.post('/studio/api/bulk/print', json={'jobId': str(uuid.uuid4()), 'drafts': [draft(client), bad]})
    assert response.status_code == 400
    assert 'No labels were sent' in response.json['message']


def test_mixed_paper_rejected(client):
    label = draft(client)
    response = client.post('/studio/api/bulk/print', json={'jobId': str(uuid.uuid4()), 'drafts': [label, {**label, 'sizeId': '29x90'}]})
    assert response.status_code == 400


def test_driver_conversion_failure_prevents_sending(client, monkeypatch):
    from app.labeldesigner.printer import PrinterQueue
    def fail_conversion(*args, **kwargs):
        raise ValueError('Bad raster')
    def forbidden(*args, **kwargs):
        pytest.fail('Must not send any label')
    monkeypatch.setattr(PrinterQueue, 'validate_queue', fail_conversion)
    monkeypatch.setattr(PrinterQueue, 'process_queue', forbidden)
    response = client.post('/studio/api/bulk/print', json={'jobId': str(uuid.uuid4()), 'drafts': [draft(client)]})
    assert response.status_code == 400
    assert 'No labels were sent' in response.json['message']


def test_bulk_uses_shared_cut_setting(client, monkeypatch):
    from app.labeldesigner.printer import PrinterQueue
    cuts = []
    add = PrinterQueue.add_label_to_queue
    def capture(self, label, cut, high_res):
        cuts.append(cut)
        return add(self, label, cut, high_res)
    monkeypatch.setattr(PrinterQueue, 'add_label_to_queue', capture)
    result = client.post('/studio/api/bulk/print', json={
        'jobId': str(uuid.uuid4()), 'drafts': [draft(client), draft(client)], 'cut': 'end'})
    assert result.status_code == 200
    assert cuts == [False, True]
