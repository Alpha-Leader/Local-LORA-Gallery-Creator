import argparse
import html
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

print("STARTED SCRIPT")

IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
LORA_EXTS = {".safetensors", ".pt", ".ckpt"}

# Simple tag normalization mapping (can be expanded)
TAG_NORMALIZATION = {
    "realistic": "realism",
    "photorealistic": "realism",
    "anime-style": "anime",
    "manga": "anime",
    "grimdark": "grimdark",
    "dark": "grimdark",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an HTML gallery for LoRAs + trigger words."
    )

    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path.cwd(),
        help="Folder to scan for LoRAs and previews (defaults to current directory).",
    )

    parser.add_argument(
        "--out-file",
        type=Path,
        default=None,
        help="Output HTML path. Defaults to <base-dir>/lora_gallery.html",
    )

    parser.add_argument(
        "--max-images",
        type=int,
        default=24,
        help="Maximum number of images to show per folder card.",
    )

    parser.add_argument(
        "--max-depth",
        type=int,
        default=3,
        help="Depth to search for civitai metadata inside each folder.",
    )

    return parser.parse_args()

ARGS = parse_args()
BASE_DIR = ARGS.base_dir
OUT_FILE = ARGS.out_file or BASE_DIR / "lora_gallery.html"
MAX_IMAGES = ARGS.max_images
MAX_DEPTH = ARGS.max_depth


def rel(p: Path) -> str:
    """Make a URL-safe relative path from the HTML file's folder."""
    rp = os.path.relpath(p, OUT_FILE.parent).replace("\\", "/")
    return quote(rp)


def robust_json_load(text: str):
    """Try to parse JSON even if there's junk before/after."""
    text = text.lstrip("\ufeff").strip()  # strip BOM if present
    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        chunk = text[start : end + 1]
        return json.loads(chunk)

    raise ValueError("No JSON object found in file")


def find_civit_info_files(folder: Path, max_depth: int = 2) -> list[Path]:
    """
    Find files containing 'civit.full.info' in name (case-insensitive),
    searching recursively up to max_depth below `folder`.
    """
    results: list[Path] = []

    folder = folder.resolve()

    # Walk manually to enforce depth limit
    for root, dirs, files in os.walk(folder):
        root_path = Path(root)

        # Depth relative to the folder
        try:
            rel_parts = root_path.relative_to(folder).parts
            depth = len(rel_parts)
        except Exception:
            depth = 999

        # Stop descending too deep
        if depth >= max_depth:
            dirs[:] = []

        for fn in files:
            if "civit.full.info" in fn.lower():
                results.append(root_path / fn)

    return results


def parse_civit_metadata_file(fp: Path) -> dict | None:
    try:
        raw = fp.read_text(encoding="utf-8", errors="ignore")
        return robust_json_load(raw)
    except Exception:
        return None


def normalize_token(s: str) -> str:
    s = re.sub(r"\s+", " ", str(s)).strip()
    s = s.rstrip(",").strip()
    return s


def uniq_preserve(items: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for x in items:
        x = str(x).strip()
        if not x:
            continue
        k = x.lower()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def extract_triggers_from_data(data: dict) -> list[str]:
    triggers: list[str] = []

    for mv in (data.get("modelVersions") or []):
        tw = mv.get("trainedWords", []) or []
        if isinstance(tw, list):
            triggers.extend([normalize_token(x) for x in tw])
        elif isinstance(tw, str) and tw.strip():
            triggers.append(normalize_token(tw))

    tw2 = data.get("trainedWords", None)
    if isinstance(tw2, list):
        triggers.extend([normalize_token(x) for x in tw2])
    elif isinstance(tw2, str) and tw2.strip():
        triggers.append(normalize_token(tw2))

    triggers = [t for t in triggers if t]
    return uniq_preserve(triggers)


def normalize_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        base = TAG_NORMALIZATION.get(t.lower(), t)
        out.append(base)
    return uniq_preserve(out)


def extract_search_tokens_from_data(data: dict) -> tuple[list[str], list[str]]:
    """
    Returns (tokens, normalized_tags)
    tokens: search terms pulled from civit metadata.
    normalized_tags: mapped tags for faceted filtering.
    """
    tokens: list[str] = []
    norm_tags: list[str] = []

    name = data.get("name")
    if isinstance(name, str) and name.strip():
        tokens.append(name.strip())

    creator = data.get("creator") or {}
    if isinstance(creator, dict):
        username = creator.get("username")
        if isinstance(username, str) and username.strip():
            tokens.append(username.strip())

    tags = data.get("tags") or []
    tag_list: list[str] = []
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, str) and t.strip():
                tag_list.append(t.strip())
                tokens.append(t.strip())
    norm_tags = normalize_tags(tag_list)

    for mv in (data.get("modelVersions") or []):
        mv_name = mv.get("name")
        if isinstance(mv_name, str) and mv_name.strip():
            tokens.append(mv_name.strip())

        base_model = mv.get("baseModel")
        if isinstance(base_model, str) and base_model.strip():
            tokens.append(base_model.strip())

        base_model_type = mv.get("baseModelType")
        if isinstance(base_model_type, str) and base_model_type.strip():
            tokens.append(base_model_type.strip())

        tw = mv.get("trainedWords", []) or []
        if isinstance(tw, list):
            tokens.extend([normalize_token(x) for x in tw])
        elif isinstance(tw, str) and tw.strip():
            tokens.append(normalize_token(tw))

        mv_tags = mv.get("tags") or []
        if isinstance(mv_tags, list):
            for t in mv_tags:
                if isinstance(t, str) and t.strip():
                    tokens.append(t.strip())
                    norm_tags.append(TAG_NORMALIZATION.get(t.lower(), t))

    tw2 = data.get("trainedWords", None)
    if isinstance(tw2, list):
        tokens.extend([normalize_token(x) for x in tw2])
    elif isinstance(tw2, str) and tw2.strip():
        tokens.append(normalize_token(tw2))

    tokens = [t for t in tokens if t]
    norm_tags = [t for t in norm_tags if t]
    return uniq_preserve(tokens), uniq_preserve(norm_tags)


# ---- Folder-level cache ----
FOLDER_META_CACHE: dict[str, list[dict]] = {}


def get_folder_metadata(folder: Path) -> tuple[list[dict], dict]:
    """Parse all civit.full.info files under this folder (depth-limited), cached by folder path."""
    key = str(folder.resolve()).lower()
    if key in FOLDER_META_CACHE:
        return FOLDER_META_CACHE[key], {"cached": True}

    debug = {"cached": False, "info_files_found": 0, "info_files_parsed": 0, "parse_errors": 0, "paths": []}
    info_files = find_civit_info_files(folder, max_depth=MAX_DEPTH)
    debug["info_files_found"] = len(info_files)
    debug["paths"] = [p.name for p in info_files[:5]]

    metas: list[dict] = []
    for fp in info_files:
        data = parse_civit_metadata_file(fp)
        if data is None:
            debug["parse_errors"] += 1
            continue
        debug["info_files_parsed"] += 1
        if isinstance(data, dict):
            metas.append(data)

    FOLDER_META_CACHE[key] = metas
    return metas, debug


def pick_best_meta_for_lora(lora_filename: str, metas: list[dict]) -> dict | None:
    """Pick metadata that matches this LoRA filename."""
    target = lora_filename.lower().strip()
    for data in metas:
        for mv in (data.get("modelVersions") or []):
            for fobj in (mv.get("files") or []):
                nm = fobj.get("name")
                if isinstance(nm, str) and nm.lower().strip() == target:
                    return data
    if len(metas) == 1:
        return metas[0]
    return None


def extract_prompt_example(data: dict) -> dict | None:
    """Return a prompt example dict if available."""
    for mv in (data.get("modelVersions") or []):
        for img in (mv.get("images") or []):
            meta = img.get("meta") or {}
            if not isinstance(meta, dict):
                continue
            prompt = meta.get("prompt") or meta.get("Prompt")
            negative = meta.get("negativePrompt") or meta.get("Negative Prompt") or meta.get("Negative prompt")
            steps = meta.get("steps") or meta.get("Steps")
            cfg = meta.get("cfgScale") or meta.get("cfg") or meta.get("CFG scale")
            sampler = meta.get("sampler") or meta.get("Sampler")
            if prompt or negative:
                return {
                    "prompt": str(prompt) if prompt else "",
                    "negative": str(negative) if negative else "",
                    "steps": steps,
                    "cfg": cfg,
                    "sampler": sampler,
                }
    return None


def collect_dataset() -> list[dict]:
    """First pass: collect all folder data."""
    dataset: list[dict] = []
    folders_scanned = 0
    folders_skipped = 0

    for root, dirs, files in os.walk(BASE_DIR):
        root_path = Path(root)
        folders_scanned += 1
        try:
            loras = [f for f in files if Path(f).suffix.lower() in LORA_EXTS]
            imgs = [f for f in files if Path(f).suffix.lower() in IMG_EXTS]
        except PermissionError:
            folders_skipped += 1
            continue

        if not loras or not imgs:
            continue

        metas, dbg = get_folder_metadata(root_path)

        lora_entries: list[dict] = []
        for lf in sorted(loras, key=lambda x: x.lower()):
            best = pick_best_meta_for_lora(lf, metas)
            if best is None and metas:
                best = metas[0]

            triggers = extract_triggers_from_data(best) if best else []
            tokens, norm_tags = extract_search_tokens_from_data(best) if best else ([], [])

            base_model = None
            base_model_type = None
            nsfw = False
            nsfw_level = None
            prompt_example = None

            if best:
                mv0 = (best.get("modelVersions") or [{}])[0]
                base_model = mv0.get("baseModel") or mv0.get("baseModelName") or mv0.get("base_model")
                base_model_type = mv0.get("baseModelType") or mv0.get("base_model_type")
                nsfw = bool(best.get("nsfw")) or bool(mv0.get("nsfw"))
                nsfw_level = best.get("nsfwLevel") or mv0.get("nsfwLevel")
                prompt_example = extract_prompt_example(best)

                # NSFW level may be in images meta
                if nsfw_level is None:
                    for img in mv0.get("images") or []:
                        lvl = img.get("nsfwLevel")
                        if lvl is not None:
                            nsfw_level = lvl
                            break

            lora_entries.append(
                {
                    "name": lf,
                    "triggers": triggers,
                    "extra_tokens": tokens,
                    "norm_tags": norm_tags,
                    "base_model": base_model,
                    "base_model_type": base_model_type,
                    "nsfw": nsfw,
                    "nsfw_level": nsfw_level,
                    "prompt_example": prompt_example,
                    "meta": best,
                }
            )

        if not lora_entries:
            continue

        dataset.append(
            {
                "root": root_path,
                "loras": lora_entries,
                "images": sorted(imgs, key=lambda x: (0 if "preview" in x.lower() else 1, x.lower())),
                "dbg": dbg,
                "title": root_path.name,
            }
        )

    # Attach scan counts to first element for reporting if needed
    if dataset:
        dataset[0]["_scan_counts"] = {"folders_scanned": folders_scanned, "folders_skipped": folders_skipped}
    return dataset


start_time = time.perf_counter()
dataset = collect_dataset()

# Build trigger conflict map and base model set
trigger_map: defaultdict[str, list[str]] = defaultdict(list)
base_models_seen: set[str] = set()
for folder in dataset:
    for l in folder["loras"]:
        if l["base_model"]:
            base_models_seen.add(str(l["base_model"]))
        for trig in l["triggers"]:
            trigger_map[trig.lower()].append(f"{folder['title']}/{l['name']}")

rows = []
header_html = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>LoRA Gallery v5</title>
<style>
  :root { color-scheme: light; }
  body { font-family: sans-serif; margin: 16px; background: #fff; color: #111; transition: background 0.3s, color 0.3s; }
  .toolbar { position: sticky; top: 0; background: inherit; padding: 10px 0; z-index: 5; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  input, select { font-size: 16px; padding: 8px; }
  .card { border: 1px solid #ddd; border-radius: 10px; padding: 12px; margin: 14px 0; }
  .title { font-size: 18px; font-weight: 700; margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }
  .meta { color: #555; margin-bottom: 10px; }
  .grid { display: flex; flex-wrap: wrap; gap: 8px; }
  img { height: 220px; border-radius: 8px; border: 1px solid #ccc; object-fit: cover; }
  .hidden { display: none; }
  .copy { margin-left: 6px; font-size: 13px; padding: 5px 8px; cursor: pointer; }
  code { background: #f4f4f4; padding: 2px 6px; border-radius: 6px; }
  .row { margin-top: 6px; }
  .pill { display:inline-block; background:#f4f4f4; padding:2px 8px; border-radius:999px; margin:2px 6px 2px 0; font-size:12px; }
  details { margin-top: 8px; }
  summary { cursor: pointer; color: #666; }
  .toolbar button { padding: 8px 10px; font-size: 13px; cursor: pointer; }
  .toggle { border: 1px solid #ccc; border-radius: 8px; background: #f8f8f8; }
  .favorite { color: #888; cursor: pointer; }
  .favorite.active { color: #e1a700; }
  textarea.note { width: 100%; min-height: 50px; margin-top: 6px; }
  .warning { color: #c0392b; font-weight: 600; }
</style>
</head>
<body id="top">
<div class="toolbar">
  <input id="q" placeholder="Search LoRAs / triggers / tags / creator / base model..." oninput="filter()" />
  <button class="toggle" id="clear" onclick="clearSearch()">Clear</button>
  <label style="font-size:14px;"><input type="checkbox" id="onlyTriggers" onchange="filter()"> Has triggers only</label>
  <label style="font-size:14px;"><input type="checkbox" id="onlyFav" onchange="filter()"> Favorites only</label>
  <label style="font-size:14px;"><input type="checkbox" id="hideNSFW" onchange="filter()"> Hide NSFW</label>
  <label style="font-size:14px;">NSFW level ≤ <input id="nsfwLevel" type="number" min="0" max="10" value="10" style="width:60px;" oninput="filter()"></label>
  <select id="baseModelFilter" onchange="filter()"><option value="">Base model: All</option></select>
  <select id="sortMode" onchange="applySort()">
    <option value="name">Sort: Name</option>
    <option value="triggers">Sort: Trigger count</option>
    <option value="usage">Sort: Most used</option>
  </select>
  <button class="toggle" id="themeToggle" onclick="toggleTheme()">Dark mode</button>
  <button class="toggle" onclick="exportData()">Export JSON</button>
  <button class="toggle" onclick="showPresets()">Preset stacks</button>
</div>
<div id="presetModal" class="hidden"></div>
<script>
let dark = false;
const baseModelOptions = new Set(BASE_MODEL_OPTIONS_JSON);

function buildBaseModelOptions(){
  const sel = document.getElementById('baseModelFilter');
  Array.from(baseModelOptions).filter(Boolean).sort().forEach(v=>{
    const opt = document.createElement('option');
    opt.value = v.toLowerCase();
    opt.textContent = v;
    sel.appendChild(opt);
  });
}

function filter(){
  const q = document.getElementById('q').value.toLowerCase().trim();
  const terms = q ? q.split(/\\s+/).filter(Boolean) : [];
  const onlyTriggers = document.getElementById('onlyTriggers').checked;
  const onlyFav = document.getElementById('onlyFav').checked;
  const hideNSFW = document.getElementById('hideNSFW').checked;
  const nsfwLevel = parseInt(document.getElementById('nsfwLevel').value || '10', 10);
  const baseModel = (document.getElementById('baseModelFilter').value || '').toLowerCase();
  document.querySelectorAll('.card').forEach(c=>{
    const t = (c.getAttribute('data-key') || '');
    const hasTrig = c.getAttribute('data-has-trigger') === '1';
    const fav = c.getAttribute('data-fav') === '1';
    const cardNSFW = c.getAttribute('data-nsfw') === '1';
    const cardNSFWLevel = parseInt(c.getAttribute('data-nsfw-level') || '0', 10);
    const cardBase = (c.getAttribute('data-base-model') || '').toLowerCase();
    const okTerms = terms.every(term => t.includes(term));
    const okTrig = (!onlyTriggers || hasTrig);
    const okFav = (!onlyFav || fav);
    const okNSFW = (!hideNSFW || !cardNSFW) && (isNaN(nsfwLevel) || cardNSFWLevel <= nsfwLevel);
    const okBase = (!baseModel || cardBase === baseModel);
    const ok = okTerms && okTrig && okFav && okNSFW && okBase;
    c.classList.toggle('hidden', !ok);
  });
}

async function copyText(txt, loraKey){
  try { await navigator.clipboard.writeText(txt); }
  catch(e){ alert("Copy failed. Your browser may block clipboard on local files."); }
  if(loraKey){ bumpUsage(loraKey); }
}
function clearSearch(){
  document.getElementById('q').value = '';
  document.getElementById('onlyTriggers').checked = false;
  document.getElementById('onlyFav').checked = false;
  document.getElementById('hideNSFW').checked = false;
  document.getElementById('baseModelFilter').value = '';
  filter();
}
function toggleTheme(){
  dark = !dark;
  const body = document.body;
  if(dark){
    body.style.background = '#0d0d0f';
    body.style.color = '#f6f6f6';
    document.documentElement.style.setProperty('color-scheme','dark');
    document.querySelectorAll('.card').forEach(c=>c.style.borderColor = '#444');
  } else {
    body.style.background = '#fff';
    body.style.color = '#111';
    document.documentElement.style.setProperty('color-scheme','light');
    document.querySelectorAll('.card').forEach(c=>c.style.borderColor = '#ddd');
  }
}
window.addEventListener('keydown', (e)=>{ if(e.key === 'Escape'){ clearSearch(); }});

function toggleFav(cardId){
  const key = 'fav_'+cardId;
  const cur = localStorage.getItem(key) === '1';
  const next = cur ? '0' : '1';
  localStorage.setItem(key, next);
  document.querySelectorAll('[data-card-id=\"'+cardId+'\"]').forEach(el=>{
    el.setAttribute('data-fav', next);
    const star = el.querySelector('.favorite');
    if(star){ star.classList.toggle('active', next==='1'); }
  });
  filter();
}

function loadFavState(){
  document.querySelectorAll('.card').forEach(c=>{
    const id = c.getAttribute('data-card-id');
    const isFav = localStorage.getItem('fav_'+id) === '1';
    if(isFav){
      c.setAttribute('data-fav','1');
      const star = c.querySelector('.favorite');
      if(star){ star.classList.add('active'); }
    }
  });
}

function saveNote(loraKey){
  const ta = document.getElementById('note_'+loraKey);
  if(!ta) return;
  localStorage.setItem('note_'+loraKey, ta.value);
}
function loadNotes(){
  document.querySelectorAll('textarea.note').forEach(ta=>{
    const key = ta.getAttribute('data-lora-key');
    ta.value = localStorage.getItem('note_'+key) || '';
  });
}

function bumpUsage(loraKey){
  const count = parseInt(localStorage.getItem('use_'+loraKey) || '0', 10) + 1;
  localStorage.setItem('use_'+loraKey, count.toString());
  localStorage.setItem('use_last_'+loraKey, Date.now().toString());
  const badge = document.getElementById('usage_'+loraKey);
  if(badge){ badge.textContent = count; }
  const cardId = loraKey.split('/')[0];
  const cCount = parseInt(localStorage.getItem('use_card_'+cardId) || '0', 10) + 1;
  localStorage.setItem('use_card_'+cardId, cCount.toString());
}
function loadUsage(){
  document.querySelectorAll('[data-usage-key]').forEach(el=>{
    const key = el.getAttribute('data-usage-key');
    el.textContent = localStorage.getItem('use_'+key) || '0';
  });
}

function applySort(){
  const mode = document.getElementById('sortMode').value;
  const container = document.getElementById('cards');
  const cards = Array.from(container.children);
  cards.sort((a,b)=>{
    if(mode === 'triggers'){
      return parseInt(b.getAttribute('data-trigger-count')||'0',10) - parseInt(a.getAttribute('data-trigger-count')||'0',10);
    }
    if(mode === 'usage'){
      return parseInt(localStorage.getItem('use_card_'+(b.getAttribute('data-card-id'))) || '0',10) -
             parseInt(localStorage.getItem('use_card_'+(a.getAttribute('data-card-id'))) || '0',10);
    }
    return (a.getAttribute('data-card-id')||'').localeCompare(b.getAttribute('data-card-id')||'');
  });
  cards.forEach(c=>container.appendChild(c));
}

function exportData(){
  const payload = {
    favorites: Object.entries(localStorage).filter(([k,v])=>k.startsWith('fav_') && v==='1').map(([k])=>k.slice(4)),
    notes: Object.entries(localStorage).filter(([k])=>k.startsWith('note_')).map(([k,v])=>({lora:k.slice(5), note:v})),
    presets: JSON.parse(localStorage.getItem('presets')||'[]'),
    usage: Object.entries(localStorage).filter(([k])=>k.startsWith('use_')).reduce((acc,[k,v])=>{acc[k.slice(4)]=v; return acc;},{}),
  };
  const blob = new Blob([JSON.stringify(payload,null,2)], {type:'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'lora_gallery_export.json';
  a.click();
  URL.revokeObjectURL(url);
}

function showPresets(){
  const modal = document.getElementById('presetModal');
  modal.classList.remove('hidden');
  const presets = JSON.parse(localStorage.getItem('presets')||'[]');
  let html = '<div style=\"background:#222;color:#eee;padding:12px;border-radius:10px;max-width:520px;\">';
  html += '<h3>Preset stacks</h3><div id=\"presetList\">';
  presets.forEach((p,idx)=>{
    html += `<div style=\"margin-bottom:6px;\"><strong>${p.name}</strong> <button onclick=\"copyText('${p.items.join(' ')}')\">Copy</button> <button onclick=\"deletePreset(${idx})\">Delete</button><div style=\"font-size:12px;color:#ccc;\">${p.items.join(', ')}</div></div>`;
  });
  html += '</div>';
  html += '<div style=\"margin-top:8px;\">Name: <input id=\"presetName\" /></div>';
  html += '<div style=\"margin-top:4px;\">Items (space-separated tags): <input id=\"presetItems\" style=\"width:90%;\" /></div>';
  html += '<button style=\"margin-top:8px;\" onclick=\"addPreset()\">Add preset</button> <button onclick=\"closePresets()\">Close</button>';
  html += '</div>';
  modal.innerHTML = html;
}
function closePresets(){ document.getElementById('presetModal').classList.add('hidden'); document.getElementById('presetModal').innerHTML=''; }
function addPreset(){
  const name = (document.getElementById('presetName').value || '').trim();
  const items = (document.getElementById('presetItems').value || '').trim().split(/\\s+/).filter(Boolean);
  if(!name || !items.length) return;
  const presets = JSON.parse(localStorage.getItem('presets')||'[]');
  presets.push({name, items});
  localStorage.setItem('presets', JSON.stringify(presets));
  showPresets();
}
function deletePreset(idx){
  const presets = JSON.parse(localStorage.getItem('presets')||'[]');
  presets.splice(idx,1);
  localStorage.setItem('presets', JSON.stringify(presets));
  showPresets();
}

function init(){
  buildBaseModelOptions();
  loadFavState();
  loadNotes();
  loadUsage();
  applySort();
  filter();
}
window.onload = init;
</script>
"""
header_html = header_html.replace("BASE_MODEL_OPTIONS_JSON", json.dumps(sorted(base_models_seen or {""})))
rows.append(header_html)

card_count = 0
total_with_triggers = 0
total_info_found = 0
total_info_parsed = 0
total_parse_errors = 0
folders_scanned = 0
folders_skipped = 0
folders_missing_meta = 0

# Accumulate base model options
base_models_seen: set[str] = set()

rows.append("<div id='cards'>")

for folder in dataset:
    root_path: Path = folder["root"]
    loras = folder["loras"]
    imgs_sorted = folder["images"]
    dbg = folder["dbg"]
    title = folder["title"]

    folders_scanned += 1
    if "_scan_counts" in folder:
        folders_skipped = folder["_scan_counts"]["folders_skipped"]

    per_lora_triggers = {l["name"]: l["triggers"] for l in loras}

    folder_search_tokens: list[str] = [title]
    for l in loras:
        folder_search_tokens.append(l["name"])
        folder_search_tokens.extend(l["triggers"])
        folder_search_tokens.extend(l["extra_tokens"])
        folder_search_tokens.extend(l["norm_tags"])
        if l["base_model"]:
            folder_search_tokens.append(str(l["base_model"]))
            base_models_seen.add(str(l["base_model"]))

    folder_search_tokens = uniq_preserve([t for t in folder_search_tokens if t])
    data_key = " ".join(folder_search_tokens).lower()

    has_any_trigger = any(per_lora_triggers[lf["name"]] for lf in loras)
    if has_any_trigger:
        total_with_triggers += 1
    else:
        folders_missing_meta += 1

    trigger_count = sum(len(per_lora_triggers[lf["name"]]) for lf in loras)

    # Card NSFW level: max of its loras
    card_nsfw = any(l["nsfw"] for l in loras)
    card_levels: list[int] = []
    for l in loras:
        try:
            if l["nsfw_level"] is not None:
                card_levels.append(int(float(l["nsfw_level"])))
        except Exception:
            continue
    card_nsfw_level = max(card_levels) if card_levels else 0
    card_base_model = ""
    for l in loras:
        if l["base_model"]:
            card_base_model = str(l["base_model"])
            break

    rows.append(
        f"<div class='card' data-card-id='{html.escape(title)}' data-key='{html.escape(data_key)}' "
        f"data-has-trigger='{1 if has_any_trigger else 0}' data-trigger-count='{trigger_count}' "
        f"data-nsfw='{1 if card_nsfw else 0}' data-nsfw-level='{card_nsfw_level}' "
        f"data-base-model='{html.escape(card_base_model.lower())}' data-fav='0'>"
    )
    rows.append(
        f"<div class='title'><span>{html.escape(title)}</span>"
        f"<span class='favorite' onclick=\"toggleFav('{html.escape(title)}')\">★</span></div>"
    )
    rows.append("<div class='meta'>")

    for l in loras:
        safe_lf = html.escape(l["name"])
        stem = html.escape(Path(l["name"]).stem)
        rel_path = html.escape(str((root_path / l["name"]).relative_to(BASE_DIR)))
        lora_key = html.escape(f"{title}/{l['name']}")

        rows.append(
            f"<div class='row'>LoRA: <code>{safe_lf}</code> "
            f"<button class='copy' onclick=\"copyText('{safe_lf}','{lora_key}')\">Copy filename</button>"
            f"<button class='copy' onclick=\"copyText('&lt;lora:{stem}:1&gt;','{lora_key}')\">Copy &lt;lora:&gt; tag</button>"
            f"<span style='margin-left:8px;color:#777;font-size:12px;'>{rel_path}</span>"
            f"<span style='margin-left:6px;font-size:12px;color:#555;'>usage: <span id='usage_{lora_key}' data-usage-key='{lora_key}'>0</span></span>"
            f"</div>"
        )

        weight_buttons = " ".join(
            [
                f"<button class='copy' onclick=\"copyText('&lt;lora:{stem}:{w}&gt;','{lora_key}')\">{w}</button>"
                for w in ("0.6", "0.8", "1.0", "1.2")
            ]
        )
        rows.append(f"<div class='row'>Weights: {weight_buttons}</div>")

        tlist = l["triggers"]
        if tlist:
            tjoined = ", ".join(tlist)
            safe_t = html.escape(tjoined)
            rows.append(
                f"<div class='row'>↳ Triggers: <code>{safe_t}</code> "
                f"<button class='copy' onclick=\"copyText('{safe_t}','{lora_key}')\">Copy triggers</button></div>"
            )
        else:
            rows.append("<div class='row'>↳ Triggers: <em>(none found)</em></div>")

        # Conflict warnings
        conflicts = []
        for t in l["triggers"]:
            hits = trigger_map.get(t.lower(), [])
            if len(hits) > 1:
                conflicts.append(f"{t} ({len(hits)} matches)")
        if conflicts:
            rows.append(f"<div class='row warning'>⚠️ Trigger conflicts: {'; '.join(html.escape(c) for c in conflicts)}</div>")

        extras = l["extra_tokens"]
        pills = []
        for x in extras[:30]:
            x = str(x).strip()
            if not x or len(x) > 40:
                continue
            pills.append(x)
            if len(pills) >= 10:
                break
        if pills:
            rows.append(
                "<div class='row'>↳ <span style='color:#777'>search tags:</span> "
                + " ".join([f"<span class='pill'>{html.escape(p)}</span>" for p in pills])
                + "</div>"
            )

        if l["norm_tags"]:
            rows.append(
                "<div class='row'>↳ <span style='color:#777'>normalized tags:</span> "
                + " ".join([f"<span class='pill'>{html.escape(p)}</span>" for p in l["norm_tags"]])
                + "</div>"
            )

        if l["base_model"] or l["base_model_type"]:
            rows.append(
                "<div class='row'>↳ Base: "
                f"{html.escape(str(l['base_model'])) if l['base_model'] else ''} "
                f"{'('+html.escape(str(l['base_model_type']))+')' if l['base_model_type'] else ''}</div>"
            )

        nsfw_label = "NSFW" if l["nsfw"] else "SFW"
        nsfw_lvl = f" (level {l['nsfw_level']})" if l["nsfw_level"] is not None else ""
        rows.append(f"<div class='row'>↳ {nsfw_label}{nsfw_lvl}</div>")

        if l["prompt_example"]:
            pe = l["prompt_example"]
            safe_p = html.escape(pe.get("prompt", ""))
            safe_n = html.escape(pe.get("negative", ""))
            meta_bits = []
            if pe.get("steps"):
                meta_bits.append(f"steps: {pe['steps']}")
            if pe.get("cfg"):
                meta_bits.append(f"cfg: {pe['cfg']}")
            if pe.get("sampler"):
                meta_bits.append(f"sampler: {pe['sampler']}")
            rows.append(
                "<details><summary>Prompt example</summary>"
                f"<div class='row'><strong>Positive:</strong> <code>{safe_p}</code></div>"
                f"<div class='row'><strong>Negative:</strong> <code>{safe_n}</code></div>"
                f"<div class='row'>{html.escape(', '.join(meta_bits))}</div>"
                f"<div class='row'><button class='copy' onclick=\"copyText('{safe_p}','{lora_key}')\">Copy positive</button> "
                f"<button class='copy' onclick=\"copyText('{safe_n}','{lora_key}')\">Copy negative</button> "
                f"<button class='copy' onclick=\"copyText('{safe_p}\\nNEGATIVE: {safe_n}','{lora_key}')\">Copy both</button></div>"
                "</details>"
            )

        rows.append(
            f"<div class='row'>Notes:<br><textarea class='note' id='note_{lora_key}' data-lora-key='{lora_key}' "
            f"onchange=\"saveNote('{lora_key}')\" placeholder='Add notes (stored locally)'></textarea></div>"
        )

    rows.append("</div>")  # end meta

    rows.append("<div class='grid'>")
    for imgf in imgs_sorted[:MAX_IMAGES]:
        img_path = root_path / imgf
        rows.append(
            f"<a href='{rel(img_path)}' target='_blank'>"
            f"<img src='{rel(img_path)}' loading='lazy' title='{html.escape(imgf)}'></a>"
        )
    rows.append("</div></div>")  # end grid + card

    card_count += 1
    if dbg.get("info_files_found"):
        total_info_found += dbg["info_files_found"]
        total_info_parsed += dbg["info_files_parsed"]
        total_parse_errors += dbg["parse_errors"]

rows.append("</div>")  # cards container

rows.append("<hr>")
rows.append("<h3>Summary</h3>")
rows.append(f"<div>Total folders scanned: <code>{folders_scanned}</code></div>")
rows.append(f"<div>Folders skipped (permissions): <code>{folders_skipped}</code></div>")
rows.append(f"<div>Total entries: <code>{card_count}</code></div>")
rows.append(f"<div>Entries with at least one trigger: <code>{total_with_triggers}</code></div>")
rows.append(f"<div>Entries missing triggers/meta: <code>{folders_missing_meta}</code></div>")
rows.append(f"<div>Total civit info files found: <code>{total_info_found}</code></div>")
rows.append(f"<div>Total civit info files parsed: <code>{total_info_parsed}</code></div>")
rows.append(f"<div>Total parse errors: <code>{total_parse_errors}</code></div>")
rows.append(f"<div>Total time: <code>{time.perf_counter() - start_time:.2f}s</code></div>")
rows.append(
    "<div style='margin-top:8px;'><a href='#top' onclick='window.scrollTo({top:0,behavior:\"smooth\"});return false;'>Back to top</a></div>"
)

rows.append("</body></html>")

OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
OUT_FILE.write_text("\n".join(rows), encoding="utf-8")
print(f"✅ Wrote gallery to: {OUT_FILE}")
print(f"✅ Entries: {card_count}, with >=1 trigger: {total_with_triggers}")
print(f"✅ Folders scanned: {folders_scanned}, skipped: {folders_skipped}, missing triggers/meta: {folders_missing_meta}")
print(f"✅ civit files found: {total_info_found}, parsed: {total_info_parsed}, parse errors: {total_parse_errors}")
print(f"⏱️ Total time: {time.perf_counter() - start_time:.2f}s")