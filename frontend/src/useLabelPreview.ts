import { useEffect, useRef, useState } from "react";
import { api, errorMessage, type Draft } from "./api";
import type { PreviewImage } from "./LabelPreview";
export type Preview =
    | { kind: "empty" }
    | { kind: "pending" }
    | { kind: "ready"; url: string; key: string }
    | { kind: "error"; message: string };

export default function useLabelPreview(
    previewDraft: Draft | null | undefined,
) {
    const [preview, setPreview] = useState<Preview>({ kind: "empty" });
    const [displayedImage, setDisplayedImage] = useState<PreviewImage | null>(
        null,
    );
    const displayedUrl = displayedImage?.url;
    const previewSequence = useRef(0);
    useEffect(
        () => () => {
            if (displayedUrl) URL.revokeObjectURL(displayedUrl);
        },
        [displayedUrl],
    );
    useEffect(() => {
        const draft = previewDraft;
        if (!draft) {
            setDisplayedImage(null);
            setPreview({ kind: "empty" });
            return;
        }
        const sequence = ++previewSequence.current;
        const controller = new AbortController();
        const content = draft.content;
        const empty =
            content.kind === "text"
                ? !content.text.trim()
                : content.kind === "qr" || content.kind === "barcode"
                  ? !content.code.trim()
                  : !content.image;
        if (empty) {
            setDisplayedImage(null);
            setPreview({ kind: "empty" });
            return;
        }
        setPreview({ kind: "pending" });
        const timer = window.setTimeout(() => {
            api.preview(draft, controller.signal)
                .then(async (blob) => {
                    if (
                        controller.signal.aborted ||
                        sequence !== previewSequence.current
                    )
                        return;
                    const url = URL.createObjectURL(blob);
                    const image = new Image();
                    image.src = url;
                    try {
                        await image.decode();
                    } catch (error) {
                        URL.revokeObjectURL(url);
                        throw error;
                    }
                    if (
                        controller.signal.aborted ||
                        sequence !== previewSequence.current
                    ) {
                        URL.revokeObjectURL(url);
                        return;
                    }
                    setDisplayedImage({
                        url,
                        sizeId: draft.sizeId,
                        width: image.naturalWidth,
                        height: image.naturalHeight,
                        draft,
                    });
                    setPreview({
                        kind: "ready",
                        url,
                        key: JSON.stringify(draft),
                    });
                })
                .catch((error) => {
                    if (
                        !controller.signal.aborted &&
                        sequence === previewSequence.current
                    )
                        setPreview({
                            kind: "error",
                            message: errorMessage(error),
                        });
                });
        }, 300);
        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [previewDraft]);

    return { preview, displayedImage, displayedUrl };
}
