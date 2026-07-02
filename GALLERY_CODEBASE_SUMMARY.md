# LoRA Gallery — Codebase Summary
_Last updated: 2026-07-02 (V5, verified against source). Read this instead of re-scanning the full .py file._

## Source File Section Map (`LocalLoraGalleryV5.py`, 2595 lines)

| Lines | Section |
|-------|---------|
| 13–43 | Constants + NSFW prompt regex (58 terms, lookaround-based so `spread_legs` matches) |
| 46–102 | `PROMPT_PACKS` (universal / illustrious / anima / pony) |
| 104–127 | `parse_args()` + module-level ARGS/BASE_DIR/OUT_FILE/CACHE_FILE |
| 129–150 | Metadata cache load/save |
| 152–182 | Helpers (`rel_url`, `load_json`, `norm`, `uniq`, `is_info`) |
| 184–356 | PNG chunk reader, `_parse_a1111`, `_parse_comfyui`, `extract_img_meta` |
| 358–398 | `extract()` — CivitAI .info → normalized dict |
| 400–540 | `scan()` — directory walk, lora/image entry building, prompt dedup |
| 542–581 | Wildcard scanner |
| 583–620 | `detect_duplicates()` (folder-level) |
| 636–943 | `CSS` string constant |
| 948–1096 | `BODY` HTML string constant |
| 1101–2224 | `JS` string constant (all browser logic) |
| 2226–2364 | `update_civitai_metadata()` (--update-civitai) |
| 2366–2509 | `fetch_civitai_images()` (--fetch-images N) |
| 2511–2595 | `main()` — build pipeline + HTML assembly |

---

## Files

| File | Purpose |
|------|---------|
| `LocalLoraGalleryV5.py` | **Current version.** Single Python script → outputs `lora_gallery.html` |
| `LocalLoraGalleryV4.py` | Previous version (kept for reference) |
| `LocalLoraGalleryV3.py` | Older version (kept for reference) |
| `lora_gallery.html` | Generated output — open this in a browser |
| `Rebuild Gallery V5.bat` | Launch menu: options 1–8 (see below) |
| `.lora_gallery_meta_cache.json` | PNG/sidecar metadata cache (keyed by filepath+filesize) |
| `_civitai_update_report.txt` | Written after option 6 (CivitAI metadata update) |
| `run_deletions.py` | Downloaded from gallery UI; moves marked items to `_DELETED/` |
| `GALLERY_CODEBASE_SUMMARY.md` | This file |
| `README.md` | User-facing setup and usage guide |

### Bat menu options (V5)
1. **Smart rebuild** — rescan + use cached PNG/sidecar prompts (typical use, fast)
2. **Skip-prompts rebuild** — rescan only, skip all metadata reading (fastest)
3. **Full rebuild** — rescan + clear/rebuild entire metadata cache (slow)
4. **Clear cache + rebuild** — delete cache file, then smart rebuild (use after script update or when lightbox prompts are wrong)
5. **Open gallery** — open existing HTML instantly, no Python run
6. **Update CivitAI metadata** — re-fetch stats/triggers/tags from civitai.com API, then rebuild
7. **Fetch CivitAI sample images** — download top 5 most-reacted images per LoRA with metadata sidecars, then rebuild
8. **Run deletions** — execute `run_deletions.py` (must be downloaded from gallery first)

---

## Python Architecture

Single-file HTML generator. No dependencies beyond Python stdlib.

```
Python runs:
  update_civitai_metadata(BASE_DIR)   [if --update-civitai]
  fetch_civitai_images(BASE_DIR, N)   [if --fetch-images N]
  scan(BASE_DIR)          → list of folder-entry dicts
  detect_duplicates(data) → marks dup_group on entries in-place
  scan_wildcards(wc_dir)  → dict of wildcard categories
  load_extra_pack()       → merges prompt_pack.json if present

Then inlines everything as JSON into:
  CSS  (string constant)
  BODY (HTML string constant)
  JS   (raw string constant, __DATA__ / __PACKS__ / __WILDCARDS__ replaced)
  → writes lora_gallery.html
```

### Key CLI args
```
--base-dir PATH      root folder to scan (default: cwd)
--out-file PATH      output HTML path (default: <base-dir>/lora_gallery.html)
--max-images N       max images per folder (default: 12)
--skip-meta          skip all metadata extraction
--clear-cache        ignore existing cache, re-read all metadata
--wildcards-dir PATH folder for wildcard .txt files
--prompt-json PATH   extra prompt pack JSON to merge
--update-civitai     re-fetch CivitAI metadata then rebuild
--fetch-images N     download top N most-reacted CivitAI images per LoRA then rebuild
```

---

## Data Model (Python → JSON → JS)

Each **folder entry** in `DATA` array:
```js
{
  id:           "relative/folder/path",   // localStorage key base
  title:        "FolderName",
  folder:       "relative/folder/path",   // empty string = root
  category:     "TopLevelFolder",         // first path segment, or "(root)"
  loras:        [ ...loraEntry ],
  images:       [ ...imageEntry ],
  image_count:  N,                        // total images in folder
  search_text:  "lowercase blob of all searchable text",
  has_triggers: bool,
  trigger_count: N,
  nsfw:         bool,
  nsfw_level:   0-100,
  base_model:   "SDXL" | "Pony" | ...,
  total_size:   bytes,
  date_added:   unix_timestamp,
  dup_group:    "model:12345" | "name:foo" | ""
}
```

Each **lora entry** (inside `folder.loras[]`):
```js
{
  filename:   "model.safetensors",
  stem:       "model",
  rel_path:   "category/folder/model.safetensors",
  file_size:  bytes,
  triggers:   ["trigger1", "trigger2"],
  tags:       ["tag1", "tag2"],
  base_model: "SDXL",
  nsfw:       bool,
  nsfw_level: N,
  name:       "Display Name",
  creator:    "username",
  stats:      { downloads: N, thumbsUp: N },  // from .info file
  model_id:   12345,                          // CivitAI model ID
  date_added: unix_timestamp
}
```

Each **image entry** (inside `folder.images[]`):
```js
{
  url:     "relative/path/to/image.jpg",
  meta:    null | { source, positive, negative, steps, cfg, sampler, seed, size, model },
  nsfw:    bool,    // detected from prompt text via regex
  dup_img: bool     // true = identical positive prompt to a newer image in same folder
}
```

---

## Metadata Sources

### CivitAI .info files
Suffixes scanned: `.civitai.full.info`, `.civit.full.info`, `.civit.info`
Fields read: `name`, `id`, `modelId`, `baseModel`, `trainedWords`, `tags`, `nsfw`, `nsfwLevel`, `stats.downloadCount`, `stats.thumbsUpCount`, `model.name`, `model.tags`, `model.nsfw`, `files[].name`, `modelVersions[]`

### PNG metadata (no PIL required)
Reads `tEXt`, `zTXt`, `iTXt` PNG chunks.
- **A1111**: `parameters` chunk → positive, "Negative prompt:", Steps, CFG, Sampler, Seed, Size, Model
- **ComfyUI**: `prompt` JSON chunk → KSampler node, CLIPTextEncode nodes

### `.params` sidecar files (V5)
Files named `imagename.jpg.params` (or `.png.params`, `.webp.params`) containing A1111-format text. Written by `--fetch-images` for downloaded CivitAI JPEGs. `extract_img_meta()` checks for sidecar before PNG chunk reading, for any image format.

Cache key = `filepath|filesize`. Skips files >30 MB. Reads at most `PNG_META_MAX=12` metadata sources per folder (PNG chunks OR sidecars).

### Duplicate image detection (V5)
After building `img_entries` for a folder, groups images by normalized positive prompt. Within each group, keeps the newest file (by `st_mtime`), marks others `dup_img: True`. Only images with metadata (prompt text) can be compared — images without metadata are never marked.

---

## JavaScript Architecture

### State variables
```js
DATA          // full dataset (read-only, inlined at build time)
PACKS         // prompt packs {universal, illustrious, anima, pony}
WILDCARDS     // wildcard data from scan

filtered      // current filtered+sorted subset of DATA
rendered      // how many cards have been rendered (virtual scroll)
PAGE = 60     // cards per render batch
activeCat     // active sidebar category filter ("" = All)
activeLbl     // active Collections label filter ("" = none)
_queue        // LoRA queue [{stem, filename, triggers, cardTitle, weight}]
_compact      // compact grid mode bool
lbImgs/lbIdx  // lightbox state
_wcData       // wildcard data (built-in + dropped)
_wcActiveCat  // active wildcard category
_delCount     // deletion marker count
```

### Key functions
```
applyFilter()           reads all filter controls → rebuilds filtered[] → re-renders
renderMore()            appends next PAGE cards to DOM (virtual scroll); calls updateDelCount()
mkCard(d)               builds a full card DOM element for folder entry d
buildLblRow(id, el)     renders label chips + "+ Label" button into el
buildCollections()      rebuilds sidebar Collections section from localStorage
buildRecent()           rebuilds sidebar Recently Used from lu_ts_* keys
jumpToCard(id)          scrolls to + flashes a card, clears filter if needed
buildBM()               populates base model dropdown
buildCats()             builds sidebar category list
buildPacks()            builds prompt pack quick-insert buttons
updateFavCount()        syncs fav-n counter + favcat.on state
toggleFavFilter()       toggles ckF checkbox + updates UI
bump(cardId, fn)        increments usage count + updates lu_ts_ + buildRecent()
queueAdd(le, title, cardId)   adds to queue + lu_ts_ + buildRecent()
showRandom()            jumps to random card in current filter
jumpToCard(id)          scrolls to card, clears filter if not visible
showStats()             opens stats modal with bar charts
showDelExport()         generates + downloads run_deletions.py
buildDelScript()        creates the Python deletion script content
lbOpen/lbShow/lbClose/lbPrev/lbNext   lightbox control
sbApp(id, txt)          appends txt to sandbox textarea id
sbCopyAndSave()         copies sandbox content + saves to history
savePreset/loadPreset/deletePreset     prompt preset management
saveToHistory/toggleHistory            prompt history (last 20)
initWildcards/buildWcData/renderWcCats/selectWcCat/renderWcPanel   wildcards
filterCreator(name)     sets search to creator name
toggleCompact()         toggles compact grid mode
toggleTheme()           toggles dark/light theme
doExport()              copies filtered list to clipboard
updateDelCount()        syncs deletion badge; called in renderMore() and toggles
```

---

## localStorage Schema

### Per card/folder (keyed by `d.id`)
```
fav_<id>           "1" | "0"        favorite flag
fav_ts_<id>        timestamp ms      when favorited (recency sort)
nsfw_m_<id>        "1" | "0"        manual NSFW override
uc_<id>            number string    aggregate usage count for card
lu_ts_<id>         timestamp ms      last used timestamp (recently used sidebar)
labels_<id>        JSON string[]    collections labels e.g. ["character","wip"]
```

### Per lora file (keyed by `d.id + "/" + le.filename`)
```
note_<id>/<filename>   string       user notes textarea content
use_<id>/<filename>    number       usage count (bumped when triggers copied)
del_folder_<folder>    "1"          marks folder for deletion
```

### Per image (keyed by URL)
```
del_img_<url>      "1" | "0"        marks image for deletion ("0" = explicitly kept)
nsfw_img_<url>     "1" | "0"        manual per-image NSFW toggle
```
Note: `dup_img` images are auto-set to `del_img_<url>="1"` on first render. Unmarking sets "0" (not null) so auto-mark doesn't re-fire on next load.

### Global
```
theme              "dark" | "light"
view_compact       "1" | "0"
thumb_h            number string    thumbnail height px (default 165)
lora_queue         JSON array       persisted queue items
sb_presets         JSON object      {name: {positive, negative, queue}}
prompt_history     JSON array       last 20 {pos, neg, ts} entries
wc_dropped         JSON object      session-dropped wildcard files
show_img_dup       "1" | "0"        show/hide duplicate images (default hidden)
```

---

## Features Inventory (V5)

### Toolbar
- Text search (AND-term, searches folder/filename/triggers/tags/creator/base model)
- `+Notes` checkbox — extends search to per-lora notes textarea
- `Img dupes` checkbox — show/hide duplicate-prompt images (hidden by default)
- Sort: Name / Newest / Folder / Triggers / Most Used / NSFW Level / Largest / ★ Fav: Recent / Most Liked / Most Downloaded
- Base model dropdown filter
- Has Triggers / Favs / Hide NSFW / NSFW max threshold / Dupes only / Unused only checkboxes
- Random — jumps to random visible card
- Compact — toggles grid/detail view
- Stats modal — folder/lora counts, size, bar charts by model/category/creator
- Moon/Sun — dark/light theme
- Export — copies filtered list to clipboard
- Deletions (N) — generates + downloads `run_deletions.py`
- Images slider (60–300px) — live-resizes image strip via `--thumb-h` CSS var

### Sidebar
- ★ Favorites — live count badge, click = toggle favs filter
- Recently Used — last 8 interacted cards, clickable to jump
- Collections — custom labels per card, auto-populated, clickable to filter
- Categories — auto-built from first folder level, clickable to filter
- Tools — external links

### Per Card
- Title (click = add first lora to queue), folder path, `↗ CivitAI` link (civitai.red, shown in compact mode too)
- Download/like stats, NSFW badge, Duplicate badge, Manual [18+] toggle, ★ favorite star
- Collections label chips + "+ Label" button
- Per LoRA: filename, display name, base model, creator (clickable = filter), size, CivitAI link
- Per LoRA actions: Copy filename, Copy `<lora:stem:1>`, Add to queue, usage counter, Delete folder
- Trigger pills (copyable, bumps usage), Tag pills (up to 14), Notes textarea
- Image strip: lazy-loaded thumbnails, variable height, lightbox on click
- Per-image: delete button, NSFW toggle, purple outline = has metadata
- Duplicate images: yellow outline, hidden by default, auto-marked for deletion
- Image strip notes: "N explicit images hidden", "N duplicate images hidden — marked for deletion"

### Lightbox
- Full-screen with prev/next (arrows + ← →), Esc to close
- Metadata panel: positive/negative prompts, Steps/CFG/Sampler/Seed/Size/Model
- Works for PNG chunk metadata AND `.params` sidecar metadata
- Buttons: Copy prompt, Copy negative, Send to sandbox, Copy all params

### Prompt Sandbox (right panel)
- LoRA Queue with weight controls, "Build" → `<lora:stem:weight>` + triggers
- Positive + negative textareas, presets (save/load/delete), history (last 20)
- Quick Inserts: Universal / Illustrious / Anima / Pony model tabs
- Wildcards: browse built-in + dropped .txt files, insert/random/drag-drop

### CivitAI Integration (V5)
- **`--update-civitai`**: interactive folder picker, re-fetches metadata, detects NEW VERSION / UPDATED / trigger changes, writes `_civitai_update_report.txt`, links to `civitai.red/models/{id}`
- **`--fetch-images N`**: interactive folder picker, downloads top-N most-reacted images per LoRA, saves `.params` sidecar in A1111 format, respects existing files (skip if present), NSFW included
- API delays: 0.1s between requests
- All display links use `civitai.red`; API calls use `civitai.com/api/v1/`

---

## NSFW System
- Card-level: from `.info` `nsfw` + `nsfwLevel` fields
- Manual override: `nsfw_m_<id>`, [18+] button on card
- Image-level: auto-detected from PNG/sidecar prompt (58-term regex with lookarounds so underscore-joined danbooru tags match), overridable per image
- Hide NSFW filter + NSFW max slider

## Keyboard Shortcuts
- `/` — focus search (when not in a text field)
- `Esc` — clear search/filters (or close lightbox if open)
- `←` / `→` — prev/next image in lightbox

## Duplicate Detection (folder-level)
Python post-scan. Groups by model_id or normalized name. Sets `dup_group`. Shown as DUPE badge. "Dupes only" filter.

## Duplicate Image Detection (V5, image-level)
Python in-scan. Within each folder, groups images by normalized positive prompt. Keeps newest (st_mtime), marks others `dup_img: True`. Hidden in gallery by default, auto-marked for deletion.

## Virtual Scrolling
IntersectionObserver on sentinel. 60 cards/batch. Disconnected before filter changes, reconnected after `requestAnimationFrame`.

---

## Adding New Features — Patterns to Follow

**New sort option:**
1. `<option value="key">Sort: Label</option>` in BODY sort select
2. `else if(srt==="key") filtered.sort(...)` in `applyFilter()` sort block

**New filter checkbox:**
1. `<label class="chk"><input type="checkbox" id="ckX"> Label</label>` in toolbar
2. `const ckX=document.getElementById("ckX").checked;` in `applyFilter()`
3. Filter condition in `filtered=DATA.filter(d=>{...})`
4. Add `"ckX"` to event listener forEach + clearSearch forEach

**New sidebar section:**
1. `<div class="sh">Title</div><div id="mylist"></div>` in BODY sidebar
2. `buildMySection()` JS function populating `#mylist`
3. Call in DOMContentLoaded init

**New per-image data field:**
1. Add field to `img_entries.append({...})` in `scan()`
2. Access as `imgObj.fieldName` in JS `mkCard` image loop

**New Python metadata field:**
1. Extract in `extract()` function
2. Add to lora_entry dict in `scan()`
3. Available in JS as `d.loras[N].fieldName`

---

## Prompt Packs
```python
{
  "universal":   { "quality": [...], "negative": [...], "subjects": [...], "styles": [...] },
  "illustrious": { ... },
  "anima":       { ... },
  "pony":        { "quality": [...], "source": [...], "negative": [...], "danbooru": [...] }
}
```
Extra packs from `prompt_pack.json` or `--prompt-json`. Section `"negative"` → negative prompt; all others → positive.

---

## CSS Variable Reference
```css
--bg          page background
--bg2         card / toolbar background
--bg3         input / pill background
--border      border color
--text        primary text
--text2       muted text / labels
--accent      purple (#8b5cf6) — active states, focus rings
--accent2     lighter purple (#a78bfa) — hover, links
--green       #22c55e — triggers, collections labels
--yellow      #eab308 — favorites star, duplicate image outline
--red         #ef4444 — delete, NSFW
--r           10px — border radius
--tr          .15s ease — transition speed
--thumb-h     165px (default) — image strip height (user-adjustable via toolbar slider)
```
