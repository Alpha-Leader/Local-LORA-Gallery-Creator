# LoRA Gallery V5

![Local LORA Gallery Screenshot](screenshot.png)
_Screenshot from an earlier version — the V5 layout adds a folder sidebar and prompt sandbox._

A local, single-file HTML gallery for browsing, organizing, and managing your Stable Diffusion LoRA collection. No web server, no installation beyond Python — just run the script and open the HTML in your browser.

---

## Requirements

- **Python 3.8+** — no external packages required (stdlib only)
- A folder of LoRA files (`.safetensors`, `.pt`, or `.ckpt`)
- Optional: CivitAI `.civitai.full.info` or `.civit.info` metadata files alongside your LoRAs (for names, triggers, tags, creator info, likes/downloads)

---

## Quick Start

1. Copy `LocalLoraGalleryV5.py` and `Rebuild Gallery V5.bat` into your LoRA root folder
2. Double-click **`Rebuild Gallery V5.bat`**
3. Choose option **1** (Smart rebuild) and press Enter
4. When prompted, press **Y** to open the gallery in your browser

The gallery is fully self-contained in `lora_gallery.html`. Open it directly in any browser — no server needed.

---

## Bat Menu Options

```
[1] Smart rebuild           Rescan folders, reuse cached prompt metadata  ← use this daily
[2] Skip-prompts rebuild    Rescan folders only, skip all image metadata   ← fastest
[3] Full rebuild            Rescan + re-read ALL PNG prompts from scratch  ← thorough
[4] Clear cache + rebuild   Delete metadata cache, then smart rebuild      ← after updates
[5] Open gallery            Open existing gallery instantly, no scan       ← quick browse
[6] Update CivitAI metadata Re-fetch stats/triggers from CivitAI API      ← refresh data
[7] Fetch CivitAI images    Download top sample images per LoRA            ← get previews
[8] Run deletions           Execute run_deletions.py to move marked items  ← cleanup
```

---

## Folder Structure

The script scans recursively from where it lives. It works with any nesting — flat, one level deep, or multiple levels. The recommended layout is:

```
loras/
  LocalLoraGalleryV5.py
  Rebuild Gallery V5.bat
  Anima/
    SomeCharacter/
      SomeCharacter.safetensors
      SomeCharacter.civitai.full.info   ← CivitAI metadata (optional)
      preview.png                        ← preview image (optional)
  Pony/
    AnotherLora/
      ...
  SDXL/
    ...
```

The first folder level (Anima, Pony, SDXL, etc.) becomes the **category** shown in the sidebar.

---

## CivitAI Metadata (.info files)

LoRAs downloaded via **CivitAI Helper** or similar tools often include `.civitai.full.info` files. The gallery reads these automatically to display:
- Trigger words
- Tags
- Base model (Pony, SDXL, Illustrious, etc.)
- Creator name
- Download count and likes
- CivitAI model link

Without a `.info` file, the gallery still shows the LoRA — just without the above metadata.

---

## Updating CivitAI Metadata (Option 6)

Refreshes stats, trigger words, and tags from the CivitAI API for any LoRA that already has a `.info` file.

- **Interactive folder picker** — choose one subfolder (e.g., just "Pony") or all
- Detects changes: `[NEW VERSION]`, `[UPDATED]`, `[+triggers]`, `[-triggers]`
- Saves a `_civitai_update_report.txt` with links to changed models on civitai.red
- API delay: 0.1s between requests

LoRAs without a `.info` file cannot be updated (no ID to look up).

---

## Fetching Sample Images (Option 7)

Downloads the top 5 most-reacted images from CivitAI for each LoRA and saves them into the LoRA's folder.

- **Interactive folder picker** — target one subfolder or all
- Images saved as `_civitai_top_1.jpg`, `_civitai_top_2.jpg`, etc.
- Prompt metadata saved as `_civitai_top_1.jpg.params` (A1111 format) — visible in the gallery lightbox
- Skips images already downloaded — safe to re-run
- NSFW images included by default
- After downloading, automatically rebuilds the gallery

---

## Gallery Features

### Search & Filter
- **Search bar** — AND-term search across folder names, filenames, triggers, tags, creator, base model
- **+Notes** — also search your personal notes
- **Img dupes** — show/hide duplicate-prompt images
- Filters: Has Triggers, Favs, Hide NSFW, NSFW threshold, Dupes only, Unused only
- **Base model dropdown** — filter to one base model
- **Sort** — Name, Newest, Folder, Triggers, Most Used, NSFW Level, Largest, Fav: Recent, Most Liked, Most Downloaded

### Sidebar
- **★ Favorites** — live count, click to filter to favorites only
- **Recently Used** — last 8 LoRAs you interacted with, clickable to jump
- **Collections** — custom labels you add to cards (e.g., "character", "style", "wip"), click to filter
- **Categories** — auto-built from your top-level folders

### Cards
- Click the card title to add to the prompt queue
- **↗ CivitAI** link on every card with metadata (opens civitai.red)
- **★** star to favorite, **[18+]** to manually tag NSFW, **+ Label** to add collections
- Copy filename, copy `<lora:stem:1>` tag, add to prompt queue
- Trigger pills — click any to copy; "Copy all" copies all at once
- Notes textarea — saved in your browser, searchable with +Notes checkbox
- Image strip with variable height slider (drag in toolbar)

### Lightbox
- Click any image to open full-screen
- Shows positive/negative prompts, Steps, CFG, Sampler, Seed, Size, Model
- Works for local PNGs with embedded metadata AND for CivitAI-downloaded images (via `.params` sidecar)
- Buttons: Copy prompt, Copy negative, Send to sandbox, Copy all params
- Keyboard: ← → to navigate, Esc to close

### Prompt Sandbox (right panel)
- **LoRA Queue** — add LoRAs, set weights (0.1–2.0), click "+ Tags & Triggers" to build your prompt
- **Presets** — save/load named prompt + queue combinations
- **History** — last 20 prompts you copied
- **Quick Inserts** — model-specific tag buttons (Universal, Illustrious, Anima, Pony)
- **Wildcards** — browse and insert from wildcard `.txt` files

---

## Duplicate Management

### Duplicate LoRA folders (same model, different folders)
The gallery detects LoRAs with the same CivitAI model ID or similar name and shows a yellow **DUPE** badge. Use the "Dupes only" filter to find them. Use the "Delete folder" button to mark one for deletion, then run deletions.

### Duplicate images (same prompt, different files)
Within each folder, if two images have identical generation prompts, the older one is:
- Hidden by default (use "Img dupes" checkbox to show them)
- Auto-marked for deletion with a yellow outline
- Shown in a strip note: *"N duplicate images hidden — marked for deletion"*

To keep a specific duplicate, click its × button (sets "keep" flag so it won't be re-marked).

---

## Deletion Workflow

The gallery never permanently deletes anything — it moves files to `_DELETED/`.

1. **Mark items** in the gallery — click × on images or "Delete folder" on LoRA rows; duplicate images are auto-marked
2. **Check the count** — "Deletions (N)" button in toolbar shows total marked
3. **Download the script** — click "Deletions (N)" → saves `run_deletions.py` to your browser's downloads folder → move it to your loras folder
4. **Run option 8** in the bat — executes `run_deletions.py`, moves everything to `_DELETED/`
5. **Rebuild** (option 1) to remove them from the gallery
6. **Permanently delete** `_DELETED/` only once you've confirmed everything looks right

---

## Compact Mode

Click **Compact** in the toolbar to switch to a thumbnail grid view. Hides trigger/tag rows, notes, and action buttons. The thumbnail size slider still works in compact mode. The CivitAI link remains visible.

---

## Wildcards

Place `.txt` files in a `wildcards/` subfolder next to the script. Each file becomes a browsable category in the right panel. You can also drag-and-drop `.txt` files directly into the wildcard drop zone in the gallery (session only).

---

## Extra Prompt Pack

Create a `prompt_pack.json` file in the same folder as the script to add custom quick-insert buttons. Structure mirrors the built-in packs:

```json
{
  "universal": {
    "quality": ["my custom tag", "another tag"],
    "negative": ["unwanted thing"]
  }
}
```

---

## Data & Privacy

All your personal data (favorites, notes, usage counts, labels, queue, presets) is stored in your **browser's localStorage** — it never leaves your machine. The gallery HTML can be shared with others and they will start with a clean slate.

The CivitAI metadata update and image fetch features make outbound HTTP requests to `civitai.com/api/v1/`. No other network requests are made.

---

## Tips

- **First run on a large collection?** Use option 3 (Full rebuild) once, then option 1 for all subsequent rebuilds
- **Added new LoRAs?** Option 1 is sufficient — it only re-reads metadata for new/changed files
- **Prompts missing in lightbox?** Run option 4 (Clear cache + rebuild) — previous cache entries may be stale
- **Downloaded CivitAI images not showing prompts?** Option 4 (Clear cache + rebuild) — the sidecar check was added in V5 and old cache entries may say "no metadata"
- **Slow fetch?** Target a specific subfolder when using options 6 and 7 instead of updating all folders at once
- **civitai.red** — all links in the gallery open on civitai.red (a mirror). CivitAI API calls still go to civitai.com
