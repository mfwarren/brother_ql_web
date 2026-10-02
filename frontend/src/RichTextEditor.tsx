import { useEffect, useRef, useState } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import { Extension } from "@tiptap/core";
import { Plugin } from "@tiptap/pm/state";
import StarterKit from "@tiptap/starter-kit";
import { TextStyle, FontSize } from "@tiptap/extension-text-style";
import {
    Bold,
    Italic,
    Underline,
    Undo2,
    Redo2,
    RemoveFormatting,
} from "lucide-react";
import {
    fontSize,
    fromDocument,
    toDocument,
    type TextContent,
} from "./rich-text";
import type { Config } from "./api";

const limits = Extension.create({
    name: "labelLimits",
    addProseMirrorPlugins() {
        return [
            new Plugin({
                filterTransaction: (transaction) =>
                    transaction.doc.textContent.length <= 2000 &&
                    transaction.doc.childCount <= 100,
            }),
        ];
    },
});
const labelSize = FontSize.extend({
    addGlobalAttributes() {
        return [
            {
                types: ["textStyle"],
                attributes: {
                    fontSize: {
                        default: null,
                        parseHTML: (element) => {
                            const size = fontSize(element.style.fontSize);
                            return size ? `${size}px` : null;
                        },
                        renderHTML: (attributes) => {
                            const size = fontSize(attributes.fontSize);
                            return size ? { style: `font-size:${size}px` } : {};
                        },
                    },
                },
            },
        ];
    },
});
const labelFont = Extension.create({
    name: "labelFont",
    addGlobalAttributes() {
        return [
            {
                types: ["textStyle"],
                attributes: {
                    font: {
                        default: null,
                        parseHTML: (element) =>
                            element.getAttribute("data-label-font"),
                        renderHTML: (attrs) =>
                            typeof attrs.font === "string"
                                ? {
                                      "data-label-font": attrs.font,
                                      style: `font-family:"LabelFace${encodeURIComponent(attrs.font)}"`,
                                  }
                                : {},
                    },
                },
            },
        ];
    },
});
const extensions = [
    StarterKit.configure({
        heading: false,
        blockquote: false,
        bulletList: false,
        orderedList: false,
        listItem: false,
        listKeymap: false,
        code: false,
        codeBlock: false,
        horizontalRule: false,
        link: false,
        strike: false,
        trailingNode: false,
    }),
    TextStyle,
    labelSize,
    labelFont,
    limits,
];

function TextSize({
    value,
    onChange,
}: {
    value: number;
    onChange: (size: number) => void;
}) {
    const [text, setText] = useState(String(value));
    useEffect(() => setText(String(value)), [value]);
    return (
        <label className="rich-size">
            <input
                type="number"
                aria-label="Text size in pixels"
                min={8}
                max={200}
                step={1}
                value={text}
                onChange={(event) => {
                    setText(event.target.value);
                    const next = event.target.valueAsNumber;
                    if (Number.isInteger(next) && next >= 8 && next <= 200)
                        onChange(next);
                }}
                onBlur={() => setText(String(value))}
            />
            <span>px</span>
        </label>
    );
}

type Props = {
    value: TextContent;
    onChange: (value: TextContent) => void;
    font: string;
    size: number;
    fonts: Config["fonts"];
    lineSpacing: number;
    onLineSpacingChange: (value: number) => void;
};
export default function RichTextEditor({
    value,
    onChange,
    font,
    size,
    fonts,
    lineSpacing,
    onLineSpacingChange,
}: Props) {
    const emitted = useRef(new Set<string>());
    const editor = useEditor({
        extensions,
        content: toDocument(value),
        shouldRerenderOnTransaction: true,
        editorProps: {
            attributes: {
                role: "textbox",
                "aria-label": "Label text",
                "aria-multiline": "true",
                spellcheck: "true",
            },
        },
        onUpdate: ({ editor }) => {
            const next = fromDocument(editor.getJSON());
            emitted.current.add(JSON.stringify(next));
            onChange(next);
        },
    });
    const valueKey = JSON.stringify(value);
    useEffect(() => {
        if (!editor) return;
        if (emitted.current.has(valueKey)) {
            // Acknowledge parent updates without replacing newer local transactions.
            for (const pending of emitted.current) {
                emitted.current.delete(pending);
                if (pending === valueKey) break;
            }
        } else {
            editor.commands.setContent(toDocument(value), {
                emitUpdate: false,
            });
            emitted.current.clear();
        }
    }, [editor, valueKey]);
    const styles = fonts
        .map((baseFace) => {
            const family = baseFace.id.split(",")[0];
            return [false, true]
                .flatMap((bold) =>
                    [false, true].map((italic) => {
                        const candidates = fonts.filter(
                            (face) =>
                                face.id.split(",")[0] === family &&
                                face.italic === (italic || baseFace.italic),
                        );
                        const weight = bold ? 700 : baseFace.weight;
                        const face = [...candidates].sort(
                            (a, b) =>
                                Math.abs(a.weight - weight) -
                                Math.abs(b.weight - weight),
                        )[0];
                        return face
                            ? `@font-face{font-family:"LabelFace${encodeURIComponent(baseFace.id)}";src:url("/studio/api/fonts/file?font=${encodeURIComponent(face.id)}");font-weight:${bold ? 700 : 400};font-style:${italic ? "italic" : "normal"};font-display:swap;}`
                            : "";
                    }),
                )
                .join("\n");
        })
        .join("\n");
    if (!editor) return null;
    const selectedSize = fontSize(editor.getAttributes("textStyle").fontSize);
    const selectedFont =
        fonts.find(
            (face) =>
                face.id === (editor.getAttributes("textStyle").font ?? font),
        ) ?? fonts[0];
    const family = selectedFont.id.split(",")[0];
    const familyFaces = fonts.filter(
        (face) => face.id.split(",")[0] === family,
    );
    const weight = editor.isActive("bold") ? 700 : selectedFont.weight;
    const italic = editor.isActive("italic") || selectedFont.italic;
    const nearest = (faces: Config["fonts"]) =>
        [...faces].sort(
            (a, b) =>
                Number(a.italic !== italic) * 1000 +
                Math.abs(a.weight - weight) -
                (Number(b.italic !== italic) * 1000 +
                    Math.abs(b.weight - weight)),
        )[0];
    const effectiveFace = nearest(familyFaces);
    const selectFace = (id: string) =>
        editor
            .chain()
            .focus()
            .unsetBold()
            .unsetItalic()
            .setMark("textStyle", { font: id })
            .run();
    const changeStyle = (targetWeight: number, targetItalic: boolean) => {
        const face = [...familyFaces]
            .filter((face) => face.italic === targetItalic)
            .sort(
                (a, b) =>
                    Math.abs(a.weight - targetWeight) -
                    Math.abs(b.weight - targetWeight),
            )[0];
        if (face) selectFace(face.id);
    };
    return (
        <div className="rich-editor">
            <style>{styles}</style>
            <div
                className="rich-toolbar"
                role="toolbar"
                aria-label="Text formatting"
            >
                <select
                    aria-label="Font family"
                    className="rich-font"
                    value={family}
                    onChange={(event) =>
                        selectFace(
                            nearest(
                                fonts.filter(
                                    (face) =>
                                        face.id.split(",")[0] ===
                                        event.target.value,
                                ),
                            ).id,
                        )
                    }
                >
                    {[...new Set(fonts.map((face) => face.id.split(",")[0]))]
                        .sort((a, b) => a.localeCompare(b))
                        .map((name) => (
                            <option key={name} value={name}>
                                {name}
                            </option>
                        ))}
                </select>
                <select
                    aria-label="Font style"
                    className="rich-font-style"
                    value={effectiveFace.id}
                    onChange={(event) => selectFace(event.target.value)}
                >
                    {[...familyFaces]
                        .sort(
                            (a, b) =>
                                Number(a.italic) - Number(b.italic) ||
                                a.weight - b.weight,
                        )
                        .map((face) => (
                            <option key={face.id} value={face.id}>
                                {face.id.split(",").slice(1).join(",")}
                            </option>
                        ))}
                </select>
                <label className="line-spacing-control" title="Line spacing">
                    <span>Spacing</span>
                    <input
                        aria-label="Line spacing percent"
                        type="number"
                        min={100}
                        max={300}
                        step={10}
                        value={lineSpacing}
                        onChange={(event) =>
                            onLineSpacingChange(Number(event.target.value))
                        }
                    />
                    <span>%</span>
                </label>
                <TextSize
                    value={selectedSize ?? size}
                    onChange={(next) =>
                        editor.chain().setFontSize(`${next}px`).run()
                    }
                />
                <button
                    type="button"
                    className="icon-button"
                    aria-label="Bold"
                    aria-pressed={effectiveFace.weight >= 600}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() =>
                        changeStyle(
                            effectiveFace.weight >= 600 ? 400 : 700,
                            effectiveFace.italic,
                        )
                    }
                >
                    <Bold size={16} />
                </button>
                <button
                    type="button"
                    className="icon-button"
                    aria-label="Italic"
                    aria-pressed={effectiveFace.italic}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() =>
                        changeStyle(effectiveFace.weight, !effectiveFace.italic)
                    }
                >
                    <Italic size={16} />
                </button>
                <button
                    type="button"
                    className="icon-button"
                    aria-label="Underline"
                    aria-pressed={editor.isActive("underline")}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() =>
                        editor.chain().focus().toggleUnderline().run()
                    }
                >
                    <Underline size={16} />
                </button>
                <button
                    type="button"
                    className="icon-button"
                    aria-label="Clear selected formatting"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() =>
                        editor
                            .chain()
                            .focus()
                            .unsetBold()
                            .unsetItalic()
                            .unsetFontSize()
                            .unsetUnderline()
                            .setMark("textStyle", { font: null })
                            .run()
                    }
                >
                    <RemoveFormatting size={16} />
                </button>
                <button
                    type="button"
                    className="icon-button"
                    aria-label="Undo text edit"
                    disabled={!editor.can().undo()}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => editor.chain().focus().undo().run()}
                >
                    <Undo2 size={16} />
                </button>
                <button
                    type="button"
                    className="icon-button"
                    aria-label="Redo text edit"
                    disabled={!editor.can().redo()}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => editor.chain().focus().redo().run()}
                >
                    <Redo2 size={16} />
                </button>
            </div>
            <div
                className="rich-text-area"
                style={{
                    fontSize: `${size}px`,
                    fontFamily: `"LabelFace${encodeURIComponent(font)}", sans-serif`,
                    fontWeight: 400,
                    fontStyle: "normal",
                }}
            >
                <div style={{ lineHeight: lineSpacing / 100 }}>
                    <EditorContent editor={editor} />
                </div>
            </div>
            <span className="small muted">
                Select text to format · Preview shows the printed layout
            </span>
        </div>
    );
}
