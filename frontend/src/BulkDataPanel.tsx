import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import { api, draftSchema, errorMessage, type Draft, type Config } from "./api";

const remoteImageSchema = z.object({
    name: z.string(),
    mime: z.string(),
    base64: z.string(),
});
const preparedSchema = z.object({
    headers: z.array(z.string()),
    timestamp: z.string(),
    jobId: z.string(),
    rows: z.array(
        z.discriminatedUnion("kind", [
            z.object({
                kind: z.literal("ready"),
                row: z.number(),
                line: z.number(),
                draft: draftSchema,
            }),
            z.object({
                kind: z.literal("error"),
                row: z.number(),
                line: z.number(),
                message: z.string(),
            }),
        ]),
    ),
});
type Row = { row: number; line: number } & (
    | { kind: "ready"; draft: Draft; url: string }
    | { kind: "error"; message: string }
);
async function post(path: string, body: unknown) {
    const response = await fetch("/studio/api/bulk/" + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const value: unknown = await response.json();
    if (!response.ok)
        throw new Error(z.object({ message: z.string() }).parse(value).message);
    return value;
}
export default function BulkDataPanel({
    template,
    onTemplateChange,
    onPreview,
    onBusy,
    config,
    cut,
}: {
    template: Draft;
    onTemplateChange: (draft: Draft) => void;
    onPreview: (selection: { draft: Draft; row: number } | null) => void;
    onBusy: (busy: boolean) => void;
    config: Config;
    cut: "each" | "end";
}) {
    const [activeRow, setActiveRow] = useState<number | null>(null);
    const [csv, setCsv] = useState("");
    const [filename, setFilename] = useState("");
    const [count, setCount] = useState(1);
    const [rows, setRows] = useState<Row[]>([]);
    const [selected, setSelected] = useState<Set<number>>(new Set());
    const [phase, setPhase] = useState<
        "edit" | "checking" | "review" | "printing" | "submitted"
    >("edit");
    const [message, setMessage] = useState("");
    const [progress, setProgress] = useState(0);
    const [total, setTotal] = useState(0);
    const [timestamp, setTimestamp] = useState("");
    const [errorsOnly, setErrorsOnly] = useState(false);
    const [headers, setHeaders] = useState<string[]>([]);
    const [jobId, setJobId] = useState("");
    const [confirm, setConfirm] = useState(false);
    const controller = useRef<AbortController | null>(null);
    const urls = useRef<string[]>([]);
    useEffect(
        () => () => {
            controller.current?.abort();
            urls.current.forEach(URL.revokeObjectURL);
        },
        [],
    );
    function clear() {
        controller.current?.abort();
        urls.current.forEach(URL.revokeObjectURL);
        urls.current = [];
        onPreview(null);
        setActiveRow(null);
        setHeaders([]);
        setTimestamp("");
        setRows([]);
        setSelected(new Set());
        setPhase("edit");
        setMessage("");
        setConfirm(false);
    }
    async function upload(file?: File) {
        if (!file) return;
        clear();
        setCsv("");
        setFilename("");
        if (file.size > 1_000_000) {
            setMessage("Choose a UTF-8 CSV smaller than 1 MB.");
            return;
        }
        try {
            const text = new TextDecoder("utf-8", { fatal: true }).decode(
                await file.arrayBuffer(),
            );
            if (!text.trim()) throw new Error("empty");
            setCsv(text);
            setFilename(file.name);
        } catch {
            setMessage(
                "Choose a nonempty UTF-8 CSV. Export it as CSV UTF-8 and upload it again.",
            );
        }
    }
    async function check() {
        clear();
        const abort = new AbortController();
        controller.current = abort;
        setPhase("checking");
        setProgress(0);
        try {
            const prepared = preparedSchema.parse(
                await post("prepare", {
                    template,
                    csv,
                    count,
                    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                }),
            );
            if (abort.signal.aborted) return;
            setTotal(prepared.rows.length);
            setHeaders(prepared.headers);
            setTimestamp(prepared.timestamp);
            const results: Row[] = [];
            const imageCache = new Map<
                string,
                z.infer<typeof remoteImageSchema>
            >();
            for (const row of prepared.rows) {
                if (abort.signal.aborted) return;
                if (row.kind === "error") results.push(row);
                else {
                    try {
                        let resolved = row.draft;
                        if (
                            resolved.content.kind === "image" &&
                            resolved.content.imageUrl
                        ) {
                            const url = resolved.content.imageUrl;
                            const image =
                                imageCache.get(url) ??
                                remoteImageSchema.parse(
                                    await post("image", { url }),
                                );
                            imageCache.set(url, image);
                            if (abort.signal.aborted) return;
                            resolved = {
                                ...resolved,
                                content: {
                                    ...resolved.content,
                                    image,
                                    imageUrl: undefined,
                                },
                            };
                        }
                        const blob = await api.preview(resolved, abort.signal);
                        if (abort.signal.aborted) return;
                        const url = URL.createObjectURL(blob);
                        urls.current.push(url);
                        results.push({ ...row, draft: resolved, url });
                    } catch (error) {
                        if (abort.signal.aborted) return;
                        results.push({
                            kind: "error",
                            row: row.row,
                            line: row.line,
                            message: errorMessage(error),
                        });
                    }
                }
                setRows([...results]);
                setProgress(results.length);
            }
            setSelected(
                new Set(
                    results
                        .filter((row) => row.kind === "ready")
                        .map((row) => row.row),
                ),
            );
            const first = results.find((row) => row.kind === "ready");
            if (first) selectPreview(first);
            setJobId(prepared.jobId);
            setPhase("review");
        } catch (error) {
            if (!abort.signal.aborted) {
                setMessage(errorMessage(error));
                setPhase("edit");
            }
        }
    }
    async function print() {
        setConfirm(false);
        setPhase("printing");
        setMessage("");
        try {
            const drafts = rows.flatMap((row) =>
                row.kind === "ready" && selected.has(row.row)
                    ? [row.draft]
                    : [],
            );
            const result = z
                .object({ message: z.string() })
                .parse(await post("print", { drafts, jobId, cut }));
            setMessage(result.message);
        } catch (error) {
            setMessage(
                errorMessage(error) +
                    " Do not retry blindly; check what printed first.",
            );
        }
        setPhase("submitted");
    }
    const errors = rows.filter((row) => row.kind === "error").length;
    const locked = phase === "checking" || phase === "printing";
    useEffect(() => {
        clear();
    }, [template]);
    useEffect(() => {
        onBusy(phase === "printing");
        return () => onBusy(false);
    }, [phase, onBusy]);
    function selectPreview(row: Row) {
        setActiveRow(row.row);
        onPreview(
            row.kind === "ready" ? { draft: row.draft, row: row.row } : null,
        );
    }
    function exportTemplate() {
        const url = URL.createObjectURL(
            new Blob([JSON.stringify(template, null, 2)], {
                type: "application/json",
            }),
        );
        const a = document.createElement("a");
        a.href = url;
        a.download = "label-template.json";
        a.click();
        URL.revokeObjectURL(url);
    }
    async function importTemplate(file?: File) {
        if (!file) return;
        clear();
        try {
            onTemplateChange(draftSchema.parse(JSON.parse(await file.text())));
        } catch {
            setMessage("That file is not a Label Studio template.");
        }
    }
    return (
        <section className="bulk-workspace">
            <div className="bulk-setup">
                <section className="panel bulk-panel">
                    <h2>Data fields</h2>
                    <p>
                        Edit your label above using the usual Text, QR, Barcode,
                        and Image controls. Use <code>{"{{Product}}"}</code> in
                        any text or caption. In Image, use a CSV field such as{" "}
                        <code>{"{{Photo}}"}</code> as its URL.
                    </p>
                    <fieldset disabled={locked} inert={locked}>
                        <p className="bulk-tokens">
                            <code>{"{{@today}}"}</code> YYYY-MM-DD ·{" "}
                            <code>{"{{@time}}"}</code> HH:mm ·{" "}
                            <code>{"{{@row}}"}</code> label number ·{" "}
                            <code>{"{{@total}}"}</code> row count
                        </p>
                        <div className="bulk-actions">
                            <button className="button" onClick={exportTemplate}>
                                Download template
                            </button>
                            <label className="button">
                                Load template
                                <input
                                    type="file"
                                    accept=".json"
                                    hidden
                                    onChange={(e) => {
                                        void importTemplate(
                                            e.target.files?.[0],
                                        );
                                        e.target.value = "";
                                    }}
                                />
                            </label>
                        </div>
                    </fieldset>
                </section>
                <section className="panel bulk-panel">
                    <h2>CSV data</h2>
                    <fieldset disabled={locked} inert={locked}>
                        <label className="field">
                            Upload or replace CSV
                            <input
                                type="file"
                                accept=".csv,text/csv"
                                onChange={(event) => {
                                    void upload(event.target.files?.[0]);
                                    event.target.value = "";
                                }}
                            />
                        </label>
                        {filename && <p>{filename}</p>}
                        <label className="field">
                            Or paste CSV
                            <textarea
                                rows={5}
                                value={csv}
                                placeholder={
                                    "Product,SKU\nCoffee beans,COF-001\nGreen tea,TEA-002"
                                }
                                onChange={(event) => {
                                    clear();
                                    setCsv(event.target.value);
                                    setFilename("");
                                }}
                            />
                        </label>
                        {!csv && (
                            <label className="field">
                                Labels using built-ins only
                                <input
                                    type="number"
                                    min={1}
                                    max={100}
                                    value={count}
                                    onChange={(event) => {
                                        clear();
                                        setCount(event.target.valueAsNumber);
                                    }}
                                />
                            </label>
                        )}
                        <p>
                            One label per row, up to 100. Blank rows are
                            skipped. Quoted commas and multiline cells are
                            supported. Your CSV stays on this printer server.
                        </p>
                        <button
                            className="button primary"
                            onClick={() => void check()}
                        >
                            Check & preview every label
                        </button>
                    </fieldset>
                    {phase === "checking" && (
                        <div role="status">
                            Rendered {progress} of {total} labels…{" "}
                            <button className="button" onClick={clear}>
                                Cancel
                            </button>
                        </div>
                    )}
                </section>
            </div>
            {message && (
                <p role="status" className="bulk-message">
                    {message}
                </p>
            )}
            {headers.length > 0 && (
                <p>
                    CSV fields:{" "}
                    {headers.map((name) => (
                        <code key={name}>{"{{" + name + "}}"} </code>
                    ))}
                </p>
            )}
            {rows.length > 0 && (
                <>
                    <div className="bulk-actions">
                        <h2>Review {rows.length} labels</h2>
                        <span>
                            {errors} {errors === 1 ? "error" : "errors"} ·{" "}
                            {selected.size} selected
                        </span>
                        <label>
                            <input
                                type="checkbox"
                                checked={errorsOnly}
                                onChange={(event) =>
                                    setErrorsOnly(event.target.checked)
                                }
                            />{" "}
                            Errors only
                        </label>
                        <button
                            className="button"
                            disabled={phase !== "review"}
                            onClick={() => setSelected(new Set())}
                        >
                            Deselect all
                        </button>
                        <button
                            className="button"
                            disabled={phase !== "review"}
                            onClick={() =>
                                setSelected(
                                    new Set(
                                        rows
                                            .filter(
                                                (row) => row.kind === "ready",
                                            )
                                            .map((row) => row.row),
                                    ),
                                )
                            }
                        >
                            Select valid labels
                        </button>
                    </div>
                    <p>
                        Built-ins frozen at{" "}
                        {new Date(timestamp).toLocaleString()}. Errors identify
                        the label number and CSV line. Fix the CSV or template
                        and check again, or explicitly print only selected valid
                        labels.
                    </p>
                    <div className="bulk-gallery">
                        {rows
                            .filter(
                                (row) => !errorsOnly || row.kind === "error",
                            )
                            .map((row) => (
                                <article
                                    className={
                                        "panel bulk-card " +
                                        (row.kind === "error"
                                            ? "bulk-error"
                                            : "")
                                    }
                                    key={row.row}
                                >
                                    <header>
                                        <button
                                            className="button subtle"
                                            type="button"
                                            aria-pressed={activeRow === row.row}
                                            onClick={() => selectPreview(row)}
                                        >
                                            Preview {row.row}
                                        </button>
                                        {row.kind === "ready" && (
                                            <input
                                                aria-label={
                                                    "Select label " + row.row
                                                }
                                                type="checkbox"
                                                disabled={phase !== "review"}
                                                checked={selected.has(row.row)}
                                                onChange={(event) => {
                                                    const next = new Set(
                                                        selected,
                                                    );
                                                    if (event.target.checked)
                                                        next.add(row.row);
                                                    else next.delete(row.row);
                                                    setSelected(next);
                                                }}
                                            />
                                        )}{" "}
                                        Label {row.row}
                                        {csv && (
                                            <small>
                                                {" "}
                                                · CSV line {row.line}
                                            </small>
                                        )}
                                    </header>
                                    {row.kind === "ready" ? (
                                        <a
                                            href={row.url}
                                            target="_blank"
                                            rel="noreferrer"
                                            aria-label={
                                                "Inspect label " + row.row
                                            }
                                        >
                                            <img
                                                loading="lazy"
                                                src={row.url}
                                                alt={
                                                    "Label " +
                                                    row.row +
                                                    " preview"
                                                }
                                            />
                                        </a>
                                    ) : (
                                        <p role="alert">{row.message}</p>
                                    )}
                                </article>
                            ))}
                    </div>
                    <div className="bulk-actions bulk-bottom">
                        <button
                            className="button primary"
                            disabled={phase !== "review" || !selected.size}
                            onClick={() => setConfirm(true)}
                        >
                            {config.mode === "simulation"
                                ? "Test print"
                                : "Print"}{" "}
                            {selected.size} labels
                        </button>
                        {phase === "printing" && (
                            <span role="status">
                                Printing batch. Keep this page open…
                            </span>
                        )}
                    </div>
                </>
            )}
            {confirm && (
                <div className="modal-backdrop">
                    <section
                        className="panel bulk-panel"
                        role="dialog"
                        aria-modal="true"
                        aria-label="Confirm bulk print"
                    >
                        <h2>
                            {config.mode === "simulation" ? "Test" : "Print"}{" "}
                            {selected.size} labels?
                        </h2>
                        <p>
                            {rows.length - selected.size} labels will be
                            skipped.{" "}
                            {cut === "each"
                                ? "Each printed label will be cut."
                                : "The batch will be cut after its last label."}{" "}
                            The loaded roll will be checked before printing.
                        </p>
                        <div className="bulk-actions">
                            <button
                                className="button"
                                onClick={() => setConfirm(false)}
                            >
                                Cancel
                            </button>
                            <button
                                className="button primary"
                                onClick={() => void print()}
                            >
                                Confirm{" "}
                                {config.mode === "simulation"
                                    ? "test print"
                                    : "print"}
                            </button>
                        </div>
                    </section>
                </div>
            )}
        </section>
    );
}
