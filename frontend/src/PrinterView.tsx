import { ArrowUpRight, Printer, RotateCw, WifiOff } from "lucide-react";
import type { Config, PrinterStatus } from "./api";

type Props = {
    model: Config["model"];
    status: PrinterStatus | null;
    simulated: boolean;
    statusNames: Record<PrinterStatus["state"], string>;
    onCheckConnection: () => void;
};

export default function PrinterView({
    model,
    status,
    simulated,
    statusNames,
    onCheckConnection,
}: Props) {
    return (
        <>
            <div className="printer-grid">
                <section className="panel printer-detail">
                    <div className="large-printer">
                        <Printer size={64} strokeWidth={1.1} />
                    </div>
                    <h2>Brother {model}</h2>
                    <span className={"status-pill " + (status?.state ?? "")}>
                        <i className={"dot " + (status?.state ?? "unknown")} />
                        {status ? statusNames[status.state] : "Checking…"}
                    </span>
                    <p>{status?.message}</p>
                    <button
                        className="button subtle"
                        onClick={onCheckConnection}
                    >
                        <RotateCw size={16} />
                        Check connection
                    </button>
                    <dl>
                        <div>
                            <dt>Connection</dt>
                            <dd>
                                {simulated
                                    ? "Local simulator"
                                    : "Raspberry Pi / USB"}
                            </dd>
                        </div>
                        <div>
                            <dt>Loaded roll</dt>
                            <dd>{status?.media ?? "Not detected"}</dd>
                        </div>
                        <div>
                            <dt>Account</dt>
                            <dd>None required</dd>
                        </div>
                    </dl>
                </section>
                <div className="printer-notes">
                    <section className="panel help-panel">
                        <span className="help-icon">
                            <WifiOff size={23} />
                        </span>
                        <h2>Keep it ready to print</h2>
                        <p>
                            The QL-800 can switch itself off after being idle.
                            Brother’s documented fix is to disable Auto Power
                            Off.
                        </p>
                        <ol>
                            <li>
                                Connect the printer to a Mac or Windows computer
                                by USB.
                            </li>
                            <li>Open Brother’s Printer Setting Tool.</li>
                            <li>
                                Set <strong>Auto Power Off (AC/DC)</strong> to{" "}
                                <strong>None</strong> and apply.
                            </li>
                            <li>Reconnect it to the Pi.</li>
                        </ol>
                        <a
                            href="https://support.brother.com/g/b/faqend.aspx?c=us_ot&faqid=faqp00001613_001&lang=en&prod=lpql800eus"
                            target="_blank"
                            rel="noreferrer"
                        >
                            Brother’s instructions <ArrowUpRight size={15} />
                        </a>
                        <p className="small muted">
                            This app cannot wake a printer that has powered off,
                            or confirm its power-off setting.
                        </p>
                    </section>
                    <section className="panel help-panel">
                        <h2>A note on black & red</h2>
                        <p>
                            Two-color printing needs the compatible 62 mm
                            black/red roll. High resolution is available for
                            black-only labels. Choose the matching roll in Label
                            & layout.
                        </p>
                    </section>
                </div>
            </div>
        </>
    );
}
