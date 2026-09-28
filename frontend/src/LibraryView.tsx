import { useEffect, useState } from "react";
import {
    ArrowUpRight,
    Copy,
    FolderOpen,
    Plus,
    Printer,
    Search,
    Tag,
    Trash2,
} from "lucide-react";
import { api, type Config, type Draft, type SavedLabel } from "./api";

type Props = {
    labels: SavedLabel[];
    sizes: Config["sizes"];
    search: string;
    onSearchChange: (search: string) => void;
    onNewLabel: () => void;
    simulated: boolean;
    canPrint: boolean;
    busy: boolean;
    onPrint: (draft: Draft) => void;
    onPreview: typeof api.preview;
    onOpen: (label: SavedLabel) => void;
    onDuplicate: (label: SavedLabel) => void;
    onDelete: (label: SavedLabel) => void;
};

export default function LibraryView({
    labels,
    sizes,
    search,
    onSearchChange,
    onNewLabel,
    simulated,
    canPrint,
    busy,
    onPrint,
    onPreview,
    onOpen,
    onDuplicate,
    onDelete,
}: Props) {
    const shownLabels = labels.filter((label) =>
        label.name.toLowerCase().includes(search.toLowerCase()),
    );

    return (
        <>
            <label className="search-field">
                <Search size={18} />
                <input
                    aria-label="Search saved labels"
                    placeholder="Find a label…"
                    value={search}
                    onChange={(event) => onSearchChange(event.target.value)}
                />
            </label>
            {shownLabels.length === 0 ? (
                <div className="empty-library panel">
                    <FolderOpen size={35} />
                    <h2>{search ? "No matching labels" : "No saved labels"}</h2>
                    <p>
                        {search
                            ? "Try a different name."
                            : "Save a label to reuse it."}
                    </p>
                    {!search && (
                        <button className="button primary" onClick={onNewLabel}>
                            <Plus size={17} /> New label
                        </button>
                    )}
                </div>
            ) : (
                <div className="library-grid">
                    {shownLabels.map((label) => (
                        <article className="saved-card panel" key={label.id}>
                            <SavedPreview
                                draft={label.draft}
                                onPreview={onPreview}
                            />
                            <div className="saved-card-body">
                                <h2>{label.name}</h2>
                                <p>
                                    {sizes.find(
                                        (size) =>
                                            size.id === label.draft.sizeId,
                                    )?.name ?? label.draft.sizeId}{" "}
                                    ·{" "}
                                    {label.draft.content.kind === "qr"
                                        ? "QR code"
                                        : label.draft.content.kind}
                                </p>
                                <div className="saved-actions">
                                    <button
                                        className="button subtle"
                                        onClick={() => onOpen(label)}
                                    >
                                        Open <ArrowUpRight size={15} />
                                    </button>
                                    <button
                                        className="icon-button"
                                        aria-label={
                                            (simulated
                                                ? "Test print "
                                                : "Print ") + label.name
                                        }
                                        disabled={!canPrint || busy}
                                        onClick={() => onPrint(label.draft)}
                                    >
                                        <Printer size={18} />
                                    </button>
                                    <button
                                        className="icon-button"
                                        aria-label={"Duplicate " + label.name}
                                        onClick={() => onDuplicate(label)}
                                    >
                                        <Copy size={16} />
                                    </button>
                                    <button
                                        className="icon-button danger"
                                        aria-label={"Delete " + label.name}
                                        onClick={() => onDelete(label)}
                                    >
                                        <Trash2 size={16} />
                                    </button>
                                </div>
                            </div>
                        </article>
                    ))}
                </div>
            )}
            <p className="library-footnote">
                Labels made in the <a href="/labeldesigner/">advanced editor</a>{" "}
                stay in its separate library, with all their formatting intact.
            </p>
        </>
    );
}

function SavedPreview({
    draft,
    onPreview,
}: {
    draft: Draft;
    onPreview: typeof api.preview;
}) {
    const [url, setUrl] = useState<string | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        let imageUrl: string | null = null;
        onPreview(draft, controller.signal)
            .then((blob) => {
                if (!controller.signal.aborted) {
                    imageUrl = URL.createObjectURL(blob);
                    setUrl(imageUrl);
                }
            })
            .catch(() => setUrl(null));
        return () => {
            controller.abort();
            if (imageUrl) URL.revokeObjectURL(imageUrl);
        };
    }, [draft]);

    return (
        <div className="saved-preview">
            {url ? (
                <img src={url} alt="Saved label preview" />
            ) : (
                <Tag size={26} />
            )}
        </div>
    );
}
