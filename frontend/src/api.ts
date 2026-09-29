import { z } from "zod";

const imageSchema = z.object({
    name: z.string(),
    mime: z.string(),
    base64: z.string(),
});
export const draftSchema = z.object({
    content: z.discriminatedUnion("kind", [
        z.object({ kind: z.literal("text"), text: z.string() }),
        z.object({
            kind: z.literal("qr"),
            code: z.string(),
            caption: z.string(),
        }),
        z.object({
            kind: z.literal("image"),
            image: imageSchema.nullable(),
            caption: z.string(),
            mode: z.enum(["grayscale", "bw", "red"]),
            fit: z.boolean(),
        }),
    ]),
    sizeId: z.string(),
    orientation: z.enum(["standard", "rotated"]),
    font: z.string(),
    fontSize: z.number(),
    align: z.enum(["left", "center", "right"]),
    color: z.enum(["black", "red"]),
    margin: z.number(),
    highRes: z.boolean(),
});
export type Draft = z.infer<typeof draftSchema>;
export type Content = Draft["content"];
export const defaultsSchema = draftSchema.pick({
    font: true,
    sizeId: true,
    orientation: true,
    margin: true,
    fontSize: true,
});
export type Defaults = z.infer<typeof defaultsSchema>;
const fontsSchema = z.array(z.object({ id: z.string(), name: z.string() }));
const catalogSchema = z.array(
    z.object({ id: z.string(), name: z.string(), installed: z.boolean() }),
);
export type FontFamily = z.infer<typeof catalogSchema>[number];
const configSchema = z.object({
    model: z.string(),
    fonts: fontsSchema,
    defaults: defaultsSchema,
    sizes: z.array(z.object({ id: z.string(), name: z.string() })),
    defaultFont: z.string(),
    defaultSize: z.string(),
    mode: z.enum(["simulation", "physical"]),
});
export type Config = z.infer<typeof configSchema>;
const statusSchema = z.object({
    state: z.enum([
        "simulation",
        "ready",
        "offline",
        "busy",
        "error",
        "unknown",
    ]),
    model: z.string(),
    message: z.string(),
    media: z.string().nullable(),
    matchingSizes: z.array(z.string()).default([]),
    mediaColor: z.enum(["black-red", "unknown"]).default("unknown"),
});
export type PrinterStatus = z.infer<typeof statusSchema>;
const savedSchema = z.object({
    id: z.string(),
    name: z.string(),
    updatedAt: z.string(),
    draft: draftSchema,
});
export type SavedLabel = z.infer<typeof savedSchema>;
const printSchema = z.object({
    kind: z.enum(["simulated", "printed", "sent"]),
    copies: z.number(),
    message: z.string(),
});

async function response(path: string, init?: RequestInit) {
    const res = await fetch(`/studio/api${path}`, init);
    if (!res.ok) {
        const error = z
            .object({ message: z.string() })
            .safeParse(await res.json().catch(() => null));
        throw new Error(
            error.success
                ? error.data.message
                : `Request failed (${res.status}). Please try again.`,
        );
    }
    return res;
}
function json(method: string, body: unknown): RequestInit {
    return {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    };
}
export const api = {
    settings: async (value: Defaults) =>
        defaultsSchema.parse(
            (await (await response("/settings", json("PUT", value))).json())
                .defaults,
        ),
    fontCatalog: async () =>
        catalogSchema.parse(
            (await (await response("/fonts/catalog")).json()).families,
        ),
    installFont: async (id: string) =>
        z
            .object({ font: z.string(), fonts: fontsSchema })
            .parse(
                await (
                    await response("/fonts/install", json("POST", { id }))
                ).json(),
            ),
    uploadFont: async (file: File) => {
        const body = new FormData();
        body.append("font", file);
        return z
            .object({ font: z.string(), fonts: fontsSchema })
            .parse(
                await (
                    await response("/fonts/upload", { method: "POST", body })
                ).json(),
            );
    },
    config: async () =>
        configSchema.parse(await (await response("/config")).json()),
    status: async () =>
        statusSchema.parse(await (await response("/status")).json()),
    preview: async (draft: Draft, signal: AbortSignal) =>
        (await response("/preview", { ...json("POST", draft), signal })).blob(),
    list: async () =>
        z
            .object({ labels: z.array(savedSchema) })
            .parse(await (await response("/labels")).json()).labels,
    save: async (name: string, draft: Draft, id: string | null) =>
        savedSchema.parse(
            await (
                await response(
                    id ? `/labels/${encodeURIComponent(id)}` : "/labels",
                    json(id ? "PUT" : "POST", { name, draft }),
                )
            ).json(),
        ),
    remove: async (id: string) => {
        await response(`/labels/${encodeURIComponent(id)}`, {
            method: "DELETE",
        });
    },
    print: async (
        draft: Draft,
        copies: number,
        cut: "each" | "end",
        confirmRedMedia = false,
    ) =>
        printSchema.parse(
            await (
                await response(
                    "/print",
                    json("POST", { draft, copies, cut, confirmRedMedia }),
                )
            ).json(),
        ),
};
export function starter(config: Config): Draft {
    return {
        content: { kind: "text", text: "Coffee beans" },
        ...config.defaults,
        align: "center",
        color: "black",
        highRes: false,
    };
}
export function errorMessage(error: unknown) {
    return error instanceof Error
        ? error.message
        : "Something went wrong. Please try again.";
}

export function labelTitle(content: Content): string {
    let title = "";
    if (content.kind === "text")
        title = content.text.trim().split(/\r?\n/)[0] ?? "";
    if (content.kind === "qr") {
        title = content.caption.trim() || content.code.trim();
        if (!content.caption.trim()) {
            try {
                const url = new URL(title);
                if (url.protocol === "http:" || url.protocol === "https:")
                    title =
                        url.hostname.replace(/^www\./, "") +
                        (url.pathname === "/" ? "" : url.pathname);
            } catch {
                /* Plain-text QR content is already a useful title. */
            }
        }
    }
    if (content.kind === "image")
        title =
            content.caption.trim() ||
            content.image?.name.replace(/\.[^.]+$/, "") ||
            "";
    return (
        title.replace(/\s+/g, " ").slice(0, 80) ||
        (content.kind === "qr"
            ? "QR label"
            : content.kind === "image"
              ? "Image label"
              : "Text label")
    );
}
