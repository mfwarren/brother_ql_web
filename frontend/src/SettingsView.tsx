import { useEffect, useState } from "react";
import { Download, LoaderCircle, Save, Search, Upload } from "lucide-react";
import {
    api,
    defaultsSchema,
    errorMessage,
    type Config,
    type Defaults,
    type FontFamily,
    type PrinterStatus,
} from "./api";

type Props = {
    config: Config;
    status: PrinterStatus | null;
    onConfig: (config: Config) => void;
};
export default function SettingsView({ config, status, onConfig }: Props) {
    const [values, setValues] = useState<Defaults>(config.defaults);
    const [families, setFamilies] = useState<FontFamily[]>([]);
    const [query, setQuery] = useState("");
    const [limit, setLimit] = useState(30);
    const [busy, setBusy] = useState("");
    const [message, setMessage] = useState("");
    const [error, setError] = useState("");
    const [catalogError, setCatalogError] = useState("");
    function loadCatalog() {
        setCatalogError("");
        api.fontCatalog()
            .then(setFamilies)
            .catch((e) => setCatalogError(errorMessage(e)));
    }
    useEffect(loadCatalog, []);
    function update(patch: Partial<Defaults>) {
        setValues((value) => ({ ...value, ...patch }));
        setMessage("");
    }
    async function save() {
        setBusy("save");
        setError("");
        setMessage("");
        try {
            const saved = await api.settings(values);
            onConfig({
                ...config,
                defaults: saved,
                defaultFont: saved.font,
                defaultSize: saved.sizeId,
            });
            setMessage(
                "Defaults saved. They apply to new labels on every device.",
            );
        } catch (e) {
            setError(errorMessage(e));
        } finally {
            setBusy("");
        }
    }
    async function install(family: FontFamily | File) {
        setBusy(family instanceof File ? "upload" : family.id);
        setError("");
        setMessage("");
        try {
            const result =
                family instanceof File
                    ? await api.uploadFont(family)
                    : await api.installFont(family.id);
            onConfig({ ...config, fonts: result.fonts });
            update({ font: result.font });
            if (!(family instanceof File))
                setFamilies((all) =>
                    all.map((f) =>
                        f.id === family.id ? { ...f, installed: true } : f,
                    ),
                );
            setMessage(
                "Font installed locally and selected. Save defaults to use it for new labels.",
            );
        } catch (e) {
            setError(errorMessage(e));
        } finally {
            setBusy("");
        }
    }
    const found = families.filter((f) =>
        f.name.toLowerCase().includes(query.toLowerCase()),
    );
    const matches = status?.matchingSizes ?? [];
    const detected = matches.length === 1 ? matches[0] : undefined;
    return (
        <div className="settings-grid">
            <section className="panel settings-panel">
                <div className="section-heading">
                    <h2>New label defaults</h2>
                    <span className="muted">Shared by all devices</span>
                </div>
                <form
                    onSubmit={(e) => {
                        e.preventDefault();
                        void save();
                    }}
                >
                    <fieldset disabled={!!busy} className="settings-fields">
                        <label className="field">
                            Default typeface
                            <select
                                value={values.font}
                                onChange={(e) =>
                                    update({ font: e.target.value })
                                }
                            >
                                {config.fonts.map((font) => (
                                    <option key={font.id} value={font.id}>
                                        {font.name}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <div className="settings-pair">
                            <label className="field">
                                Text size (px)
                                <input
                                    type="number"
                                    min="8"
                                    max="200"
                                    required
                                    value={values.fontSize}
                                    onChange={(e) =>
                                        update({
                                            fontSize: e.target.valueAsNumber,
                                        })
                                    }
                                />
                            </label>
                            <label className="field">
                                Margins (px)
                                <input
                                    type="number"
                                    min="0"
                                    max="100"
                                    required
                                    value={values.margin}
                                    onChange={(e) =>
                                        update({
                                            margin: e.target.valueAsNumber,
                                        })
                                    }
                                />
                            </label>
                        </div>
                        <label className="field">
                            Default orientation
                            <select
                                value={values.orientation}
                                onChange={(e) =>
                                    update({
                                        orientation:
                                            defaultsSchema.shape.orientation.parse(
                                                e.target.value,
                                            ),
                                    })
                                }
                            >
                                <option value="standard">Standard</option>
                                <option value="rotated">Rotated 90°</option>
                            </select>
                        </label>
                        <label className="field">
                            Fallback label roll
                            <select
                                value={values.sizeId}
                                onChange={(e) =>
                                    update({ sizeId: e.target.value })
                                }
                            >
                                {config.sizes.map((size) => (
                                    <option key={size.id} value={size.id}>
                                        {size.name}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label className="check-field">
                            <input
                                type="checkbox"
                                checked={values.autoDetectRoll}
                                onChange={(event) =>
                                    update({
                                        autoDetectRoll: event.target.checked,
                                    })
                                }
                            />
                            Follow loaded roll for new labels
                        </label>
                        <div className="detected-roll">
                            <span>
                                Loaded: {status?.media ?? "Not detected"}
                            </span>
                            {detected && (
                                <button
                                    type="button"
                                    className="button subtle"
                                    onClick={() => update({ sizeId: detected })}
                                >
                                    Use detected roll
                                </button>
                            )}
                        </div>
                        {matches.length > 1 && (
                            <p className="small muted">
                                Color not confirmed. Choose black or black/red
                                in the editor.
                            </p>
                        )}
                        <button className="button primary" type="submit">
                            <Save size={16} />
                            Save defaults
                        </button>
                    </fieldset>
                </form>
                <p className="small muted">
                    Detected rolls update new labels automatically. Saved labels
                    and manual roll choices stay fixed. The fallback is used
                    when detection is unavailable.
                </p>
                {message && (
                    <p className="settings-message" role="status">
                        {message}
                    </p>
                )}
                {error && (
                    <p className="inline-error" role="alert">
                        {error}
                    </p>
                )}
            </section>
            <section className="panel settings-panel font-settings">
                <div className="section-heading">
                    <h2>Fonts</h2>
                    <label className="button subtle font-upload">
                        <Upload size={16} />
                        Upload font
                        <input
                            type="file"
                            accept=".ttf,.otf"
                            aria-label="Upload font"
                            disabled={!!busy}
                            onChange={(e) => {
                                const file = e.target.files?.[0];
                                if (file) void install(file);
                                e.target.value = "";
                            }}
                        />
                    </label>
                </div>
                <p className="small muted">
                    Search Google Fonts, then install a family’s regular face.
                    Fonts stay on this printer server for offline use. You can
                    also upload a TTF or OTF, up to 8 MB.
                </p>
                <label className="search-field">
                    <Search size={16} />
                    <input
                        aria-label="Search Google Fonts"
                        placeholder="Search Google Fonts"
                        value={query}
                        onChange={(e) => {
                            setQuery(e.target.value);
                            setLimit(30);
                        }}
                    />
                </label>
                <span className="small muted">
                    {found.length.toLocaleString()} families
                </span>
                {catalogError && (
                    <div role="alert">
                        {catalogError}{" "}
                        <button className="button subtle" onClick={loadCatalog}>
                            Retry
                        </button>
                    </div>
                )}
                <div className="font-catalog">
                    {found.slice(0, limit).map((family) => (
                        <div className="font-row" key={family.id}>
                            <span>{family.name}</span>
                            <button
                                className="button subtle"
                                disabled={!!busy || family.installed}
                                onClick={() => void install(family)}
                                aria-label={`Install ${family.name}`}
                            >
                                {busy === family.id ? (
                                    <LoaderCircle size={15} className="spin" />
                                ) : (
                                    !family.installed && <Download size={15} />
                                )}
                                {family.installed
                                    ? "Installed"
                                    : busy === family.id
                                      ? "Installing…"
                                      : "Install"}
                            </button>
                        </div>
                    ))}
                    {found.length > limit && (
                        <button
                            className="button subtle"
                            onClick={() => setLimit(limit + 30)}
                        >
                            Show more
                        </button>
                    )}
                </div>
            </section>
            <section className="panel settings-panel density-settings">
                <h2>Print darkness</h2>
                <p>
                    The QL-800 has black and red density settings from −6 to +6
                    in Brother’s Printer Setting Tool. This app’s Linux driver
                    cannot change them yet.
                </p>
                <p className="small muted">
                    A heavier typeface can thicken text, but it does not change
                    the printer’s heat or density setting.
                </p>
                <a
                    href="https://support.brother.ca/app/answers/detail/a_id/159086/kw/guide"
                    target="_blank"
                    rel="noreferrer"
                >
                    Brother’s density settings ↗
                </a>
            </section>
        </div>
    );
}
