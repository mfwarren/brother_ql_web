"""Tiny original variable font fixtures; no external downloads or font licenses."""
import io

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.designspaceLib import DesignSpaceDocument, AxisDescriptor, SourceDescriptor
from fontTools.varLib import build


def variable_font(directory, italic=False):
    document = DesignSpaceDocument()
    axis = AxisDescriptor(); axis.name = 'Weight'; axis.tag = 'wght'
    axis.minimum = axis.default = 100; axis.maximum = 900
    document.addAxis(axis)
    for weight, stroke in [(100, 50), (900, 500)]:
        fb = FontBuilder(1000, isTTF=True)
        fb.setupGlyphOrder(['.notdef', 'space', 'A'])
        glyphs = {}
        for name in ['.notdef', 'space', 'A']:
            pen = TTGlyphPen(None)
            if name != 'space':
                skew = 100 if italic else 0
                pen.moveTo((50, 0)); pen.lineTo((50+stroke, 0))
                pen.lineTo((50+stroke+skew, 700)); pen.lineTo((50+skew, 700)); pen.closePath()
            glyphs[name] = pen.glyph()
        fb.setupGlyf(glyphs)
        fb.setupHorizontalMetrics({name:(700,50) for name in glyphs})
        fb.setupHorizontalHeader(ascent=800, descent=-200)
        fb.setupCharacterMap({32:'space',65:'A'})
        fb.setupNameTable({'familyName':'Test Variable Thin','styleName':'Italic' if italic else 'Regular',
                          'uniqueFontIdentifier':f'test-{weight}-{italic}','fullName':'Test Variable',
                          'psName':f'TestVariable{weight}', 'typographicFamily':'Test Variable'})
        fb.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200,
                    usWeightClass=weight,fsSelection=1 if italic else 0)
        fb.setupPost(); fb.setupMaxp()
        path=directory / f'{weight}-{italic}.ttf'; fb.save(path)
        source=SourceDescriptor(); source.path=str(path); source.name=str(weight); source.location={'Weight':weight}
        document.addSource(source)
    font, _, _ = build(document)
    out=io.BytesIO(); font.save(out); return out.getvalue()
