import { useEffect, useRef } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import { Extension } from "@tiptap/core";
import { Plugin } from "@tiptap/pm/state";
import StarterKit from "@tiptap/starter-kit";
import { TextStyle, FontSize } from "@tiptap/extension-text-style";
import { Bold, Italic, Undo2, Redo2, RemoveFormatting } from "lucide-react";
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
        underline: false,
        strike: false,
        trailingNode: false,
    }),
    TextStyle,
    labelSize,
    limits,
];

type Props = {
    value: TextContent;
    onChange: (value: TextContent) => void;
    font: string;
    size: number;
    fonts: Config["fonts"];
};
export default function RichTextEditor({
    value,
    onChange,
    font,
    size,
    fonts,
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
    const base = fonts.find((face) => face.id === font);
    const family = font.split(",")[0];
    const normal = fonts.filter(
        (face) => face.id.split(",")[0] === family && !face.italic,
    );
    const italic = fonts.filter(
        (face) => face.id.split(",")[0] === family && face.italic,
    );
    const closest = (faces: Config["fonts"], weight: number) =>
        [...faces].sort(
            (a, b) => Math.abs(a.weight - weight) - Math.abs(b.weight - weight),
        )[0];
    const faces = [
        closest(normal, base?.weight ?? 400),
        closest(normal, 700),
        closest(italic, base?.weight ?? 400),
        closest(italic, 700),
    ].filter((face) => face !== undefined);
    const styles = faces
        .map(
            (face) =>
                `@font-face{font-family:LabelEditorFont;src:url("/studio/api/fonts/file?font=${encodeURIComponent(face.id)}");font-weight:${face.weight};font-style:${face.italic ? "italic" : "normal"};font-display:swap;}`,
        )
        .join("\n");
    if (!editor) return null;
    const selectedSize = fontSize(editor.getAttributes("textStyle").fontSize);
    return (
        <div className="rich-editor">
            <style>{styles}</style>
            <div
                className="rich-toolbar"
                role="toolbar"
                aria-label="Text formatting"
            >
                <button
                    type="button"
                    className="icon-button"
                    aria-label="Bold"
                    aria-pressed={editor.isActive("bold")}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => editor.chain().focus().toggleBold().run()}
                >
                    <Bold size={16} />
                </button>
                <button
                    type="button"
                    className="icon-button"
                    aria-label="Italic"
                    aria-pressed={editor.isActive("italic")}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => editor.chain().focus().toggleItalic().run()}
                >
                    <Italic size={16} />
                </button>
                <select
                    aria-label="Selected text size"
                    value={selectedSize ?? ""}
                    onChange={(event) => {
                        if (event.target.value)
                            editor
                                .chain()
                                .focus()
                                .setFontSize(`${event.target.value}px`)
                                .run();
                        else editor.chain().focus().unsetFontSize().run();
                    }}
                >
                    <option value="">Default size</option>
                    {[
                        ...new Set([
                            24,
                            32,
                            40,
                            48,
                            56,
                            70,
                            80,
                            96,
                            120,
                            160,
                            ...(selectedSize ? [selectedSize] : []),
                        ]),
                    ]
                        .sort((a, b) => a - b)
                        .map((value) => (
                            <option key={value} value={value}>
                                {value} px
                            </option>
                        ))}
                </select>
                <button
                    type="button"
                    className="icon-button"
                    aria-label="Clear selected formatting"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => editor.chain().focus().unsetBold().unsetItalic().unsetFontSize().run()}
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
                    fontFamily: "LabelEditorFont, sans-serif",
                    fontWeight: base?.weight ?? 400,
                    fontStyle: base?.italic ? "italic" : "normal",
                }}
            >
                <EditorContent editor={editor} />
            </div>
            <span className="small muted">
                Select text to format · Preview shows the printed layout
            </span>
        </div>
    );
}
