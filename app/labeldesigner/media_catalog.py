"""Brother SKU aliases for existing, tested raster geometry definitions."""
import json
from pathlib import Path

from brother_ql.labels import ALL_LABELS, Color, FormFactor
from brother_ql.models import ALL_MODELS

CATALOG = json.loads((Path(__file__).parents[1] / 'data/label-rolls.json').read_text())


def supported_labels(model):
    two_color = any(item.identifier == model and item.two_color for item in ALL_MODELS)
    is_ptouch = model.startswith('PT-')
    return [label for label in ALL_LABELS
            if (label.form_factor == FormFactor.PTOUCH_ENDLESS) == is_ptouch
            and (not label.restricted_to_models or model in label.restricted_to_models)
            and (label.color != Color.BLACK_RED_WHITE or two_color)]


def label_info(label):
    details = CATALOG.get(label.identifier, {})
    codes = details.get('codes', [])
    name = label.name
    if codes:
        name += ' · ' + ' / '.join(codes[:2])
    elif label.identifier == '12+17':
        name += ' (12+17 profile)'
    return {'fixedSize': label.form_factor in (FormFactor.DIE_CUT, FormFactor.ROUND_DIE_CUT), 'id': label.identifier, 'name': name, 'codes': codes,
            'description': details.get('description', 'Generic driver profile')}
