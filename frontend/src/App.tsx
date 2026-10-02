import {
    AlertTriangle,
    Check,
    ChevronRight,
    CircleHelp,
    FolderOpen,
    LayoutGrid,
    LoaderCircle,
    Plus,
    Printer,
    Save,
    Search,
    Settings2,
    Tag,
    Trash2,
    Type,
    X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
    api,
    errorMessage,
    labelTitle,
    paperMismatch,
    starter,
    verticalAlignment,
    type Config,
    type Content,
    type Draft,
    type PrinterStatus,
    type SavedLabel,
} from "./api";
import BulkDataPanel from "./BulkDataPanel";
import ContentPanel from "./editor/ContentPanel";
import PaperSettings from "./editor/PaperSettings";
import PreviewPanel from "./editor/PreviewPanel";
import LibraryView from "./LibraryView";
import PrinterView from "./PrinterView";
import SettingsView from "./SettingsView";
import useLabelPreview from "./useLabelPreview";

type Page = "editor" | "library" | "printer" | "settings";
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
    const [bulkEnabled, setBulkEnabled] = useState(false);
    const [bulkPreview, setBulkPreview] = useState<{
        draft: Draft;
        row: number;
    } | null>(null);
    const [bulkBusy, setBulkBusy] = useState(false);
    const previewDraft = bulkPreview?.draft ?? draft;
    const [page, setPage] = useState<Page>("editor");
    const [labels, setLabels] = useState<SavedLabel[]>([]);
    const [followLoadedRoll, setFollowLoadedRoll] = useState(true);
    const [activeId, setActiveId] = useState<string | null>(null);
    const [name, setName] = useState("");
    const [search, setSearch] = useState("");
    const { preview, displayedImage, displayedUrl } =
        useLabelPreview(previewDraft);
    const [showMargins, setShowMargins] = useState(false);
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
        update({
            content: next,
            ...(draft?.content.kind === "text" && next.kind === "text"
                ? { verticalAlign: verticalAlignment(draft) }
                : {}),
        });
    }
    function changeKind(kind: Content["kind"]) {
        if (!draft || draft.content.kind === kind) return;
        contentDrafts.current.set(draft.content.kind, draft.content);
        const saved = contentDrafts.current.get(kind);
        content(
            saved ??
                (kind === "text"
                    ? { kind, text: "" }
                    : kind === "barcode"
                      ? { kind, code: "", caption: "", format: "code128" }
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
            imageUrl: undefined,
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
                bulkEnabled ||
                bulkPreview !== null ||
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
                <a className="brand" href="/" aria-label="Label Studio home">
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
                            <div hidden={page !== "editor"}>
                                <div className="editor-grid">
                                    <div className="content-column">
                                        <div inert={bulkBusy}>
                                            <ContentPanel
                                                draft={draft}
                                                config={config}
                                                content={content}
                                                update={update}
                                                changeKind={changeKind}
                                                bulkEnabled={bulkEnabled}
                                                uploadInput={uploadInput}
                                                upload={upload}
                                            />
                                        </div>
                                        <section className="bulk-accordion panel">
                                            <h2>
                                                <button
                                                    type="button"
                                                    className="bulk-toggle"
                                                    disabled={bulkBusy}
                                                    aria-expanded={bulkEnabled}
                                                    aria-controls="bulk-data"
                                                    onClick={() =>
                                                        setBulkEnabled(
                                                            !bulkEnabled,
                                                        )
                                                    }
                                                >
                                                    <LayoutGrid size={16} />{" "}
                                                    Bulk labels{" "}
                                                    <ChevronRight size={16} />
                                                </button>
                                            </h2>
                                            <div
                                                id="bulk-data"
                                                hidden={!bulkEnabled}
                                            >
                                                <BulkDataPanel
                                                    template={draft}
                                                    config={config}
                                                    cut={cut}
                                                    onTemplateChange={setDraft}
                                                    onPreview={setBulkPreview}
                                                    onBusy={setBulkBusy}
                                                />
                                            </div>
                                        </section>
                                    </div>
                                    <div
                                        className="settings-column"
                                        inert={bulkBusy}
                                    >
                                        <PaperSettings
                                            draft={draft}
                                            config={config}
                                            update={update}
                                            layoutOpen={layoutOpen}
                                            setLayoutOpen={setLayoutOpen}
                                            status={status}
                                            detectedRoll={detectedRoll}
                                            showMargins={showMargins}
                                            setShowMargins={setShowMargins}
                                            cut={cut}
                                            setCut={setCut}
                                        />
                                    </div>
                                    <div
                                        className="preview-column"
                                        inert={bulkBusy}
                                    >
                                        <PreviewPanel
                                            name={name}
                                            draft={draft}
                                            config={config}
                                            bulkPreview={bulkPreview}
                                            preview={preview}
                                            displayedImage={displayedImage}
                                            displayedUrl={displayedUrl}
                                            sizeName={sizeName}
                                            showMargins={showMargins}
                                        />
                                        <section
                                            className="print-panel panel"
                                            hidden={
                                                bulkEnabled ||
                                                bulkPreview !== null
                                            }
                                        >
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
                                                            Needs {sizeName}.
                                                            Loaded:{" "}
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
                                                                    event.target
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
                                                    !Number.isInteger(copies)
                                                }
                                                onClick={() =>
                                                    void print(draft, copies)
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
                            </div>
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
