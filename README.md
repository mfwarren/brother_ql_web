# Label Studio for Brother QL

Design and print labels from your phone, tablet, or computer. Connect a Brother QL printer to a Raspberry Pi or Linux computer, open Label Studio in your browser, and share the printer with everyone on your local network.

Make labels for storage bins, mailing addresses, file folders, equipment, guest Wi-Fi, and packages. Save the ones you use often so the next print takes just a few clicks.

[Download](https://github.com/mfwarren/brother_ql_web/releases/latest) · [Installation guide](STUDIO.md) · [Report an issue](https://github.com/mfwarren/brother_ql_web/issues)

![Label Studio desktop editor](docs/design/desktop.png)

## Make the label you need

- Mix font families, weights, sizes, bold, italic, and underline within the same label. Select words to format them independently.
- Merge CSV data into text, QR, barcode, and image-caption templates. Preview up to 100 labels, fix row errors, and print selected rows. [Bulk printing guide](docs/bulk-printing.md).
- Create Code 128, EAN-13, EAN-8, and UPC-A barcodes with optional captions. Retail check digits are calculated and validated automatically.
- Add QR codes with captions, upload images, or print the first page of a PDF. Use QR labels for links, equipment identifiers, or Wi-Fi access.
- Adjust orientation, line spacing, individual margins, and text alignment. Show margin guides in the preview to check the usable area. Center text vertically on fixed-size labels, or let continuous labels grow to fit the content.
- Check the rendered preview before printing. It stays visible while edits update, so you can keep working without the page jumping around.
- Choose fonts from Google Fonts or upload TTF/OTF files. Installed fonts stay on the printer host and are available to everyone using the app.
- Save labels with their formatting and paper settings. Reprint a favorite, duplicate it for a new item, or print several copies at once.

## Share one printer

Label Studio runs on a computer connected to your printer. Everyone else uses a browser, with no printer-driver installation needed on their phone or laptop. The interface adapts to desktop, tablet, and phone screens, with print controls close at hand.

On the QL-800, the app detects the loaded roll's width, die-cut length, and black-only or black/red media. New labels can follow the loaded roll automatically. Saved labels keep their own paper settings, and the app checks for a mismatch before printing.

Set shared defaults for fonts, label size, orientation, and margins in Settings. A searchable Brother DK roll catalog helps you find the right paper profile.

| Tablet | Phone |
| --- | --- |
| ![Tablet editor](docs/design/ipad.png) | ![Phone editor](docs/design/phone.png) |

## Start with an example

Nine sample labels give you a starting point, including storage labels, mailing addresses, visitor badges, QR tags, handling arrows, and a red Fragile label. Open a sample, replace the example content, check the paper settings, and print.

| Storage bin | QR asset tag | Mailing address |
| --- | --- | --- |
| ![Storage label](docs/samples/text.png) | ![QR label](docs/samples/qr.png) | ![Address label](docs/samples/mailing-address.png) |

Black/red printing requires a compatible printer and black/red label roll. The Fragile sample is configured for that stock.

## Get started

1. [Download the latest release](https://github.com/mfwarren/brother_ql_web/releases/latest). Choose the `label-studio` archive, which includes the built web interface.
2. Follow the [installation guide](STUDIO.md) on your Raspberry Pi or Linux computer. You can try the simulator before connecting a printer.
3. Connect your printer, open Label Studio in a browser, and check the Printer page. Choose a sample or create your first label.

For a printer host that starts automatically and serves the app on port 80, follow the [Raspberry Pi service guide](deploy/README.md).

Label Studio is intended for a trusted home or workspace network. It has no user accounts; anyone who can reach the app can print and change its settings. Keep it off the public internet.

## Printer compatibility

The tested setup is a Brother QL-800 connected by USB to a Raspberry Pi 3 running Raspberry Pi OS. Printing and media detection have been exercised with 62 mm black-only continuous tape, 62 mm black/red continuous tape, and 29 × 90 mm die-cut labels.

The driver supports additional Brother QL models, but those have not all been tested with Label Studio. Reports from other printer owners are welcome. Include your model, connection type, and label roll when [opening an issue](https://github.com/mfwarren/brother_ql_web/issues).

[Contributing](CONTRIBUTING.md) · [GPL-3.0 license](LICENSE)
