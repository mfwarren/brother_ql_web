import { ChevronRight, Settings2 } from "lucide-react";
import { type Config, type Draft, type PrinterStatus } from "../api";
import MarginControls from "../MarginControls";

type Props = {
    draft: Draft;
    config: Config;
    update: (patch: Partial<Draft>) => void;
    layoutOpen: boolean;
    setLayoutOpen: (value: boolean) => void;
    status: PrinterStatus | null;
    detectedRoll: string | undefined;
    showMargins: boolean;
    setShowMargins: (value: boolean) => void;
    cut: "each" | "end";
    setCut: (value: "each" | "end") => void;
};
export default function PaperSettings({
    draft,
    config,
    update,
    layoutOpen,
    setLayoutOpen,
    status,
    detectedRoll,
    showMargins,
    setShowMargins,
    cut,
    setCut,
}: Props) {
    return (
        <details
            className="layout-details panel"
            open={layoutOpen}
            onToggle={(event) => setLayoutOpen(event.currentTarget.open)}
        >
            <summary>
                <Settings2 size={16} /> Label settings{" "}
                <ChevronRight size={16} />
            </summary>
            <div className="form-body">
                <label className="field">
                    Label roll
                    <select
                        value={draft.sizeId}
                        onChange={(event) =>
                            update({
                                sizeId: event.target.value,
                                color: "black",
                                highRes: false,
                                content:
                                    draft.content.kind === "image"
                                        ? {
                                              ...draft.content,
                                              mode: "grayscale",
                                          }
                                        : draft.content,
                            })
                        }
                    >
                        {config.sizes.map((size) => (
                            <option key={size.id} value={size.id}>
                                {size.name}
                            </option>
                        ))}
                    </select>
                </label>
                <div className="detected-roll">
                    <span>
                        {status?.media
                            ? `Loaded: ${status.media}`
                            : "Roll not detected"}
                    </span>
                    {detectedRoll && detectedRoll !== draft.sizeId && (
                        <button
                            className="button subtle"
                            type="button"
                            onClick={() =>
                                update({
                                    sizeId: detectedRoll,
                                    highRes: false,
                                    color: "black",
                                    content:
                                        draft.content.kind === "image"
                                            ? {
                                                  ...draft.content,
                                                  mode: "grayscale",
                                              }
                                            : draft.content,
                                })
                            }
                        >
                            Use loaded roll
                        </button>
                    )}
                </div>
                <div className="two-fields">
                    <label className="field">
                        Orientation
                        <select
                            value={draft.orientation}
                            onChange={(event) =>
                                update({
                                    orientation:
                                        event.target.value === "rotated"
                                            ? "rotated"
                                            : "standard",
                                })
                            }
                        >
                            <option value="standard">Standard</option>
                            <option value="rotated">Rotated 90°</option>
                        </select>
                    </label>
                    <MarginControls
                        draft={draft}
                        onChange={update}
                        showGuide={showMargins}
                        onShowGuide={setShowMargins}
                    />
                </div>
                <label className="check-field">
                    <input
                        type="checkbox"
                        disabled={draft.sizeId === "62red"}
                        checked={draft.highRes}
                        onChange={(event) =>
                            update({
                                highRes: event.target.checked,
                            })
                        }
                    />
                    High resolution <span className="muted">300 × 600 dpi</span>
                </label>
                <label className="field">
                    Cut
                    <select
                        value={cut}
                        onChange={(event) =>
                            setCut(
                                event.target.value === "end" ? "end" : "each",
                            )
                        }
                    >
                        <option value="each">After each label</option>
                        <option value="end">After the last label</option>
                    </select>
                </label>
            </div>
        </details>
    );
}
