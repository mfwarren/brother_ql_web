import type { Draft } from "./api";
export type PreviewImage = {
    url: string;
    sizeId: string;
    width: number;
    height: number;
    draft: Draft;
};

export default function LabelPreview({
    image,
    fixed,
    guide,
}: {
    image: PreviewImage;
    fixed: boolean;
    guide: boolean;
}) {
    const { draft, width, height, url } = image;
    const margins = draft.margins ?? {
        top: draft.margin,
        right: draft.margin,
        bottom: draft.margin,
        left: draft.margin,
    };
    // The printer preview rotates standard die-cut and rotated continuous labels clockwise.
    const rotated = fixed
        ? draft.orientation === "standard"
        : draft.orientation === "rotated";
    const { top, right, bottom, left } = rotated
        ? {
              top: margins.left,
              right: margins.top,
              bottom: margins.right,
              left: margins.bottom,
          }
        : margins;
    return (
        <svg
            className="label-preview-image"
            role="img"
            aria-label="Rendered label preview"
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
        >
            <image href={url} width={width} height={height} />
            {guide && (
                <rect
                    x={left}
                    y={top}
                    width={Math.max(0, width - left - right)}
                    height={Math.max(0, height - top - bottom)}
                    fill="none"
                    stroke="#387ac3"
                    strokeWidth="1"
                    strokeDasharray="4 3"
                    vectorEffect="non-scaling-stroke"
                />
            )}
        </svg>
    );
}
