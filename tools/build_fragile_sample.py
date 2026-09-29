"""Draw the original fragile sample at three times its approximate print size."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from app import create_app
import app as app_module

create_app()
font_path = app_module.FONTS.get_path('DejaVu Sans,Bold')
image = Image.new('RGB', (1500, 560), 'white')
draw = ImageDraw.Draw(image)
red = '#e00000'
draw.rounded_rectangle((12, 12, 1487, 547), radius=20, outline=red, width=14)
# Broken wine-glass bowl, separated by a jagged fracture.
draw.polygon([(110,90),(360,90),(340,220),(286,202),(251,238),(215,207),(165,230),(135,196)], fill='black')
draw.polygon([(150,254),(211,231),(249,262),(291,226),(333,244),(319,284),(280,323),(252,332),(252,433),(321,447),(321,467),(149,467),(149,447),(218,433),(218,332),(183,312),(160,285)],fill='black')
draw.text((417,124),'FRAGILE',font=ImageFont.truetype(font_path,207),fill=red,stroke_width=1)
draw.text((434,370),'HANDLE WITH CARE',font=ImageFont.truetype(font_path,70),fill='black')
image.save(Path(__file__).resolve().parents[1] / 'app/samples/fragile.png')
