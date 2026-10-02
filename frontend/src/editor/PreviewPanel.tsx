import {
    ArrowDownToLine,
    CircleHelp,
    LoaderCircle,
    RotateCw,
    Tag,
} from "lucide-react";
import { type Config, type Draft } from "../api";
import LabelPreview, { type PreviewImage } from "../LabelPreview";
import type { Preview } from "../useLabelPreview";

type Props = {
    draft: Draft;
    config: Config;
    bulkPreview: { draft: Draft; row: number } | null;
    preview: Preview;
    displayedImage: PreviewImage | null;
    displayedUrl: string | undefined;
    sizeName: string;
    showMargins: boolean;
    name: string;
};
export default function PreviewPanel({
    draft,
    config,
    bulkPreview,
    preview,
    displayedImage,
    displayedUrl,
    sizeName,
    showMargins,
    name,
}: Props) {
    return (
        <section className="preview-panel panel">
            <div className="panel-heading">
                <div>
                    <h2>
                        Preview
                        {bulkPreview && " · Row " + bulkPreview.row}
                    </h2>
                </div>
                <span className="preview-tag">
                    <i
                        className={`dot ${preview.kind === "ready" ? "ready" : "unknown"}`}
                    />
                    {preview.kind === "pending"
                        ? "Updating"
                        : preview.kind === "ready"
                          ? "Ready"
                          : "Preview"}
                </span>
            </div>
            <div
                className="preview-stage"
                aria-busy={preview.kind === "pending"}
            >
                {preview.kind === "pending" && (
                    <div
                        className="preview-update"
                        role="status"
                        aria-label="Updating preview"
                    >
                        <LoaderCircle className="spin" size={18} />
                    </div>
                )}
                {displayedUrl && preview.kind === "error" && (
                    <div className="preview-update preview-error" role="alert">
                        {preview.message}
                    </div>
                )}
                <span className="dimension">{sizeName}</span>
                <div
                    className={
                        config.sizes.find(
                            (size) => size.id === displayedImage?.sizeId,
                        )?.fixedSize
                            ? "label-artwork die-cut"
                            : "label-artwork"
                    }
                >
                    {displayedUrl ? (
                        <LabelPreview
                            image={displayedImage!}
                            fixed={
                                !!config.sizes.find(
                                    (size) =>
                                        size.id === displayedImage?.sizeId,
                                )?.fixedSize
                            }
                            guide={showMargins}
                        />
                    ) : preview.kind === "pending" ? (
                        <div className="preview-placeholder" />
                    ) : preview.kind === "error" ? (
                        <div
                            className="preview-placeholder preview-error"
                            role="alert"
                        >
                            <CircleHelp size={25} />
                            <strong>Preview unavailable</strong>
                            <span>{preview.message}</span>
                        </div>
                    ) : (
                        <div className="preview-placeholder">
                            <Tag size={26} />
                            <span>Enter content to preview</span>
                        </div>
                    )}
                </div>
            </div>
            <div className="preview-toolbar">
                <span>
                    <RotateCw size={14} />
                    {draft.highRes ? "300 × 600" : "300 × 300"} dpi
                </span>
                <span>Preview scaled to fit</span>
                {preview.kind === "ready" && (
                    <a
                        href={preview.url}
                        download={`${name || "label"}.png`}
                        title="Download preview"
                        aria-label="Download preview"
                    >
                        <ArrowDownToLine size={17} />
                    </a>
                )}
            </div>
        </section>
    );
}
