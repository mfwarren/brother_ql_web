import type { Draft } from "./api";

const sides = ["top", "right", "bottom", "left"] as const;
export default function MarginControls({
    draft,
    onChange,
    showGuide,
    onShowGuide,
}: {
    draft: Draft;
    onChange: (patch: Partial<Draft>) => void;
    showGuide: boolean;
    onShowGuide: (show: boolean) => void;
}) {
    const margins = draft.margins ?? {
        top: draft.margin,
        right: draft.margin,
        bottom: draft.margin,
        left: draft.margin,
    };
    return (
        <fieldset className="margin-controls">
            <legend>
                Margins <span className="optional">px</span>
            </legend>
            <label className="check-field">
                <input
                    type="checkbox"
                    checked={!draft.margins}
                    onChange={(event) =>
                        onChange(
                            event.target.checked
                                ? { margin: margins.top, margins: undefined }
                                : { margins },
                        )
                    }
                />
                Link sides
            </label>
            <div className="margin-inputs">
                {(draft.margins ? sides : (["top"] as const)).map((side) => (
                    <label className="field" key={side}>
                        {draft.margins
                            ? side[0].toUpperCase() + side.slice(1)
                            : "All sides"}
                        <input
                            type="number"
                            aria-label={
                                draft.margins ? `${side} margin` : "All margins"
                            }
                            min={0}
                            max={100}
                            value={margins[side]}
                            onChange={(event) =>
                                onChange(
                                    draft.margins
                                        ? {
                                              margins: {
                                                  ...margins,
                                                  [side]: Number(
                                                      event.target.value,
                                                  ),
                                              },
                                          }
                                        : {
                                              margin: Number(
                                                  event.target.value,
                                              ),
                                          },
                                )
                            }
                        />
                    </label>
                ))}
            </div>
            <label className="check-field">
                <input
                    type="checkbox"
                    checked={showGuide}
                    onChange={(event) => onShowGuide(event.target.checked)}
                />
                Show margin guides
            </label>
        </fieldset>
    );
}
