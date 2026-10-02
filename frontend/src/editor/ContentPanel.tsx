import {
    AlignCenter,
    AlignLeft,
    AlignRight,
    Barcode,
    ImagePlus,
    QrCode,
    Type,
} from "lucide-react";
import type { RefObject } from "react";
import {
    verticalAlignment,
    type Config,
    type Content,
    type Draft,
} from "../api";
import RichTextEditor from "../RichTextEditor";

type Props = {
    draft: Draft;
    config: Config;
    content: (value: Content) => void;
    update: (patch: Partial<Draft>) => void;
    changeKind: (kind: Content["kind"]) => void;
    bulkEnabled: boolean;
    uploadInput: RefObject<HTMLInputElement | null>;
    upload: (file: File | undefined) => Promise<void>;
};
export default function ContentPanel({
    draft,
    config,
    content,
    update,
    changeKind,
    bulkEnabled,
    uploadInput,
    upload,
}: Props) {
    return (
        <section className="editor-panel panel">
            <div
                className="content-tabs"
                role="group"
                aria-label="Label content type"
            >
                <button
                    aria-pressed={draft.content.kind === "text"}
                    onClick={() => changeKind("text")}
                >
                    <Type size={18} />
                    Text
                </button>
                <button
                    aria-pressed={draft.content.kind === "qr"}
                    onClick={() => changeKind("qr")}
                >
                    <QrCode size={18} />
                    QR code
                </button>
                <button
                    type="button"
                    aria-pressed={draft.content.kind === "barcode"}
                    onClick={() => changeKind("barcode")}
                >
                    <Barcode size={18} />
                    Barcode
                </button>
                <button
                    aria-pressed={draft.content.kind === "image"}
                    onClick={() => changeKind("image")}
                >
                    <ImagePlus size={18} />
                    Image
                </button>
            </div>
            <div className="form-body">
                {draft.content.kind === "text" && (
                    <RichTextEditor
                        value={draft.content}
                        onChange={content}
                        font={draft.font}
                        size={draft.fontSize}
                        fonts={config.fonts}
                        lineSpacing={draft.lineSpacing ?? 100}
                        onLineSpacingChange={(lineSpacing) =>
                            update({
                                lineSpacing,
                            })
                        }
                    />
                )}
                {draft.content.kind === "barcode" && (
                    <>
                        <label className="field">
                            Barcode type
                            <select
                                aria-label="Barcode type"
                                value={draft.content.format}
                                onChange={(event) => {
                                    const format = event.target.value;
                                    if (
                                        draft.content.kind === "barcode" &&
                                        (format === "code128" ||
                                            format === "ean13" ||
                                            format === "ean8" ||
                                            format === "upca")
                                    )
                                        content({
                                            ...draft.content,
                                            format,
                                        });
                                }}
                            >
                                <option value="code128">
                                    Code 128 · Text and numbers
                                </option>
                                <option value="ean13">
                                    EAN-13 · 12 or 13 digits
                                </option>
                                <option value="ean8">
                                    EAN-8 · 7 or 8 digits
                                </option>
                                <option value="upca">
                                    UPC-A · 11 or 12 digits
                                </option>
                            </select>
                        </label>
                        <label className="field">
                            Barcode value
                            <input
                                aria-label="Barcode value"
                                value={draft.content.code}
                                maxLength={80}
                                placeholder="SKU-0042"
                                onChange={(event) => {
                                    if (draft.content.kind === "barcode")
                                        content({
                                            ...draft.content,
                                            code: event.target.value,
                                        });
                                }}
                            />
                        </label>
                        <label className="field">
                            Caption <span className="optional">optional</span>
                            <input
                                aria-label="Barcode caption"
                                value={draft.content.caption}
                                placeholder="Product or shelf name"
                                onChange={(event) => {
                                    if (draft.content.kind === "barcode")
                                        content({
                                            ...draft.content,
                                            caption: event.target.value,
                                        });
                                }}
                            />
                        </label>
                    </>
                )}
                {draft.content.kind === "qr" && (
                    <>
                        <label className="field">
                            Link or QR content
                            <textarea
                                aria-label="QR content"
                                value={draft.content.code}
                                placeholder="https://example.com"
                                maxLength={2000}
                                onChange={(event) => {
                                    if (draft.content.kind === "qr")
                                        content({
                                            ...draft.content,
                                            code: event.target.value,
                                        });
                                }}
                                rows={3}
                            />
                        </label>
                        <label className="field">
                            Caption <span className="optional">optional</span>
                            <input
                                value={draft.content.caption}
                                placeholder="Scan for more"
                                onChange={(event) => {
                                    if (draft.content.kind === "qr")
                                        content({
                                            ...draft.content,
                                            caption: event.target.value,
                                        });
                                }}
                            />
                        </label>
                    </>
                )}
                {draft.content.kind === "image" && (
                    <>
                        {bulkEnabled && (
                            <label className="field">
                                Image URL or CSV field
                                <input
                                    aria-label="Image URL or CSV field"
                                    placeholder="https://… or {{Photo}}"
                                    value={draft.content.imageUrl ?? ""}
                                    onChange={(event) => {
                                        if (draft.content.kind === "image")
                                            content({
                                                ...draft.content,
                                                image: null,
                                                imageUrl: event.target.value,
                                            });
                                    }}
                                />
                                <small>
                                    Public HTTPS PNG or JPEG. Leave blank to use
                                    the uploaded image.
                                </small>
                            </label>
                        )}

                        <input
                            ref={uploadInput}
                            className="visually-hidden"
                            type="file"
                            accept="image/png,image/jpeg,application/pdf"
                            aria-label="Upload label image"
                            onChange={(event) =>
                                void upload(event.target.files?.[0])
                            }
                        />
                        <button
                            className="upload-area"
                            onClick={() => uploadInput.current?.click()}
                        >
                            <ImagePlus size={27} />
                            <strong>
                                {draft.content.image
                                    ? draft.content.image.name
                                    : "Choose an image or PDF"}
                            </strong>
                            <span>
                                PNG, JPG, or the first page of a PDF · Up to 5
                                MB
                            </span>
                        </button>
                        <label className="field">
                            Caption <span className="optional">optional</span>
                            <input
                                value={draft.content.caption}
                                onChange={(event) => {
                                    if (draft.content.kind === "image")
                                        content({
                                            ...draft.content,
                                            caption: event.target.value,
                                        });
                                }}
                            />
                        </label>
                        <div className="two-fields">
                            <label className="field">
                                Image treatment
                                <select
                                    value={draft.content.mode}
                                    onChange={(event) => {
                                        if (
                                            draft.content.kind === "image" &&
                                            (event.target.value ===
                                                "grayscale" ||
                                                event.target.value === "bw" ||
                                                event.target.value === "red")
                                        )
                                            content({
                                                ...draft.content,
                                                mode: event.target.value,
                                            });
                                    }}
                                >
                                    <option value="grayscale">
                                        Grayscale / dithering
                                    </option>
                                    <option value="bw">Black & white</option>
                                    {draft.sizeId === "62red" && (
                                        <option value="red">Black & red</option>
                                    )}
                                </select>
                            </label>
                            <label className="check-field">
                                <input
                                    type="checkbox"
                                    checked={draft.content.fit}
                                    onChange={(event) => {
                                        if (draft.content.kind === "image")
                                            content({
                                                ...draft.content,
                                                fit: event.target.checked,
                                            });
                                    }}
                                />
                                Fit to label
                            </label>
                        </div>
                    </>
                )}
                <div className="section-divider" />
                {draft.content.kind !== "text" && (
                    <div className="two-fields font-fields">
                        <label className="field">
                            Typeface
                            <select
                                value={draft.font}
                                onChange={(event) =>
                                    update({
                                        font: event.target.value,
                                    })
                                }
                            >
                                {config.fonts.map((font) => (
                                    <option key={font.id} value={font.id}>
                                        {font.name}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label className="field">
                            Size <span className="optional">px</span>
                            <input
                                type="number"
                                min={8}
                                max={200}
                                value={draft.fontSize}
                                onChange={(event) =>
                                    update({
                                        fontSize: Number(event.target.value),
                                    })
                                }
                            />
                        </label>
                    </div>
                )}
                <div className="format-row">
                    <div className="segmented" aria-label="Text alignment">
                        {(
                            [
                                {
                                    value: "left",
                                    Icon: AlignLeft,
                                },
                                {
                                    value: "center",
                                    Icon: AlignCenter,
                                },
                                {
                                    value: "right",
                                    Icon: AlignRight,
                                },
                            ] satisfies {
                                value: Draft["align"];
                                Icon: typeof AlignLeft;
                            }[]
                        ).map(({ value, Icon }) => (
                            <button
                                key={value}
                                aria-label={`Align ${value}`}
                                aria-pressed={draft.align === value}
                                onClick={() =>
                                    update({
                                        align: value,
                                    })
                                }
                            >
                                <Icon size={18} />
                            </button>
                        ))}
                    </div>
                    {draft.content.kind === "text" &&
                        config.sizes.find((item) => item.id === draft.sizeId)
                            ?.fixedSize && (
                            <label className="vertical-choice">
                                Vertical
                                <select
                                    aria-label="Vertical alignment"
                                    value={verticalAlignment(draft)}
                                    onChange={(event) => {
                                        const value = event.target.value;
                                        if (
                                            value === "top" ||
                                            value === "center" ||
                                            value === "bottom"
                                        )
                                            update({
                                                verticalAlign: value,
                                            });
                                    }}
                                >
                                    <option value="top">Top</option>
                                    <option value="center">Center</option>
                                    <option value="bottom">Bottom</option>
                                </select>
                            </label>
                        )}
                    <label className="color-choice">
                        <span>Ink</span>
                        <select
                            aria-label="Ink color"
                            value={draft.color}
                            onChange={(event) =>
                                update({
                                    color:
                                        event.target.value === "red"
                                            ? "red"
                                            : "black",
                                })
                            }
                        >
                            <option value="black">● Black</option>
                            {draft.sizeId === "62red" && (
                                <option value="red">● Red</option>
                            )}
                        </select>
                    </label>
                </div>
            </div>
        </section>
    );
}
