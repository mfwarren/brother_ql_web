# Bulk labels from CSV

Design a text, QR, barcode, or image label in the editor, then turn on **Bulk**. The designer stays in place; the CSV and batch review panel appears below it.
Keep using the same Text, QR, Barcode, and Image tabs, formatting toolbar, and paper settings. There is no separate template editor. Checking the batch selects the first valid row in the main preview. Choose **Preview N** on any review card to show that row there. Changing the design invalidates the reviewed batch; check it again before printing.

Write a CSV column name inside double braces, such as `{{Product}}`.
Names are case-sensitive. Values are inserted literally; formulas and code are never executed.

| Field | Value |
| --- | --- |
| `{{Product}}` | The current row's Product column |
| `{{@today}}` | Local date, YYYY-MM-DD |
| `{{@time}}` | Local time, HH:mm |
| `{{@row}}` | Label number, starting at 1 |
| `{{@total}}` | Number of nonblank data rows |

The browser's timezone sets the date and time. Built-ins are fixed when you
check the batch, so reviewing and printing across midnight does not change them.
If you select only some rows, their original numbers and total remain unchanged.
For other numbering or date formats, create columns in your spreadsheet.

Upload a UTF-8 CSV, or paste its contents. The first row must contain unique,
nonempty column names. Quoted commas, multiline cells, and leading zeroes are
preserved. Blank rows are skipped. Column names cannot contain braces or start
with @. Each batch supports up to 100 rows and 50 columns, with a 1 MB CSV limit.
Without a CSV, choose a label count to use only built-in variables.

Choose **Check & preview every label**. All rows are validated and rendered
sequentially, with progress and cancellation. Each card shows its label number
and CSV line. Open a preview to inspect the full image, or filter to errors.
Fix the CSV or template and check again. Valid labels are selected initially;
the final confirmation states how many labels will print and how many are skipped.
Review every image for visual fit: a successful render is not a guarantee that
all text fits the selected paper or that a physical barcode will scan.

**Download template** saves a reusable JSON file, including paper and formatting.
**Load template** restores it. CSV rows are not included in that file. Replacing
the CSV or editing the template clears the previous review. CSV data stays in memory while you switch tabs or toggle Bulk. Download your template before reloading or closing the page.

Every selected label is rendered and converted for the printer before the first
label is sent. A batch uses one paper size and resolution and follows the designer's Cut setting.
The server checks the loaded paper and holds the printer lock throughout printing.
Duplicate submissions with the same batch ID are rejected. If the connection or
printer fails after sending begins, some labels may already have printed. Inspect
the output before creating another batch; the app does not automatically retry.


## Images from CSV

In the Image tab with Bulk enabled, set **Image URL or CSV field** to a field
such as `{{Photo}}`, or a direct image URL. Each Photo cell should contain a
public HTTPS link to a PNG or JPEG, up to 5 MB and 16 megapixels. Authenticated
links, private network addresses, and custom ports are unsupported.

Images download sequentially while checking rows. Repeated URLs download once
per check. A failed download appears on its row. The reviewed image bytes are
kept in the resolved label and sent with the print request, so printing does not
fetch a potentially changed URL. Large images may require selecting fewer rows
to stay within the server's request-size limit. Uploading a file in the usual
Image tab replaces the URL source.
