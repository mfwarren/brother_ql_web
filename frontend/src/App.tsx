import { useEffect, useRef, useState } from "react";
import {
    AlertTriangle,
    AlignCenter,
    AlignLeft,
    AlignRight,
    ArrowDownToLine,
    ArrowUpRight,
    Check,
    ChevronRight,
    CircleHelp,
    FolderOpen,
    Save,
    Search,
    ImagePlus,
    LayoutGrid,
    LoaderCircle,
    Plus,
    Printer,
    QrCode,
    RotateCw,
    Settings2,
    Tag,
    Trash2,
    Type,
    X,
} from "lucide-react";
import {
    api,
    errorMessage,
    starter,
    labelTitle,
    paperMismatch,
    type Config,
    type Content,
    type Draft,
    type PrinterStatus,
    type SavedLabel,
} from "./api";
import LibraryView from "./LibraryView";
import PrinterView from "./PrinterView";
import SettingsView from "./SettingsView";
import RichTextEditor from "./RichTextEditor";

type Page = "editor" | "library" | "printer" | "settings";
type Preview =
    | { kind: "empty" }
    | { kind: "pending" }
    | { kind: "ready"; url: string; key: string }
    | { kind: "error"; message: string };
const statusNames: Record<PrinterStatus["state"], string> = {
    simulation: "Preview mode",
    ready: "Ready to print",
    offline: "Printer offline",
    busy: "Printer busy",
    error: "Needs attention",
    unknown: "Status unknown",
};

export default function App() {
    const [config, setConfig] = useState<Config | null>(null);
    const [draft, setDraft] = useState<Draft | null>(null);
    const [status, setStatus] = useState<PrinterStatus | null>(null);
    const [layoutOpen, setLayoutOpen] = useState(window.innerWidth >= 1100);
    const [page, setPage] = useState<Page>("editor");
    const [labels, setLabels] = useState<SavedLabel[]>([]);
    const [followLoadedRoll, setFollowLoadedRoll] = useState(true);
    const [activeId, setActiveId] = useState<string | null>(null);
    const [name, setName] = useState("");
    const [search, setSearch] = useState("");
    const [preview, setPreview] = useState<Preview>({ kind: "empty" });
    const [copies, setCopies] = useState(1);
    const [cut, setCut] = useState<"each" | "end">("each");
    const [busy, setBusy] = useState(false);
    const [notice, setNotice] = useState<{
        text: string;
        error: boolean;
    } | null>(null);
    const [startupError, setStartupError] = useState("");
    const [deleteTarget, setDeleteTarget] = useState<SavedLabel | null>(null);
    const [redPrint, setRedPrint] = useState<{
        draft: Draft;
        copies: number;
    } | null>(null);
    const redDialog = useRef<HTMLDialogElement>(null);
    const saveDialog = useRef<HTMLDialogElement>(null);
    const deleteDialog = useRef<HTMLDialogElement>(null);
    const uploadInput = useRef<HTMLInputElement>(null);
    const previewSequence = useRef(0);
    const contentDrafts = useRef(new Map<Content["kind"], Content>());
    const draftKey = JSON.stringify(draft);

    useEffect(() => {
        let alive = true;
        Promise.all([api.config(), api.list()])
            .then(([settings, saved]) => {
                if (alive) {
                    setConfig(settings);
                    setDraft(starter(settings));
                    setLabels(saved);
                }
            })
            .catch((error) => {
                if (alive) setStartupError(errorMessage(error));
            });
        let refreshing = false;
        const refresh = () => {
            if (refreshing) return;
            refreshing = true;
            return api
                .status()
                .then((value) => {
                    if (alive) setStatus(value);
                })
                .catch((error) => {
                    if (alive)
                        setStatus({
                            state: "unknown",
                            model: "QL-800",
                            media: null,
                            matchingSizes: [],
                            mediaColor: "unknown",
                            message: errorMessage(error),
                        });
                })
                .finally(() => {
                    refreshing = false;
                });
        };
        void refresh();
        const timer = window.setInterval(refresh, 5000);
        return () => {
            alive = false;
            window.clearInterval(timer);
        };
    }, []);

    const detectedRoll =
        status?.state === "ready" && status.matchingSizes.length === 1
            ? status.matchingSizes[0]
            : undefined;
    useEffect(() => {
        if (
            !detectedRoll ||
            !config?.defaults.autoDetectRoll ||
            !followLoadedRoll ||
            activeId
        )
            return;
        setDraft((current) =>
            current && current.sizeId !== detectedRoll
                ? {
                      ...current,
                      sizeId: detectedRoll,
                      highRes: false,
                      color: "black",
                      content:
                          current.content.kind === "image"
                              ? { ...current.content, mode: "grayscale" }
                              : current.content,
                  }
                : current,
        );
    }, [detectedRoll, config, followLoadedRoll, activeId, draft?.sizeId]);

    useEffect(() => {
        if (!draft) return;
        const sequence = ++previewSequence.current;
        const controller = new AbortController();
        let url: string | null = null;
        const content = draft.content;
        const empty =
            content.kind === "text"
                ? !content.text.trim()
                : content.kind === "qr"
                  ? !content.code.trim()
                  : !content.image;
        if (empty) {
            setPreview({ kind: "empty" });
            return;
        }
        setPreview({ kind: "pending" });
        const timer = window.setTimeout(() => {
            api.preview(draft, controller.signal)
                .then((blob) => {
                    if (
                        controller.signal.aborted ||
                        sequence !== previewSequence.current
                    )
                        return;
                    url = URL.createObjectURL(blob);
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
            if (url) URL.revokeObjectURL(url);
        };
    }, [draft]);

    useEffect(() => {
        const media = window.matchMedia("(min-width: 1100px)");
        const sync = () => setLayoutOpen(media.matches);
        media.addEventListener("change", sync);
        return () => media.removeEventListener("change", sync);
    }, []);

    function update(values: Partial<Draft>) {
        if (values.sizeId !== undefined) setFollowLoadedRoll(false);
        setDraft((current) => (current ? { ...current, ...values } : current));
    }
    function content(next: Content) {
        update({ content: next });
    }
    function changeKind(kind: Content["kind"]) {
        if (!draft || draft.content.kind === kind) return;
        contentDrafts.current.set(draft.content.kind, draft.content);
        const saved = contentDrafts.current.get(kind);
        content(
            saved ??
                (kind === "text"
                    ? { kind, text: "" }
                    : kind === "qr"
                      ? { kind, code: "", caption: "" }
                      : {
                            kind,
                            image: null,
                            caption: "",
                            mode: "grayscale",
                            fit: true,
                        }),
        );
    }
    function notify(text: string, error = false) {
        setNotice({ text, error });
    }
    async function newLabel() {
        try {
            const latest = await api.config();
            setConfig(latest);
            contentDrafts.current.clear();
            setDraft(starter(latest));
            setFollowLoadedRoll(true);
            setActiveId(null);
            setName("");
            setPage("editor");
            setNotice(null);
        } catch (error) {
            notify(errorMessage(error), true);
        }
    }
    function open(label: SavedLabel) {
        contentDrafts.current.clear();
        setDraft(label.draft);
        setFollowLoadedRoll(false);
        setActiveId(label.id);
        setName(label.name);
        setPage("editor");
        setNotice(null);
    }
    async function print(target: Draft, count = 1, confirmRedMedia = false) {
        if (busy) return;
        setBusy(true);
        try {
            if (config?.mode === "physical") {
                const fresh = await api.status();
                setStatus(fresh);
                if (fresh.state !== "ready") {
                    notify(fresh.message, true);
                    return;
                }
                if (paperMismatch(target, fresh)) {
                    const required =
                        config.sizes.find((size) => size.id === target.sizeId)
                            ?.name ?? target.sizeId;
                    notify(
                        `Paper mismatch. Label needs ${required}; loaded: ${fresh.media ?? "unknown"}.`,
                        true,
                    );
                    return;
                }
                if (
                    target.sizeId === "62red" &&
                    !confirmRedMedia &&
                    fresh.mediaColor !== "black-red"
                ) {
                    setRedPrint({ draft: target, copies: count });
                    redDialog.current?.showModal();
                    return;
                }
            }
            const result = await api.print(target, count, cut, confirmRedMedia);
            notify(result.message);
            void api
                .status()
                .then(setStatus)
                .catch(() => setStatus(null));
        } catch (error) {
            notify(errorMessage(error), true);
            void api
                .status()
                .then(setStatus)
                .catch(() => setStatus(null));
        } finally {
            setBusy(false);
        }
    }
    function showSave() {
        if (!activeId && draft) setName(labelTitle(draft.content));
        saveDialog.current?.showModal();
    }
    async function save() {
        if (!draft || !name.trim() || busy) return;
        setBusy(true);
        try {
            const saved = await api.save(name.trim(), draft, activeId);
            setActiveId(saved.id);
            setName(saved.name);
            setLabels(await api.list());
            saveDialog.current?.close();
            notify(`Saved “${saved.name}” to your library.`);
        } catch (error) {
            notify(errorMessage(error), true);
        } finally {
            setBusy(false);
        }
    }
    async function remove() {
        if (!deleteTarget) return;
        setBusy(true);
        try {
            await api.remove(deleteTarget.id);
            setLabels(await api.list());
            if (activeId === deleteTarget.id) setActiveId(null);
            deleteDialog.current?.close();
            setDeleteTarget(null);
            notify("Label deleted.");
        } catch (error) {
            notify(errorMessage(error), true);
        } finally {
            setBusy(false);
        }
    }
    async function upload(file: File | undefined) {
        if (!file || draft?.content.kind !== "image") return;
        if (file.size > 5 * 1024 * 1024) {
            notify("Choose a file smaller than 5 MB.", true);
            return;
        }
        if (
            !["image/png", "image/jpeg", "application/pdf"].includes(file.type)
        ) {
            notify("Choose a PNG, JPEG, or PDF file.", true);
            return;
        }
        const bytes = new Uint8Array(await file.arrayBuffer());
        let binary = "";
        bytes.forEach((byte) => {
            binary += String.fromCharCode(byte);
        });
        content({
            ...draft.content,
            image: { name: file.name, mime: file.type, base64: btoa(binary) },
        });
        setNotice(null);
    }
    const simulated = config?.mode === "simulation";
    const canPrint =
        !!status && (status.state === "ready" || status.state === "simulation");
    const mismatchedPaper =
        !simulated && !!draft && paperMismatch(draft, status);
    const previewCurrent = preview.kind === "ready" && preview.key === draftKey;
    const activeName = activeId
        ? name
        : draft
          ? labelTitle(draft.content)
          : "Label Studio";
    const sizeName =
        config?.sizes.find((size) => size.id === draft?.sizeId)?.name ??
        "62 mm continuous";
    const shownLabels = labels.filter((label) =>
        label.name.toLowerCase().includes(search.toLowerCase()),
    );

    useEffect(() => {
        const handleShortcut = (event: KeyboardEvent) => {
            if (
                !(event.metaKey || event.ctrlKey) ||
                page !== "editor" ||
                document.querySelector("dialog[open]")
            )
                return;
            if (event.key.toLowerCase() === "s") {
                event.preventDefault();
                if (previewCurrent && !busy) showSave();
            }
            if (event.key === "Enter") {
                event.preventDefault();
                if (
                    draft &&
                    canPrint &&
                    !mismatchedPaper &&
                    previewCurrent &&
                    !busy &&
                    Number.isInteger(copies) &&
                    copies >= 1 &&
                    copies <= 100
                )
                    void print(draft, copies);
            }
        };
        window.addEventListener("keydown", handleShortcut);
        return () => window.removeEventListener("keydown", handleShortcut);
    });

    return (
        <div
            className={`shell page-${page}${mismatchedPaper ? " paper-mismatch" : ""}`}
        >
            <aside className="sidebar">
                <a
                    className="brand"
                    href="/studio/"
                    aria-label="Label Studio home"
                >
                    <span className="brand-mark">
                        <Tag size={22} strokeWidth={2.3} />
                    </span>
                    <span>Label Studio</span>
                </a>
                <nav aria-label="Main navigation">
                    <button
                        className={
                            page === "editor" ? "nav-item active" : "nav-item"
                        }
                        onClick={() => setPage("editor")}
                    >
                        <Type size={19} />
                        <span>Editor</span>
                    </button>
                    <button
                        className={
                            page === "library" ? "nav-item active" : "nav-item"
                        }
                        onClick={() => setPage("library")}
                    >
                        <LayoutGrid size={18} />
                        <span>Labels</span>{" "}
                        <span className="count">{labels.length}</span>
                    </button>
                    <button
                        className={
                            page === "printer" ? "nav-item active" : "nav-item"
                        }
                        onClick={() => setPage("printer")}
                    >
                        <Printer size={18} />
                        <span>Printer</span>
                    </button>
                    <button
                        className={
                            page === "settings" ? "nav-item active" : "nav-item"
                        }
                        onClick={() => setPage("settings")}
                    >
                        <Settings2 size={18} />
                        <span>Settings</span>
                    </button>
                </nav>
                <div className="sidebar-library">
                    <label className="search-field">
                        <Search size={15} />
                        <input
                            aria-label="Filter sidebar labels"
                            placeholder="Find label"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                        />
                    </label>
                    <div className="sidebar-library-title">
                        Saved labels{" "}
                        <button
                            className="icon-button"
                            aria-label="New label"
                            onClick={newLabel}
                        >
                            <Plus size={16} />
                        </button>
                    </div>
                    <div className="sidebar-label-list">
                        {shownLabels.map((label) => (
                            <button
                                key={label.id}
                                className={`sidebar-label ${activeId === label.id ? "selected" : ""}`}
                                onClick={() => open(label)}
                            >
                                <Tag size={15} />
                                <span>{label.name}</span>
                            </button>
                        ))}
                    </div>
                </div>
                <div className="sidebar-bottom">
                    <div className="device-mini">
                        <span className="device-icon">
                            <Printer size={21} />
                        </span>
                        <div>
                            <strong>Brother {config?.model ?? "QL-800"}</strong>
                            <small>
                                <i
                                    className={`dot ${status?.state ?? "unknown"}`}
                                />
                                {status
                                    ? statusNames[status.state]
                                    : "Connecting…"}
                            </small>
                        </div>
                    </div>
                    <a href="/labeldesigner/" target="_blank" rel="noreferrer">
                        Advanced editor <ArrowUpRight size={14} />
                    </a>
                </div>
            </aside>
            <main className="main">
                <header className="topbar">
                    <h1 className="document-title">
                        {page === "editor"
                            ? activeName
                            : page === "library"
                              ? "Labels"
                              : page === "settings"
                                ? "Settings"
                                : "Printer"}
                    </h1>
                    <div className="topbar-actions">
                        {page === "library" && (
                            <button
                                className="button subtle"
                                onClick={newLabel}
                            >
                                <Plus size={16} />
                                New label
                            </button>
                        )}
                        {page === "editor" && (
                            <>
                                <button
                                    className="button subtle new-action"
                                    onClick={newLabel}
                                >
                                    <Plus size={16} />
                                    New
                                </button>
                                <button
                                    className="button subtle"
                                    disabled={!previewCurrent || busy}
                                    onClick={showSave}
                                >
                                    <Save size={16} />
                                    Save
                                </button>
                            </>
                        )}
                        <button
                            className={`status-pill ${status?.state ?? ""}`}
                            onClick={() => setPage("printer")}
                        >
                            <i
                                className={`dot ${status?.state ?? "unknown"}`}
                            />
                            {status ? statusNames[status.state] : "Connecting…"}
                        </button>
                    </div>
                </header>
                <div className="workspace">
                    {notice && (
                        <div
                            className={`notice ${notice.error ? "error" : ""}`}
                            role={notice.error ? "alert" : "status"}
                        >
                            {notice.error ? (
                                <CircleHelp size={17} />
                            ) : (
                                <Check size={17} />
                            )}
                            <span>{notice.text}</span>
                            <button
                                className="icon-button"
                                aria-label="Dismiss message"
                                onClick={() => setNotice(null)}
                            >
                                <X size={16} />
                            </button>
                        </div>
                    )}
                    {startupError && (
                        <div className="notice error" role="alert">
                            {startupError}
                            <button onClick={() => window.location.reload()}>
                                Retry
                            </button>
                        </div>
                    )}
                    {!config || !draft ? (
                        <div className="loading">
                            <LoaderCircle className="spin" /> Loading your
                            workspace…
                        </div>
                    ) : (
                        <>
                            {page === "editor" && (
                                <>
                                    <div className="editor-grid">
                                        <section className="editor-panel panel">
                                            <div
                                                className="content-tabs"
                                                role="group"
                                                aria-label="Label content type"
                                            >
                                                <button
                                                    aria-pressed={
                                                        draft.content.kind ===
                                                        "text"
                                                    }
                                                    onClick={() =>
                                                        changeKind("text")
                                                    }
                                                >
                                                    <Type size={18} />
                                                    Text
                                                </button>
                                                <button
                                                    aria-pressed={
                                                        draft.content.kind ===
                                                        "qr"
                                                    }
                                                    onClick={() =>
                                                        changeKind("qr")
                                                    }
                                                >
                                                    <QrCode size={18} />
                                                    QR code
                                                </button>
                                                <button
                                                    aria-pressed={
                                                        draft.content.kind ===
                                                        "image"
                                                    }
                                                    onClick={() =>
                                                        changeKind("image")
                                                    }
                                                >
                                                    <ImagePlus size={18} />
                                                    Image
                                                </button>
                                            </div>
                                            <div className="form-body">
                                                {draft.content.kind ===
                                                    "text" && (
                                                    <RichTextEditor
                                                        value={draft.content}
                                                        onChange={content}
                                                        font={draft.font}
                                                        size={draft.fontSize}
                                                        fonts={config.fonts}
                                                    />
                                                )}
                                                {draft.content.kind ===
                                                    "qr" && (
                                                    <>
                                                        <label className="field">
                                                            Link or QR content
                                                            <textarea
                                                                aria-label="QR content"
                                                                value={
                                                                    draft
                                                                        .content
                                                                        .code
                                                                }
                                                                placeholder="https://example.com"
                                                                maxLength={2000}
                                                                onChange={(
                                                                    event,
                                                                ) => {
                                                                    if (
                                                                        draft
                                                                            .content
                                                                            .kind ===
                                                                        "qr"
                                                                    )
                                                                        content(
                                                                            {
                                                                                ...draft.content,
                                                                                code: event
                                                                                    .target
                                                                                    .value,
                                                                            },
                                                                        );
                                                                }}
                                                                rows={3}
                                                            />
                                                        </label>
                                                        <label className="field">
                                                            Caption{" "}
                                                            <span className="optional">
                                                                optional
                                                            </span>
                                                            <input
                                                                value={
                                                                    draft
                                                                        .content
                                                                        .caption
                                                                }
                                                                placeholder="Scan for more"
                                                                onChange={(
                                                                    event,
                                                                ) => {
                                                                    if (
                                                                        draft
                                                                            .content
                                                                            .kind ===
                                                                        "qr"
                                                                    )
                                                                        content(
                                                                            {
                                                                                ...draft.content,
                                                                                caption:
                                                                                    event
                                                                                        .target
                                                                                        .value,
                                                                            },
                                                                        );
                                                                }}
                                                            />
                                                        </label>
                                                    </>
                                                )}
                                                {draft.content.kind ===
                                                    "image" && (
                                                    <>
                                                        <input
                                                            ref={uploadInput}
                                                            className="visually-hidden"
                                                            type="file"
                                                            accept="image/png,image/jpeg,application/pdf"
                                                            aria-label="Upload label image"
                                                            onChange={(event) =>
                                                                void upload(
                                                                    event.target
                                                                        .files?.[0],
                                                                )
                                                            }
                                                        />
                                                        <button
                                                            className="upload-area"
                                                            onClick={() =>
                                                                uploadInput.current?.click()
                                                            }
                                                        >
                                                            <ImagePlus
                                                                size={27}
                                                            />
                                                            <strong>
                                                                {draft.content
                                                                    .image
                                                                    ? draft
                                                                          .content
                                                                          .image
                                                                          .name
                                                                    : "Choose an image or PDF"}
                                                            </strong>
                                                            <span>
                                                                PNG, JPG, or the
                                                                first page of a
                                                                PDF · Up to 5 MB
                                                            </span>
                                                        </button>
                                                        <label className="field">
                                                            Caption{" "}
                                                            <span className="optional">
                                                                optional
                                                            </span>
                                                            <input
                                                                value={
                                                                    draft
                                                                        .content
                                                                        .caption
                                                                }
                                                                onChange={(
                                                                    event,
                                                                ) => {
                                                                    if (
                                                                        draft
                                                                            .content
                                                                            .kind ===
                                                                        "image"
                                                                    )
                                                                        content(
                                                                            {
                                                                                ...draft.content,
                                                                                caption:
                                                                                    event
                                                                                        .target
                                                                                        .value,
                                                                            },
                                                                        );
                                                                }}
                                                            />
                                                        </label>
                                                        <div className="two-fields">
                                                            <label className="field">
                                                                Image treatment
                                                                <select
                                                                    value={
                                                                        draft
                                                                            .content
                                                                            .mode
                                                                    }
                                                                    onChange={(
                                                                        event,
                                                                    ) => {
                                                                        if (
                                                                            draft
                                                                                .content
                                                                                .kind ===
                                                                                "image" &&
                                                                            (event
                                                                                .target
                                                                                .value ===
                                                                                "grayscale" ||
                                                                                event
                                                                                    .target
                                                                                    .value ===
                                                                                    "bw" ||
                                                                                event
                                                                                    .target
                                                                                    .value ===
                                                                                    "red")
                                                                        )
                                                                            content(
                                                                                {
                                                                                    ...draft.content,
                                                                                    mode: event
                                                                                        .target
                                                                                        .value,
                                                                                },
                                                                            );
                                                                    }}
                                                                >
                                                                    <option value="grayscale">
                                                                        Grayscale
                                                                        /
                                                                        dithering
                                                                    </option>
                                                                    <option value="bw">
                                                                        Black &
                                                                        white
                                                                    </option>
                                                                    {draft.sizeId ===
                                                                        "62red" && (
                                                                        <option value="red">
                                                                            Black
                                                                            &
                                                                            red
                                                                        </option>
                                                                    )}
                                                                </select>
                                                            </label>
                                                            <label className="check-field">
                                                                <input
                                                                    type="checkbox"
                                                                    checked={
                                                                        draft
                                                                            .content
                                                                            .fit
                                                                    }
                                                                    onChange={(
                                                                        event,
                                                                    ) => {
                                                                        if (
                                                                            draft
                                                                                .content
                                                                                .kind ===
                                                                            "image"
                                                                        )
                                                                            content(
                                                                                {
                                                                                    ...draft.content,
                                                                                    fit: event
                                                                                        .target
                                                                                        .checked,
                                                                                },
                                                                            );
                                                                    }}
                                                                />
                                                                Fit to label
                                                            </label>
                                                        </div>
                                                    </>
                                                )}
                                                <div className="section-divider" />
                                                {draft.content.kind !==
                                                    "text" && (
                                                    <div className="two-fields font-fields">
                                                        <label className="field">
                                                            Typeface
                                                            <select
                                                                value={
                                                                    draft.font
                                                                }
                                                                onChange={(
                                                                    event,
                                                                ) =>
                                                                    update({
                                                                        font: event
                                                                            .target
                                                                            .value,
                                                                    })
                                                                }
                                                            >
                                                                {config.fonts.map(
                                                                    (font) => (
                                                                        <option
                                                                            key={
                                                                                font.id
                                                                            }
                                                                            value={
                                                                                font.id
                                                                            }
                                                                        >
                                                                            {
                                                                                font.name
                                                                            }
                                                                        </option>
                                                                    ),
                                                                )}
                                                            </select>
                                                        </label>
                                                        <label className="field">
                                                            Size{" "}
                                                            <span className="optional">
                                                                px
                                                            </span>
                                                            <input
                                                                type="number"
                                                                min={8}
                                                                max={200}
                                                                value={
                                                                    draft.fontSize
                                                                }
                                                                onChange={(
                                                                    event,
                                                                ) =>
                                                                    update({
                                                                        fontSize:
                                                                            Number(
                                                                                event
                                                                                    .target
                                                                                    .value,
                                                                            ),
                                                                    })
                                                                }
                                                            />
                                                        </label>
                                                    </div>
                                                )}
                                                <div className="format-row">
                                                    <div
                                                        className="segmented"
                                                        aria-label="Text alignment"
                                                    >
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
                                                        ).map(
                                                            ({
                                                                value,
                                                                Icon,
                                                            }) => (
                                                                <button
                                                                    key={value}
                                                                    aria-label={`Align ${value}`}
                                                                    aria-pressed={
                                                                        draft.align ===
                                                                        value
                                                                    }
                                                                    onClick={() =>
                                                                        update({
                                                                            align: value,
                                                                        })
                                                                    }
                                                                >
                                                                    <Icon
                                                                        size={
                                                                            18
                                                                        }
                                                                    />
                                                                </button>
                                                            ),
                                                        )}
                                                    </div>
                                                    <label className="color-choice">
                                                        <span>Ink</span>
                                                        <select
                                                            aria-label="Ink color"
                                                            value={draft.color}
                                                            onChange={(event) =>
                                                                update({
                                                                    color:
                                                                        event
                                                                            .target
                                                                            .value ===
                                                                        "red"
                                                                            ? "red"
                                                                            : "black",
                                                                })
                                                            }
                                                        >
                                                            <option value="black">
                                                                ● Black
                                                            </option>
                                                            {draft.sizeId ===
                                                                "62red" && (
                                                                <option value="red">
                                                                    ● Red
                                                                </option>
                                                            )}
                                                        </select>
                                                    </label>
                                                </div>
                                            </div>
                                        </section>
                                        <details
                                            className="layout-details panel"
                                            open={layoutOpen}
                                            onToggle={(event) =>
                                                setLayoutOpen(
                                                    event.currentTarget.open,
                                                )
                                            }
                                        >
                                            <summary>
                                                <Settings2 size={16} /> Label
                                                settings{" "}
                                                <ChevronRight size={16} />
                                            </summary>
                                            <div className="form-body">
                                                <label className="field">
                                                    Label roll
                                                    <select
                                                        value={draft.sizeId}
                                                        onChange={(event) =>
                                                            update({
                                                                sizeId: event
                                                                    .target
                                                                    .value,
                                                                color: "black",
                                                                highRes: false,
                                                                content:
                                                                    draft
                                                                        .content
                                                                        .kind ===
                                                                    "image"
                                                                        ? {
                                                                              ...draft.content,
                                                                              mode: "grayscale",
                                                                          }
                                                                        : draft.content,
                                                            })
                                                        }
                                                    >
                                                        {config.sizes.map(
                                                            (size) => (
                                                                <option
                                                                    key={
                                                                        size.id
                                                                    }
                                                                    value={
                                                                        size.id
                                                                    }
                                                                >
                                                                    {size.name}
                                                                </option>
                                                            ),
                                                        )}
                                                    </select>
                                                </label>
                                                <div className="detected-roll">
                                                    <span>
                                                        {status?.media
                                                            ? `Loaded: ${status.media}`
                                                            : "Roll not detected"}
                                                    </span>
                                                    {detectedRoll &&
                                                        detectedRoll !==
                                                            draft.sizeId && (
                                                            <button
                                                                className="button subtle"
                                                                type="button"
                                                                onClick={() =>
                                                                    update({
                                                                        sizeId: detectedRoll,
                                                                        highRes: false,
                                                                        color: "black",
                                                                        content:
                                                                            draft
                                                                                .content
                                                                                .kind ===
                                                                            "image"
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
                                                            value={
                                                                draft.orientation
                                                            }
                                                            onChange={(event) =>
                                                                update({
                                                                    orientation:
                                                                        event
                                                                            .target
                                                                            .value ===
                                                                        "rotated"
                                                                            ? "rotated"
                                                                            : "standard",
                                                                })
                                                            }
                                                        >
                                                            <option value="standard">
                                                                Standard
                                                            </option>
                                                            <option value="rotated">
                                                                Rotated 90°
                                                            </option>
                                                        </select>
                                                    </label>
                                                    <label className="field">
                                                        Margin{" "}
                                                        <span className="optional">
                                                            px
                                                        </span>
                                                        <input
                                                            type="number"
                                                            min={0}
                                                            max={100}
                                                            value={draft.margin}
                                                            onChange={(event) =>
                                                                update({
                                                                    margin: Number(
                                                                        event
                                                                            .target
                                                                            .value,
                                                                    ),
                                                                })
                                                            }
                                                        />
                                                    </label>
                                                </div>
                                                <label className="check-field">
                                                    <input
                                                        type="checkbox"
                                                        disabled={
                                                            draft.sizeId ===
                                                            "62red"
                                                        }
                                                        checked={draft.highRes}
                                                        onChange={(event) =>
                                                            update({
                                                                highRes:
                                                                    event.target
                                                                        .checked,
                                                            })
                                                        }
                                                    />
                                                    High resolution{" "}
                                                    <span className="muted">
                                                        300 × 600 dpi
                                                    </span>
                                                </label>
                                                <label className="field">
                                                    Cut
                                                    <select
                                                        value={cut}
                                                        onChange={(event) =>
                                                            setCut(
                                                                event.target
                                                                    .value ===
                                                                    "end"
                                                                    ? "end"
                                                                    : "each",
                                                            )
                                                        }
                                                    >
                                                        <option value="each">
                                                            After each label
                                                        </option>
                                                        <option value="end">
                                                            After the last label
                                                        </option>
                                                    </select>
                                                </label>
                                            </div>
                                        </details>
                                        <div className="preview-column">
                                            <section className="preview-panel panel">
                                                <div className="panel-heading">
                                                    <div>
                                                        <h2>Preview</h2>
                                                    </div>
                                                    <span className="preview-tag">
                                                        <i
                                                            className={`dot ${preview.kind === "ready" ? "ready" : "unknown"}`}
                                                        />
                                                        {preview.kind ===
                                                        "pending"
                                                            ? "Updating"
                                                            : preview.kind ===
                                                                "ready"
                                                              ? "Ready"
                                                              : "Preview"}
                                                    </span>
                                                </div>
                                                <div className="preview-stage">
                                                    <span className="dimension">
                                                        {sizeName}
                                                    </span>
                                                    <div className="label-artwork">
                                                        {preview.kind ===
                                                        "ready" ? (
                                                            <img
                                                                src={
                                                                    preview.url
                                                                }
                                                                alt="Rendered label preview"
                                                            />
                                                        ) : preview.kind ===
                                                          "pending" ? (
                                                            <div className="preview-placeholder">
                                                                <LoaderCircle
                                                                    className="spin"
                                                                    size={24}
                                                                />
                                                                <span>
                                                                    Rendering
                                                                    your label…
                                                                </span>
                                                            </div>
                                                        ) : preview.kind ===
                                                          "error" ? (
                                                            <div
                                                                className="preview-placeholder preview-error"
                                                                role="alert"
                                                            >
                                                                <CircleHelp
                                                                    size={25}
                                                                />
                                                                <strong>
                                                                    Preview
                                                                    unavailable
                                                                </strong>
                                                                <span>
                                                                    {
                                                                        preview.message
                                                                    }
                                                                </span>
                                                            </div>
                                                        ) : (
                                                            <div className="preview-placeholder">
                                                                <Tag
                                                                    size={26}
                                                                />
                                                                <span>
                                                                    Enter
                                                                    content to
                                                                    preview
                                                                </span>
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                                <div className="preview-toolbar">
                                                    <span>
                                                        <RotateCw size={14} />
                                                        {draft.highRes
                                                            ? "300 × 600"
                                                            : "300 × 300"}{" "}
                                                        dpi
                                                    </span>
                                                    <span>
                                                        Preview scaled to fit
                                                    </span>
                                                    {preview.kind ===
                                                        "ready" && (
                                                        <a
                                                            href={preview.url}
                                                            download={`${name || "label"}.png`}
                                                            title="Download preview"
                                                            aria-label="Download preview"
                                                        >
                                                            <ArrowDownToLine
                                                                size={17}
                                                            />
                                                        </a>
                                                    )}
                                                </div>
                                            </section>
                                            <section className="print-panel panel">
                                                {mismatchedPaper && (
                                                    <div
                                                        className="paper-warning"
                                                        role="alert"
                                                    >
                                                        <AlertTriangle
                                                            size={18}
                                                            aria-hidden="true"
                                                        />
                                                        <div>
                                                            <strong>
                                                                Paper mismatch
                                                            </strong>
                                                            <span>
                                                                Needs {sizeName}
                                                                . Loaded:{" "}
                                                                {status?.media}.
                                                            </span>
                                                        </div>
                                                    </div>
                                                )}
                                                <div className="print-options">
                                                    <label className="field">
                                                        Copies
                                                        <input
                                                            aria-label="Copies"
                                                            type="number"
                                                            min={1}
                                                            max={100}
                                                            value={copies}
                                                            onChange={(event) =>
                                                                setCopies(
                                                                    Number(
                                                                        event
                                                                            .target
                                                                            .value,
                                                                    ),
                                                                )
                                                            }
                                                        />
                                                    </label>
                                                </div>
                                                <button
                                                    className="button primary print-button"
                                                    aria-keyshortcuts="Meta+Enter Control+Enter"
                                                    title="Print (⌘/Ctrl + Enter)"
                                                    disabled={
                                                        !canPrint ||
                                                        mismatchedPaper ||
                                                        !previewCurrent ||
                                                        busy ||
                                                        copies < 1 ||
                                                        copies > 100 ||
                                                        !Number.isInteger(
                                                            copies,
                                                        )
                                                    }
                                                    onClick={() =>
                                                        void print(
                                                            draft,
                                                            copies,
                                                        )
                                                    }
                                                >
                                                    {busy ? (
                                                        <LoaderCircle
                                                            className="spin"
                                                            size={18}
                                                        />
                                                    ) : (
                                                        <Printer size={18} />
                                                    )}
                                                    {simulated
                                                        ? "Test print"
                                                        : `Print ${copies === 1 ? "label" : `${copies} labels`}`}
                                                </button>
                                                <p className="print-note">
                                                    {simulated
                                                        ? "Simulator · no paper used"
                                                        : !canPrint
                                                          ? status?.message ||
                                                            "Checking the printer…"
                                                          : mismatchedPaper
                                                            ? "Change the roll or label settings"
                                                            : "Ready"}
                                                </p>
                                            </section>
                                        </div>
                                    </div>
                                </>
                            )}
                            {page === "library" && (
                                <LibraryView
                                    labels={labels}
                                    sizes={config.sizes}
                                    search={search}
                                    onSearchChange={setSearch}
                                    onNewLabel={newLabel}
                                    simulated={simulated ?? false}
                                    canPrint={canPrint}
                                    status={simulated ? null : status}
                                    busy={busy}
                                    onPrint={(target) => void print(target)}
                                    onPreview={api.preview}
                                    onOpen={open}
                                    onDuplicate={(label) => {
                                        open(label);
                                        setActiveId(null);
                                        setName(`${label.name} copy`);
                                    }}
                                    onDelete={(label) => {
                                        setDeleteTarget(label);
                                        deleteDialog.current?.showModal();
                                    }}
                                />
                            )}
                            {page === "settings" && (
                                <SettingsView
                                    config={config}
                                    status={status}
                                    onConfig={setConfig}
                                />
                            )}
                            {page === "printer" && (
                                <PrinterView
                                    model={config.model}
                                    status={status}
                                    simulated={simulated ?? false}
                                    statusNames={statusNames}
                                    onCheckConnection={() => {
                                        api.status()
                                            .then(setStatus)
                                            .catch((error) =>
                                                notify(
                                                    errorMessage(error),
                                                    true,
                                                ),
                                            );
                                    }}
                                />
                            )}
                        </>
                    )}
                </div>
            </main>
            <dialog
                ref={redDialog}
                className="dialog"
                onCancel={() => setRedPrint(null)}
            >
                <div className="dialog-heading">
                    <h2>Black/red tape loaded?</h2>
                    <button
                        className="icon-button"
                        aria-label="Cancel red print"
                        onClick={() => {
                            redDialog.current?.close();
                            setRedPrint(null);
                        }}
                    >
                        <X size={20} />
                    </button>
                </div>
                <p>
                    This label is saved for 62 mm black/red tape. The printer
                    has not confirmed the tape color.
                </p>
                <button
                    className="button primary"
                    disabled={!redPrint || busy}
                    onClick={() => {
                        const job = redPrint;
                        redDialog.current?.close();
                        setRedPrint(null);
                        if (job) void print(job.draft, job.copies, true);
                    }}
                >
                    Black/red tape is loaded · Print
                </button>
            </dialog>
            <dialog ref={saveDialog} className="dialog">
                <form
                    onSubmit={(event) => {
                        event.preventDefault();
                        void save();
                    }}
                >
                    <div className="dialog-heading">
                        <h2>{activeId ? "Save label" : "Save label"}</h2>
                        <button
                            type="button"
                            className="icon-button"
                            aria-label="Close save dialog"
                            onClick={() => saveDialog.current?.close()}
                        >
                            <X size={20} />
                        </button>
                    </div>

                    <label className="field">
                        Label name
                        <input
                            autoFocus
                            required
                            maxLength={100}
                            value={name}
                            onChange={(event) => setName(event.target.value)}
                            placeholder="e.g. Coffee jars"
                        />
                    </label>
                    {notice?.error && (
                        <p className="inline-error" role="alert">
                            {notice.text}
                        </p>
                    )}
                    <button
                        className="button primary"
                        disabled={busy || !name.trim()}
                    >
                        {busy ? (
                            <LoaderCircle className="spin" size={17} />
                        ) : (
                            <FolderOpen size={17} />
                        )}
                        Save label
                    </button>
                </form>
            </dialog>
            <dialog ref={deleteDialog} className="dialog">
                <div className="dialog-heading">
                    <h2>Delete this label?</h2>
                    <button
                        className="icon-button"
                        aria-label="Cancel deletion"
                        onClick={() => deleteDialog.current?.close()}
                    >
                        <X size={20} />
                    </button>
                </div>
                <p>“{deleteTarget?.name}” will be removed from your library.</p>
                <button
                    className="button destructive"
                    disabled={busy}
                    onClick={() => void remove()}
                >
                    <Trash2 size={16} />
                    Delete label
                </button>
            </dialog>
        </div>
    );
}
