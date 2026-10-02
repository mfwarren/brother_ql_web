"""Normalize text documents and preserve the layout of older plain labels."""
from dataclasses import dataclass
from enum import Enum
import app as app_module
from app.label_geometry import label_geometry, margins
from app.labeldesigner.label import SimpleLabel
from app.labeldesigner.enums import LabelContent
from app.rich_text import render_label


class TextLayout(Enum):
    FLOW = 'flow'
    LEGACY_PLAIN = 'legacy-plain'


@dataclass(frozen=True)
class TextDocument:
    draft: dict
    layout: TextLayout


def normalize_text(draft):
    content = draft['content']
    # These fields marked the introduction of the rich renderer. Older saved
    # documents must retain their ink-based line height and block centering.
    layout = TextLayout.FLOW if ('paragraphs' in content or any(
        key in draft for key in ('verticalAlign', 'lineSpacing', 'margins'))) else TextLayout.LEGACY_PLAIN
    paragraphs = content.get('paragraphs')
    if paragraphs is None:
        paragraphs = [{'runs': [{'text': line}]} for line in content['text'].split('\n')]
    normalized = {**draft, 'content': {**content, 'paragraphs': paragraphs}}
    return TextDocument(normalized, layout)


def plain_lines(text, draft):
    """Prepare font faces for captions and older plain-text documents."""
    font = draft['font']
    return [{'text': line, 'font': font, 'size': str(draft['fontSize']),
             'align': draft['align'], 'color': draft['color'],
             'line_spacing': str(draft.get('lineSpacing', 100)),
             'path': app_module.FONTS.get_path(font), 'variations': app_module.FONTS.get_variations(font)}
            for line in text.splitlines()]


def render_text(draft):
    document = normalize_text(draft)
    if document.layout is TextLayout.FLOW:
        return render_label(document.draft)
    return _render_legacy_plain(document.draft)


def _render_legacy_plain(draft):
    geometry = label_geometry(draft)
    label = SimpleLabel(width=geometry.width, height=geometry.height,
                        label_orientation=geometry.orientation, label_type=geometry.label_type,
                        label_content=LabelContent.TEXT_ONLY, label_margin=margins(draft),
                        text=plain_lines(draft['content']['text'], draft))
    label.expand_templates = False
    return label
