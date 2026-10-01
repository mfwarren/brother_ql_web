# Architecture decision

Choose the static React and TypeScript candidate on top of the DL6ER Python app. Both candidates reuse the renderer and avoid Node on the Pi. The independent comparison in architecture-comparison.md ties the scores at 21, and favors React for stateful phone editing. Parent assessment agrees: React wins on editing state, Flask forms win on build simplicity, neither changes the cost of image rendering. No Node server or browser canvas renderer is introduced.

Model the Domain shaped the draft as a text/QR/image union. Prove It Works shaped verification around actual PNG rendering, persisted documents and simulated raster output. Type System Discipline shaped the client boundary into parsed Zod schemas with inferred TypeScript types.

The concrete implementation contract is studio-contract.md. It deliberately narrows the first modern editor to shared text formatting, QR content, images, basic layout and saved labels. The old editor retains per-line styles, barcodes and templates. Saved modern documents have their own versioned directory so opening them cannot discard unsupported upstream formatting. An importer is deferred, not silently approximated.

Graft from the Flask candidate: server-configured printer destination, truthful simulation status, atomic repository writes, and bounded uploads. Keep the React candidate's static deployment and stale-preview cancellation. Reject a second server runtime and browser-side rasterization. Keep the restored 2020 app untouched; the development checkout is a local branch of the 2026 successor.

Implementation reconciliation: first-page PDF conversion avoids work for pages the editor never uses. Font fallback now returns an actual installed font. The adapter splits multiline content into upstream line records after a real browser test exposed Pillow's multiline anchor error. Preview, save and print all use the same draft validation and renderer. The original classic routes remain available.
