# Brother DK roll codes

The catalog maps 55 regional product codes to 21 existing raster profiles. It
adds names and aliases, not unverified print geometry. Settings includes a
searchable code list; the roll selectors show the main North American and
international codes. Saved labels retain their existing size IDs.

The printer reports dimensions and, on the verified QL-800, ink-color mode. It
does not identify an exact SKU, adhesive, paper versus film, or backing color.
Different products can therefore share one print profile. Codes in a row are
compatible size selections, not identical materials. Black-only describes the
print mode, not the color of the backing.

## Sources

- [Brother Canada DK label catalog](https://www.brother.ca/en/supplies-accessories/c/pr-labelling-sa)
- [Brother QL-570 consumables reference, including regional North American codes](https://download.brother.com/welcome/docp000062/ql570qs0ecafreca.pdf)
- [Brother international DK catalog](https://www.brother.co.uk/~/media/58a4cf49d87a405a9454fff894090398.pdf)
- [Brother current DK roll leaflet](https://www.brother.co.uk/-/media/pdf/buk/labelling/dk-label-roll/dk-roll-test-leaflet-2022.pdf?rev=7ee59ec4c7e34993ab7354531db798cb)
- [Brother QL-800 supplies](https://www.brother.com.mx/-/media/brother/product-catalog-media/documents/2020/09/25/11/10/bro8392-ql-800seriesbrochure-v5.pdf)
- [Brother DK-22251 black/red roll](https://www.brother.com.au/en/supplies/supplies-detail/dk-22251)
- [Brother non-adhesive and film stock codes](https://www.brother-usa.com/-/media/solutions/newsroom/files/healthcare-labeling-solutions-2020_supplies.pdf)

## Profiles and codes

| Driver profile | Use | Product codes |
| --- | --- | --- |
| `12` | Continuous paper | DK-2214, DK-22214 |
| `29` | Continuous paper or film | DK-2210, DK-22210, DK-2211, DK-22211 |
| `38` | Continuous paper | DK-2225, DK-22225 |
| `50` | Continuous paper | DK-2223, DK-22223 |
| `54` | Continuous non-adhesive paper | DK-N5224, DK-N55224, DK-55224 |
| `62` | Continuous paper, film, clear, yellow, or removable stock | DK-2205, DK-22205, DK-2212, DK-22212, DK-2113, DK-22113, DK-2606, DK-22606, DK-4205, DK-44205, DK-4605, DK-44605 |
| `62red` | Continuous black/red on white | DK-2251, DK-22251 |
| `17x54` | Multipurpose / return address | DK-1204, DK-11204 |
| `17x87` | File folder | DK-1203, DK-11203 |
| `23x23` | Square | DK-1221, DK-11221 |
| `29x90` | Standard address | DK-1201, DK-11201 |
| `39x90` | Large address | DK-1208, DK-11208 |
| `62x29` | Small address | DK-1209, DK-11209 |
| `60x86` | Visitor badge (marketed as 60 × 86 mm) | DK-1234, DK-11234 |
| `62x100` | Shipping | DK-1202, DK-11202 |
| `d12` | Round | DK-1219, DK-11219 |
| `d24` | Round | DK-1218, DK-11218 |
| `d58` | CD/DVD round film | DK-1207, DK-11207 |
| `102` | Wide continuous paper | DK-2243, DK-22243 |
| `102x51` | Wide multipurpose | DK-1240, DK-11240 |
| `102x152` | Wide shipping (marketed as 102 × 152 mm) | DK-1241, DK-11241 |

Wide-format profiles appear only for the models allowed by the driver. P-touch
profiles are excluded from QL printers; black/red profiles require a two-color
model. Generic driver profiles without verified SKU mappings remain available.

Profile IDs and protocol dimensions are not always the marketed dimensions:
`39x90` uses 38 × 90 mm, `60x86` uses 60 × 87 mm, `102x152` uses 102 × 153 mm,
and the small-address `62x29` feeds across the 62 mm edge. The app retains the
driver's dimensions for detection and rendering rather than guessing new values
from retail descriptions. The 12+17 profile shares reported dimensions with the
ordinary 12 mm roll, so ambiguous detection still requires manual selection.

Only the owner's 29 × 90 mm and two 62 mm continuous rolls have been physically
verified. Other catalog profiles use the upstream driver geometry and simulated
status tests; they have not been physically printed in this project.
