"""Printable dimensions and orientation shared by every renderer."""
from dataclasses import dataclass
from brother_ql.labels import ALL_LABELS, FormFactor
from app.labeldesigner.enums import LabelOrientation, LabelType

DEFAULT_DPI = 300


def printable_dimensions(size, high_res=False):
    dimensions = next(label.dots_printable for label in ALL_LABELS if label.identifier == size)
    return tuple(value * (2 if high_res else 1) for value in dimensions)


@dataclass(frozen=True)
class LabelGeometry:
    width: int
    height: int
    orientation: LabelOrientation
    label_type: LabelType


def label_geometry(draft):
    media = next(label for label in ALL_LABELS if label.identifier == draft['sizeId'])
    width, height = printable_dimensions(draft['sizeId'], draft['highRes'])
    if height > width:
        width, height = height, width
    rotated = draft['orientation'] == 'rotated'
    if rotated:
        width, height = height, width
    label_type = {FormFactor.ENDLESS: LabelType.ENDLESS_LABEL,
                  FormFactor.DIE_CUT: LabelType.DIE_CUT_LABEL,
                  FormFactor.ROUND_DIE_CUT: LabelType.ROUND_DIE_CUT_LABEL}[media.form_factor]
    return LabelGeometry(width, height, LabelOrientation.ROTATED if rotated else LabelOrientation.STANDARD, label_type)


def margins(draft):
    return tuple(draft.get('margins', {}).get(side, draft['margin']) for side in ('left', 'right', 'top', 'bottom'))
