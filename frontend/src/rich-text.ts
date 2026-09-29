import { z } from "zod";
import type { JSONContent } from "@tiptap/core";
import type { Content, Paragraphs } from "./api";

export type TextContent = Extract<Content, { kind: "text" }>;
const markSchema = z.discriminatedUnion("type", [
    z.object({ type: z.literal("bold") }),
    z.object({ type: z.literal("italic") }),
    z.object({
        type: z.literal("textStyle"),
        attrs: z
            .object({
                fontSize: z.string().nullable().optional(),
                font: z.string().nullable().optional(),
            })
            .optional(),
    }),
]);
const documentSchema = z.object({
    type: z.literal("doc"),
    content: z
        .array(
            z.object({
                type: z.literal("paragraph"),
                content: z
                    .array(
                        z.discriminatedUnion("type", [
                            z.object({
                                type: z.literal("text"),
                                text: z.string(),
                                marks: z.array(markSchema).optional(),
                            }),
                            z.object({ type: z.literal("hardBreak") }),
                        ]),
                    )
                    .optional(),
            }),
        )
        .optional(),
});

export function fontSize(value: unknown): number | undefined {
    if (typeof value !== "string" || !/^\d+px$/.test(value)) return undefined;
    return Math.max(8, Math.min(200, Number.parseInt(value, 10)));
}

export function fromDocument(value: unknown): TextContent {
    const document = documentSchema.parse(value);
    const paragraphs: Paragraphs = [];
    for (const paragraph of document.content ?? []) {
        let runs: Paragraphs[number]["runs"] = [];
        for (const node of paragraph.content ?? []) {
            if (node.type === "hardBreak") {
                paragraphs.push({ runs });
                runs = [];
                continue;
            }
            const run: Paragraphs[number]["runs"][number] = { text: node.text };
            for (const mark of node.marks ?? []) {
                if (mark.type === "bold") run.bold = true;
                if (mark.type === "italic") run.italic = true;
                if (mark.type === "textStyle") {
                    if (mark.attrs?.font) run.font = mark.attrs.font;
                    const size = fontSize(mark.attrs?.fontSize);
                    if (size !== undefined) run.size = size;
                }
            }
            runs.push(run);
        }
        paragraphs.push({ runs });
    }
    if (!paragraphs.length) paragraphs.push({ runs: [] });
    return {
        kind: "text",
        text: paragraphs
            .map((p) => p.runs.map((run) => run.text).join(""))
            .join("\n"),
        paragraphs,
    };
}

export function toDocument(value: TextContent): JSONContent {
    const paragraphs: Paragraphs =
        value.paragraphs ??
        value.text.split("\n").map((text) => ({ runs: [{ text }] }));
    return {
        type: "doc",
        content: paragraphs.map((paragraph) => ({
            type: "paragraph",
            content: paragraph.runs
                .filter((run) => run.text)
                .map((run) => ({
                    type: "text",
                    text: run.text,
                    marks: [
                        ...(run.bold ? [{ type: "bold" }] : []),
                        ...(run.italic ? [{ type: "italic" }] : []),
                        ...(run.size || run.font
                            ? [
                                  {
                                      type: "textStyle",
                                      attrs: {
                                          fontSize: run.size
                                              ? `${run.size}px`
                                              : null,
                                          font: run.font ?? null,
                                      },
                                  },
                              ]
                            : []),
                    ],
                })),
        })),
    };
}
