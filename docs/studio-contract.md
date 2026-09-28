# Studio contract, implementation target

All endpoints under /studio/api. Same-origin Flask serves built React files under /studio/. Classic /labeldesigner remains available for advanced upstream features. Backend retains upstream renderer and driver. No arbitrary client-selected printer path.

GET /config -> {model:string, fonts:[{id:string,name:string}], sizes:[{id:string,name:string}], defaultFont:string, defaultSize:string, mode:'simulation'|'physical'}.
GET /status -> {state:'simulation'|'ready'|'offline'|'busy'|'error'|'unknown', model:string, message:string, media:string|null}.
POST /preview JSON LabelDraft -> image/png or {message:string} with error status.
POST /print JSON {draft:LabelDraft,copies:integer,cut:'each'|'end'} -> {kind:'simulated'|'printed'|'sent',copies:number,message:string}. Server configured simulation vs physical, no UI override. Reject absent hardware. Interprocess lock for hardware and reject contention. Configured default in local instance is simulation.
GET /labels -> {labels:[{id:string,name:string,updatedAt:string,draft:LabelDraft}]}.
POST /labels JSON {name:string,draft:LabelDraft} -> saved object {id,name,updatedAt,draft} (new UUID; avoids overwrite).
PUT /labels/<id> JSON {name,draft} -> updated saved object.
DELETE /labels/<id> -> {success:true}.

LabelDraft = {content: discriminated Content, sizeId:string, orientation:'standard'|'rotated', font:string, fontSize:number, align:'left'|'center'|'right', color:'black'|'red', margin:number, highRes:boolean}.
Content = {kind:'text',text:string} | {kind:'qr',code:string,caption:string} | {kind:'image',image:null|{name:string,mime:string,base64:string},caption:string,mode:'grayscale'|'bw'|'red',fit:boolean}.

First modern UI has shared style across text lines. Classic editor keeps per-line styles/barcodes/other upstream features. LabelDraft schema validation belongs on server. Font id family,style comes from catalog. Black/red color only on 62red; highRes off for red media. Image uploaded as base64 to bound 5 MiB, PNG/JPEG/PDF allowed. Server limits label text sizes and copies to 1..100, fonts to known ids, size to QL800 compatible labels. Margin 0..100 px. Font size 8..200. Validate preview/save/print same way. Empty draft returns useful 400, UI can display empty state.

Modern saved documents may be separate versioned JSON under instance/studio-labels, because first UI cannot losslessly edit all upstream rich label formats. Do not overwrite or silently downgrade upstream labels. Retain classic editor and original label repository for those. Save atomically. This deviation from original React candidate is deliberate to prevent silent loss of advanced line options. Later explicit importer can map features or refuse unsupported ones.

Expected local development: instance config points to .local-fonts and simulation, 127.0.0.1:8014. Build output app/static/studio. Backend can be exercised via Flask client independent of frontend build. Meaningful tests should exercise actual renderer, persistence round-trip with images, bounds, failed physical device, explicit simulation and lock contention. No actual printing needed.
