#!/usr/bin/env python3
"""
LocalLoraGalleryV5.py  —  Optimized LoRA gallery
Features: virtual scrolling, dark mode, copyable tag pills, image lightbox
with embedded prompt/settings, manual NSFW toggle, model-specific tag presets,
folder sidebar, prompt sandbox, PNG metadata extraction (no PIL required),
favorites with live sidebar counter and recency sort.
"""
import argparse, json, os, re, struct, time, zlib
from pathlib import Path
from urllib.parse import quote

# ── Constants ─────────────────────────────────────────────────────────────────
LORA_EXTS     = {".safetensors", ".pt", ".ckpt"}
IMG_EXTS      = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
INFO_SUFFIXES = (".civitai.full.info", ".civit.full.info", ".civit.info")
PNG_META_MAX  = 12       # max images to read PNG metadata from per folder
PNG_SIZE_LIMIT = 30 * 1024 * 1024  # skip files >30 MB

# ── NSFW image prompt detection ───────────────────────────────────────────────
_NSFW_IMG_TERMS = [
    "nsfw","nude","nudity","naked","explicit","hentai",
    "topless","bottomless","completely nude","completely_nude",
    "nipple","nipples","areola","areolae",
    "pussy","vagina","vulva","penis","cock","phallus","erection",
    "ass","anus","groin","cameltoe","upskirt","genitals","genitalia",
    "sex","intercourse","penetration","blowjob","fellatio",
    "cunnilingus","paizuri","masturbation","orgasm","squirting",
    "cum","cumshot","creampie","ahegao","anal",
    "bondage","bdsm","gangbang","orgy",
    "handjob","footjob","fingering","spread legs","sex toy",
    "no panties","no bra","no_panties","no_bra",
    "loli","shota",
]
def _nsfw_pat(term):
    # Use lookarounds instead of \b so underscore-joined danbooru tags like
    # large_ass or spread_legs are matched even though _ is a \w character.
    parts = re.split(r'[ _]', term)
    inner = r'[ _]'.join(re.escape(p) for p in parts)
    return r'(?<![a-zA-Z])' + inner + r'(?![a-zA-Z])'
_NSFW_IMG_RE = re.compile('|'.join(_nsfw_pat(t) for t in _NSFW_IMG_TERMS), re.IGNORECASE)
def is_nsfw_prompt(text: str) -> bool:
    return bool(_NSFW_IMG_RE.search(text)) if text else False

# ── Prompt packs ──────────────────────────────────────────────────────────────
PROMPT_PACKS = {
    "universal": {
        "quality":  ["masterpiece","best quality","high detail","sharp focus",
                     "cinematic lighting","highres","intricate details","ultra-detailed"],
        "negative": ["worst quality","low quality","lowres","blurry","jpeg artifacts",
                     "watermark","signature","text","bad anatomy","bad hands","deformed","ugly"],
        "subjects": ["1girl","1boy","2girls","solo","portrait","full body","cowboy shot",
                     "upper body","close-up","looking at viewer","from above","from below",
                     "from behind","dutch angle","smile","blush","standing","sitting"],
        "styles":   ["anime style","semi-realistic","photorealistic","oil painting",
                     "watercolor","ink illustration","pixel art","comic style",
                     "detailed background","simple background","white background",
                     "outdoors","indoors","night","sunset","city"],
    },
    "illustrious": {
        "quality":  ["masterpiece","best quality","newest","very aesthetic","absurdres",
                     "highres","ultra-detailed","amazing quality","perfect composition",
                     "beautiful detailed eyes","detailed face","intricate details"],
        "negative": ["lowres","worst quality","low quality","bad anatomy","bad hands",
                     "extra fingers","missing fingers","bad proportions","watermark",
                     "signature","text","cropped","out of frame","mutation","deformed",
                     "ugly","blurry","jpeg artifacts","artist name","censored"],
        "danbooru": ["1girl","1boy","solo","portrait","upper body","cowboy shot","full body",
                     "looking at viewer","smile","blush","expressionless","serious",
                     "long hair","short hair","twintails","ponytail",
                     "school uniform","dress","bikini","nude",
                     "outdoors","indoors","bedroom","classroom","city","forest","beach",
                     "night","day","moonlight","sunset","detailed background","simple background"],
    },
    "anima": {
        "quality":  ["masterpiece","best quality","amazing quality","very aesthetic",
                     "absurdres","highres","ultra-detailed","perfect anatomy",
                     "beautiful shading","clean line art","vibrant colors"],
        "negative": ["worst quality","low quality","bad anatomy","bad hands","extra digits",
                     "missing digits","lowres","blurry","jpeg artifacts","watermark",
                     "text","signature","deformed","ugly","censored"],
        "danbooru": ["1girl","1boy","solo","portrait","upper body","cowboy shot","full body",
                     "looking at viewer","smile","blush","expressionless","ahegao",
                     "long hair","short hair","twintails","ponytail","gradient hair",
                     "school uniform","dress","swimsuit","bikini","nude","naked",
                     "outdoors","indoors","bedroom","classroom","night","day","detailed background"],
    },
    "pony": {
        "quality":  ["score_9","score_8_up","score_7_up","score_6_up","score_5_up","score_4_up",
                     "masterpiece","best quality","highly detailed","amazing quality"],
        "source":   ["source_anime","source_manga","source_cartoon","source_western"],
        "negative": ["score_5","score_4","score_3","score_2","score_1",
                     "worst quality","bad quality","low quality","lowres",
                     "bad anatomy","bad hands","watermark","text","signature","deformed",
                     "source_pony","source_furry"],
        "danbooru": ["1girl","1boy","solo","portrait","upper body","cowboy shot","full body",
                     "looking at viewer","smile","blush","expressionless",
                     "long hair","short hair","twintails","ponytail",
                     "school uniform","dress","swimsuit","bikini","nude",
                     "outdoors","indoors","bedroom","night","day"],
    },
}

# ── Args ──────────────────────────────────────────────────────────────────────
def parse_args():
    ap = argparse.ArgumentParser(description="LoRA Gallery V5")
    ap.add_argument("--base-dir",   type=Path, default=Path.cwd())
    ap.add_argument("--out-file",   type=Path, default=None)
    ap.add_argument("--max-images", type=int,  default=12)
    ap.add_argument("--prompt-json",type=Path, default=None)
    ap.add_argument("--skip-meta",  action="store_true",
                    help="Skip PNG metadata extraction (much faster, no prompt display in lightbox)")
    ap.add_argument("--clear-cache",action="store_true",
                    help="Ignore and rebuild the PNG metadata cache")
    ap.add_argument("--wildcards-dir", type=Path, default=None,
                    help="Folder containing wildcard .txt files (default: <base-dir>/wildcards)")
    ap.add_argument("--update-civitai", action="store_true",
                    help="Re-fetch CivitAI metadata for all LoRAs that have existing .info files, then rebuild")
    ap.add_argument("--fetch-images",   type=int, default=0, metavar="N",
                    help="Download top N most-reacted CivitAI images per LoRA (with metadata sidecars), then rebuild")
    return ap.parse_args()

ARGS     = parse_args()
BASE_DIR = ARGS.base_dir.resolve()
OUT_FILE = (ARGS.out_file or BASE_DIR / "lora_gallery.html").resolve()
MAX_IMGS = ARGS.max_images
CACHE_FILE = BASE_DIR / ".lora_gallery_meta_cache.json"

# ── Metadata cache ────────────────────────────────────────────────────────────
_META_CACHE: dict = {}

def _load_cache():
    global _META_CACHE
    if ARGS.skip_meta or ARGS.clear_cache:
        _META_CACHE = {}
        return
    try:
        if CACHE_FILE.exists():
            _META_CACHE = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            print(f"  Loaded {len(_META_CACHE)} cached metadata entries.")
    except Exception:
        _META_CACHE = {}

def _save_cache():
    if ARGS.skip_meta:
        return
    try:
        CACHE_FILE.write_text(json.dumps(_META_CACHE, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    except Exception as e:
        print(f"  Warning: could not save cache: {e}")

# ── Helpers ───────────────────────────────────────────────────────────────────
def rel_url(p: Path) -> str:
    return quote(os.path.relpath(p, OUT_FILE.parent).replace("\\", "/"))

def load_json(fp: Path):
    try:
        txt = fp.read_text(encoding="utf-8", errors="ignore").lstrip("﻿").strip()
        try:
            return json.loads(txt)
        except Exception:
            s, e = txt.find("{"), txt.rfind("}")
            if s != -1 and e > s:
                return json.loads(txt[s:e+1])
    except Exception:
        pass
    return None

def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().rstrip(",").strip()

def uniq(lst):
    seen, out = set(), []
    for x in lst:
        x = str(x).strip()
        if x and x.lower() not in seen:
            seen.add(x.lower()); out.append(x)
    return out

def is_info(name: str) -> bool:
    n = name.lower()
    return any(n.endswith(s) for s in INFO_SUFFIXES)

# ── PNG metadata (no PIL required) ────────────────────────────────────────────
def _read_png_texts(fp: Path) -> dict:
    """Read tEXt/zTXt/iTXt chunks from a PNG. Returns dict of key->value."""
    texts = {}
    try:
        sz = fp.stat().st_size
        if sz > PNG_SIZE_LIMIT:
            return texts
        with open(fp, "rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                return texts
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                length = struct.unpack(">I", hdr[:4])[0]
                ctype  = hdr[4:8].decode("ascii", errors="ignore")
                if length > 10 * 1024 * 1024:
                    f.seek(length + 4, 1)
                    continue
                data = f.read(length)
                f.read(4)  # CRC
                if ctype == "tEXt":
                    nul = data.find(b"\x00")
                    if nul != -1:
                        key = data[:nul].decode("latin-1", errors="ignore")
                        val = data[nul+1:].decode("latin-1", errors="ignore")
                        texts[key] = val
                elif ctype == "zTXt":
                    nul = data.find(b"\x00")
                    if nul != -1 and len(data) > nul + 2:
                        key = data[:nul].decode("latin-1", errors="ignore")
                        try:
                            val = zlib.decompress(data[nul+2:]).decode("utf-8", errors="ignore")
                            texts[key] = val
                        except Exception:
                            pass
                elif ctype == "iTXt":
                    nul = data.find(b"\x00")
                    if nul != -1:
                        key  = data[:nul].decode("utf-8", errors="ignore")
                        rest = data[nul+1:]
                        if len(rest) >= 2:
                            compressed = rest[0]
                            rest = rest[2:]
                            n2 = rest.find(b"\x00")
                            if n2 != -1:
                                rest = rest[n2+1:]
                                n3 = rest.find(b"\x00")
                                if n3 != -1:
                                    raw = rest[n3+1:]
                                    if compressed:
                                        try: raw = zlib.decompress(raw)
                                        except Exception: pass
                                    texts[key] = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw
                if ctype == "IDAT":
                    break
    except Exception:
        pass
    return texts


def _parse_a1111(params: str) -> dict:
    """Parse A1111/AUTOMATIC1111 'parameters' text chunk."""
    out = {"source": "a1111"}
    try:
        lines = params.strip().splitlines()
        neg_idx = next((i for i, l in enumerate(lines) if l.startswith("Negative prompt:")), None)
        # Find settings line (starts with "Steps:")
        set_idx = next((i for i, l in enumerate(lines) if re.match(r"Steps:\s*\d+", l.strip())), None)

        if neg_idx is not None:
            out["positive"] = "\n".join(lines[:neg_idx]).strip()
            neg_end = set_idx if set_idx is not None else len(lines)
            neg_text = "\n".join(lines[neg_idx:neg_end])
            out["negative"] = neg_text.replace("Negative prompt:", "", 1).strip()
        elif set_idx is not None:
            out["positive"] = "\n".join(lines[:set_idx]).strip()
        else:
            out["positive"] = params.strip()

        if set_idx is not None:
            sl = lines[set_idx]
            def _g(pattern):
                m = re.search(pattern, sl, re.IGNORECASE)
                return m.group(1).strip() if m else None
            if _g(r"Steps:\s*(\d+)"): out["steps"] = _g(r"Steps:\s*(\d+)")
            if _g(r"CFG scale:\s*([\d.]+)"): out["cfg"] = _g(r"CFG scale:\s*([\d.]+)")
            if _g(r"Sampler:\s*([^,]+)"): out["sampler"] = _g(r"Sampler:\s*([^,]+)")
            if _g(r"Seed:\s*(\d+)"): out["seed"] = _g(r"Seed:\s*(\d+)")
            if _g(r"Size:\s*([\dx]+)"): out["size"] = _g(r"Size:\s*([\dx]+)")
            mdl = _g(r"Model:\s*([^,]+)")
            if mdl: out["model"] = mdl
    except Exception:
        pass
    return out


def _parse_comfyui(prompt_json: str) -> dict:
    """Parse ComfyUI 'prompt' JSON chunk."""
    out = {"source": "comfyui"}
    try:
        wf = json.loads(prompt_json)
        if not isinstance(wf, dict):
            return out
        pos_id = neg_id = None
        for nid, node in wf.items():
            ct = node.get("class_type", "")
            if "KSampler" in ct:
                inp = node.get("inputs", {})
                pr = inp.get("positive")
                nr = inp.get("negative")
                if isinstance(pr, list) and pr: pos_id = str(pr[0])
                if isinstance(nr, list) and nr: neg_id = str(nr[0])
                if inp.get("steps"): out["steps"] = str(inp["steps"])
                if inp.get("cfg"):   out["cfg"]   = str(inp["cfg"])
                smpl = inp.get("sampler_name") or inp.get("sampler")
                if smpl: out["sampler"] = smpl
                seed = inp.get("seed") or inp.get("noise_seed")
                if seed: out["seed"] = str(seed)
                break
        for nid, node in wf.items():
            if node.get("class_type") == "CLIPTextEncode":
                txt = node.get("inputs", {}).get("text", "")
                if isinstance(txt, list): txt = " ".join(str(x) for x in txt if x)
                elif not isinstance(txt, str): txt = str(txt) if txt else ""
                if nid == pos_id:   out["positive"] = txt
                elif nid == neg_id: out["negative"] = txt
    except Exception:
        pass
    return out


def extract_img_meta(fp: Path) -> dict | None:
    """Return generation metadata dict from a PNG or sidecar .params file, or None. Uses cache."""
    if ARGS.skip_meta:
        return None
    try:
        fsize = fp.stat().st_size
    except Exception:
        return None
    cache_key = str(fp) + "|" + str(fsize)
    if cache_key in _META_CACHE:
        return _META_CACHE[cache_key]

    result = None

    # Check for .params sidecar first (written by --fetch-images for JPEG/WebP)
    params_fp = fp.parent / (fp.name + ".params")
    if params_fp.exists():
        try:
            txt = params_fp.read_text(encoding="utf-8", errors="ignore")
            r = _parse_a1111(txt)
            if r.get("positive"):
                result = r
        except Exception:
            pass

    # Fall back to PNG chunk reading
    if result is None and fp.suffix.lower() == ".png":
        texts = _read_png_texts(fp)
        if texts:
            if "parameters" in texts:
                r = _parse_a1111(texts["parameters"])
                if r.get("positive"):
                    result = r
            elif "prompt" in texts:
                r = _parse_comfyui(texts["prompt"])
                if r.get("positive") or r.get("negative"):
                    result = r

    _META_CACHE[cache_key] = result
    return result

# ── CivitAI metadata extraction ───────────────────────────────────────────────
def extract(data: dict) -> dict:
    r = dict(triggers=[], tags=[], base_model="", nsfw=False, nsfw_level=0,
             name="", creator="", stats={}, civitai_id=None, model_id=None, files=[])
    if not data:
        return r
    if "modelVersions" in data:
        r["name"]       = str(data.get("name") or "")
        r["civitai_id"] = data.get("id")
        r["model_id"]   = data.get("id")
        r["nsfw"]       = bool(data.get("nsfw", False))
        r["nsfw_level"] = int(data.get("nsfwLevel") or 0)
        c = data.get("creator") or {}
        if isinstance(c, dict): r["creator"] = str(c.get("username") or "")
        tags = data.get("tags") or []
        r["tags"] = uniq(t for t in tags if isinstance(t, str) and t.strip())
        for mv in (data.get("modelVersions") or []):
            tw = mv.get("trainedWords") or []
            r["triggers"] += [norm(t) for t in (tw if isinstance(tw, list) else [tw]) if t]
            if not r["base_model"]: r["base_model"] = str(mv.get("baseModel") or "")
            if not r["civitai_id"]: r["civitai_id"] = mv.get("id")
            r["files"] += [f["name"] for f in (mv.get("files") or []) if f.get("name")]
        s = data.get("stats") or {}
        r["stats"] = {"downloads": int(s.get("downloadCount") or 0), "thumbsUp": int(s.get("thumbsUpCount") or 0)}
    else:
        r["civitai_id"] = data.get("id")
        r["model_id"]   = data.get("modelId")
        r["base_model"] = str(data.get("baseModel") or "")
        r["nsfw_level"] = int(float(data.get("nsfwLevel") or 0))
        tw = data.get("trainedWords") or []
        r["triggers"] = [norm(t) for t in (tw if isinstance(tw, list) else [tw]) if t]
        m = data.get("model") or {}
        r["name"] = str(m.get("name") or data.get("name") or "")
        r["nsfw"] = bool(m.get("nsfw")) or r["nsfw_level"] > 20
        tags = list(m.get("tags") or []) + list(data.get("tags") or [])
        r["tags"] = uniq(t for t in tags if isinstance(t, str) and t.strip())
        r["files"] = [f["name"] for f in (data.get("files") or []) if f.get("name")]
        s = data.get("stats") or {}
        r["stats"] = {"downloads": int(s.get("downloadCount") or 0), "thumbsUp": int(s.get("thumbsUpCount") or 0)}
    r["triggers"] = uniq(t for t in r["triggers"] if t)
    return r

# ── Directory scan ─────────────────────────────────────────────────────────────
def scan(base: Path) -> list:
    entries = []
    dirs_scanned = 0

    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort(key=str.lower)
        dp = Path(dirpath)

        loras, images, infos = [], [], []
        for f in filenames:
            suf = Path(f).suffix.lower()
            if suf in LORA_EXTS:  loras.append(f)
            elif suf in IMG_EXTS: images.append(f)
            elif is_info(f):      infos.append(dp / f)

        dirs_scanned += 1
        if dirs_scanned % 100 == 0:
            print(f"\r  Scanning... {dirs_scanned} dirs, {len(entries)} LoRA folders found", end="", flush=True)

        if not loras:
            continue

        parsed = [d for d in (load_json(fp) for fp in infos) if d]
        metas  = [extract(d) for d in parsed]

        lora_entries = []
        for lf in sorted(loras, key=str.lower):
            stem = Path(lf).stem
            best = None
            for m in metas:
                if any(fn.lower() == lf.lower() for fn in m["files"]):
                    best = m; break
            if best is None:
                if len(metas) == 1:
                    best = metas[0]
                elif metas:
                    for m in metas:
                        if stem.lower() in (m["name"] or "").lower():
                            best = m; break
                    if best is None: best = metas[0]
            if best is None: best = {}
            rel_p = os.path.relpath(dp / lf, base).replace("\\", "/")
            try:
                _st = (dp / lf).stat()
                fsize = int(_st.st_size)
                date_added = int(_st.st_ctime)
            except Exception:
                fsize = 0
                date_added = 0
            lora_entries.append({
                "filename":   lf,
                "stem":       stem,
                "rel_path":   rel_p,
                "file_size":  fsize,
                "triggers":   best.get("triggers", []),
                "tags":       best.get("tags", []),
                "base_model": best.get("base_model") or "",
                "nsfw":       bool(best.get("nsfw", False)),
                "nsfw_level": int(best.get("nsfw_level") or 0),
                "name":       best.get("name") or stem,
                "creator":    best.get("creator") or "",
                "stats":      best.get("stats") or {},
                "model_id":   best.get("model_id"),
                "date_added": date_added,
            })

        imgs_sorted = sorted(images, key=lambda x: (0 if "preview" in x.lower() else 1, x.lower()))

        # Read metadata for first PNG_META_MAX images (PNG chunks or .params sidecar)
        img_entries = []
        meta_read = 0
        for im in imgs_sorted[:MAX_IMGS]:
            img_fp = dp / im
            meta = None
            if meta_read < PNG_META_MAX:
                is_png     = img_fp.suffix.lower() == ".png"
                has_sidecar = (img_fp.parent / (img_fp.name + ".params")).exists()
                if is_png or has_sidecar:
                    meta = extract_img_meta(img_fp)
                    meta_read += 1
            img_nsfw = False
            if meta:
                def _to_str(v): return v if isinstance(v, str) else (" ".join(str(x) for x in v if x) if isinstance(v, list) else str(v) if v else "")
                combined = " ".join(filter(None, [_to_str(meta.get("positive","")), _to_str(meta.get("negative",""))]))
                img_nsfw = is_nsfw_prompt(combined)
            try:    img_mtime = img_fp.stat().st_mtime
            except: img_mtime = 0
            img_entries.append({"url": rel_url(img_fp), "meta": meta, "nsfw": img_nsfw,
                                 "_mtime": img_mtime, "dup_img": False})

        # Deduplicate by positive prompt — keep newest file, mark others
        _prompt_groups = {}
        for i, entry in enumerate(img_entries):
            pos = ((entry.get("meta") or {}).get("positive") or "").strip().lower()
            if pos:
                _prompt_groups.setdefault(pos, []).append(i)
        for indices in _prompt_groups.values():
            if len(indices) > 1:
                indices.sort(key=lambda i: img_entries[i]["_mtime"], reverse=True)
                for i in indices[1:]:
                    img_entries[i]["dup_img"] = True
        for entry in img_entries:
            del entry["_mtime"]

        rel_folder = os.path.relpath(str(dp), str(base)).replace("\\", "/")
        if rel_folder == ".": rel_folder = ""
        parts = [p for p in rel_folder.split("/") if p]
        category = parts[0] if parts else "(root)"

        toks = [dp.name, rel_folder, category]
        for le in lora_entries:
            toks += [le["filename"], le["name"], le["creator"], le["base_model"]]
            toks += le["triggers"] + le["tags"]
        search_text = " ".join(uniq(t for t in toks if t)).lower()

        nsfw = any(le["nsfw"] for le in lora_entries)
        nsfw_level = max((le["nsfw_level"] for le in lora_entries), default=0)
        base_model = next((le["base_model"] for le in lora_entries if le["base_model"]), "")
        total_size = sum(le.get("file_size", 0) for le in lora_entries)

        entries.append({
            "id":            rel_folder or dp.name,
            "title":         dp.name,
            "folder":        rel_folder,
            "category":      category,
            "loras":         lora_entries,
            "images":        img_entries,
            "image_count":   len(images),
            "search_text":   search_text,
            "has_triggers":  any(le["triggers"] for le in lora_entries),
            "trigger_count": sum(len(le["triggers"]) for le in lora_entries),
            "nsfw":          nsfw,
            "nsfw_level":    nsfw_level,
            "base_model":    base_model,
            "total_size":    total_size,
            "date_added":    max((le.get("date_added", 0) for le in lora_entries), default=0),
        })

    print(f"\r  Scanned {dirs_scanned} dirs -- {len(entries)} LoRA folders found.        ")
    return entries

# ── Wildcard scanner ──────────────────────────────────────────────────────────
def _parse_wc_file(fp: Path) -> list:
    try:
        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
        items = [l.strip() for l in lines
                 if l.strip() and not l.strip().startswith("#") and not l.strip().startswith("//")]
        return items[:500]
    except Exception:
        return []

def scan_wildcards(wc_dir: Path) -> dict:
    """Scan wildcards folder. Returns {group: {name: [items]}}.
    Root-level .txt files → group key "".
    Subfolder .txt files  → group key = subfolder name.
    """
    result: dict = {}
    if not wc_dir.is_dir():
        return result

    # Root-level .txt files
    root = sorted(wc_dir.glob("*.txt"), key=lambda p: p.name.lower())
    if root:
        result[""] = {}
        for fp in root:
            items = _parse_wc_file(fp)
            if items:
                result[""][fp.stem] = items

    # One level of subdirectories
    for sub in sorted(wc_dir.iterdir()):
        if sub.is_dir():
            sub_files = sorted(sub.glob("*.txt"), key=lambda p: p.name.lower())
            if sub_files:
                result[sub.name] = {}
                for fp in sub_files:
                    items = _parse_wc_file(fp)
                    if items:
                        result[sub.name][fp.stem] = items

    return result

# ── Duplicate detection ───────────────────────────────────────────────────────
def detect_duplicates(data: list) -> int:
    """Group entries by model_id or normalized name. Modifies data in-place."""
    from collections import defaultdict
    model_groups: dict = defaultdict(list)
    name_groups:  dict = defaultdict(list)

    for i, entry in enumerate(data):
        for le in entry["loras"]:
            mid = le.get("model_id")
            if mid:
                try: model_groups[int(mid)].append(i)
                except (TypeError, ValueError): pass
        raw = entry["title"]
        normed = re.sub(r'[\s_\-]+[vV]?\d[\d._]*\s*$', '', raw).strip().lower()
        if normed:
            name_groups[normed].append(i)

    dup_set: set = set()
    for mid, idxs in model_groups.items():
        if len(set(idxs)) > 1:
            for i in set(idxs):
                dup_set.add(i)
                if not data[i].get("dup_group"):
                    data[i]["dup_group"] = "model:" + str(mid)

    for name, idxs in name_groups.items():
        unique = list(dict.fromkeys(idxs))
        if len(unique) > 1:
            for i in unique:
                dup_set.add(i)
                if not data[i].get("dup_group"):
                    data[i]["dup_group"] = "name:" + name

    for entry in data:
        entry.setdefault("dup_group", "")

    return len(dup_set)

# ── Prompt pack loader ────────────────────────────────────────────────────────
def load_extra_pack() -> dict:
    if ARGS.prompt_json and ARGS.prompt_json.exists():
        try: return load_json(ARGS.prompt_json) or {}
        except: pass
    auto = BASE_DIR / "prompt_pack.json"
    if auto.exists():
        try: return load_json(auto) or {}
        except: pass
    return {}

# ═══════════════════════════════════════════════════════════════════════════════
# CSS
# ═══════════════════════════════════════════════════════════════════════════════
CSS = """
:root{color-scheme:dark;--bg:#111114;--bg2:#1c1c22;--bg3:#252530;--border:#2e2e3c;
  --text:#e2e2ea;--text2:#7878a0;--accent:#8b5cf6;--accent2:#a78bfa;
  --green:#22c55e;--yellow:#eab308;--red:#ef4444;--r:10px;--tr:.15s ease}
[data-theme=light]{color-scheme:light;--bg:#f0f0f6;--bg2:#fff;--bg3:#e8e8f2;
  --border:#d0d0e0;--text:#111118;--text2:#555570}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);font-size:14px;line-height:1.5;overflow:hidden}
::-webkit-scrollbar{width:7px;height:7px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}
::-webkit-scrollbar-thumb:hover{background:var(--text2)}

/* Toolbar */
#toolbar{position:sticky;top:0;z-index:100;background:var(--bg2);border-bottom:1px solid var(--border);
  padding:7px 10px;display:flex;flex-wrap:wrap;gap:5px;align-items:center}
input,select,button,textarea{font-family:inherit;font-size:13px;background:var(--bg3);color:var(--text);
  border:1px solid var(--border);border-radius:6px;padding:5px 8px;transition:border-color var(--tr)}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--accent)}
button{cursor:pointer}
button:hover{border-color:var(--accent2);color:var(--accent2)}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.primary:hover{background:var(--accent2);border-color:var(--accent2)}
#search{flex:1;min-width:200px;font-size:13px;padding:6px 10px}
.tsep{width:1px;background:var(--border);height:24px;margin:0 1px;flex-shrink:0}
.chk{display:flex;align-items:center;gap:4px;cursor:pointer;font-size:12px;color:var(--text2);user-select:none;white-space:nowrap}
.chk input[type=checkbox]{cursor:pointer;accent-color:var(--accent)}
.chk:hover{color:var(--text)}
input[type=number]{width:52px}

/* Layout */
#layout{display:grid;grid-template-columns:185px 1fr 330px;height:calc(100vh - 48px)}
@media(max-width:1280px){#layout{grid-template-columns:165px 1fr}#sandbox{display:none}}
@media(max-width:860px){#layout{grid-template-columns:1fr}#sidebar{display:none}}

/* Sidebar */
#sidebar{overflow-y:auto;border-right:1px solid var(--border);padding:8px 0}
.sh{padding:4px 12px 6px;font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--text2)}
.cat{display:flex;align-items:center;justify-content:space-between;padding:5px 12px;
  cursor:pointer;border-left:3px solid transparent;transition:all var(--tr);font-size:12px;gap:5px}
.cat:hover{background:var(--bg3)}
.cat.on{border-left-color:var(--accent);color:var(--accent2);background:var(--bg3)}
.cat-n{font-size:10px;color:var(--text2);background:var(--bg3);padding:1px 5px;border-radius:999px;flex-shrink:0}
.cat.on .cat-n{background:var(--accent);color:#fff}
.cat-label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sidelink{display:block;padding:6px 14px;font-size:12px;color:var(--accent2);text-decoration:none;
  border-left:3px solid transparent;transition:all var(--tr)}
.sidelink:hover{border-left-color:var(--accent2);background:var(--bg3)}

/* Main */
#main{overflow-y:auto;padding:10px 12px;display:flex;flex-direction:column}
#stats-bar{font-size:12px;color:var(--text2);margin-bottom:8px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
#stats-bar b{color:var(--text)}

/* Cards */
.card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);
  padding:12px;margin-bottom:10px;transition:border-color var(--tr)}
.card:hover{border-color:var(--accent)}
.ch{display:flex;align-items:flex-start;gap:7px;margin-bottom:8px}
.ct{flex:1;overflow:hidden}
.ctitle{font-size:15px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cfolder{font-size:11px;color:var(--text2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:1px}
.cstats{font-size:11px;color:var(--text2);margin-top:3px;display:flex;gap:8px}
.star{font-size:16px;cursor:pointer;color:var(--text2);user-select:none;transition:color var(--tr);flex-shrink:0}
.star:hover,.star.on{color:var(--yellow)}
/* Manual NSFW toggle */
.nsfw-tog{font-size:13px;cursor:pointer;user-select:none;flex-shrink:0;
  opacity:.35;transition:opacity var(--tr);padding:1px 3px;border-radius:4px}
.nsfw-tog:hover{opacity:.7}
.nsfw-tog.on{opacity:1}
.nsfw-b{font-size:10px;padding:2px 6px;border-radius:4px;background:var(--red);
  color:#fff;font-weight:700;letter-spacing:.04em;flex-shrink:0;align-self:flex-start}

/* LoRA rows */
.lr{border-top:1px solid var(--border);padding-top:9px;margin-top:9px}
.lname{font-family:monospace;font-size:12px;color:var(--accent2);word-break:break-all}
.lcname{font-size:11px;color:var(--text2);margin-top:2px}
.linfo{font-size:11px;color:var(--text2);display:flex;gap:8px;flex-wrap:wrap;margin-top:4px}
.linfo a{color:var(--accent2);text-decoration:none}.linfo a:hover{text-decoration:underline}
.lacts{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px;align-items:center}
.bsm{font-size:11px;padding:3px 7px;border-radius:4px;cursor:pointer;border:1px solid var(--border);
  background:var(--bg3);color:var(--text);transition:all var(--tr)}
.bsm:hover{border-color:var(--accent);color:var(--accent2)}
.usage{font-size:11px;color:var(--text2)}.usage b{color:var(--text)}

/* Tag pills */
.trow{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px;align-items:center}
.tlabel{font-size:11px;color:var(--text2);flex-shrink:0}
.pill{display:inline-flex;align-items:center;background:var(--bg3);border:1px solid var(--border);
  border-radius:999px;padding:2px 9px;font-size:11px;cursor:pointer;
  transition:all var(--tr);user-select:none}
.pill:hover{border-color:var(--accent);color:var(--accent2)}
.pill.trig{border-color:var(--accent);background:rgba(139,92,246,.13);color:var(--accent2)}
.pill.trig:hover{background:rgba(139,92,246,.26)}
.pill.cp{border-color:var(--green)!important;color:var(--green)!important}
.notrig{font-size:12px;color:var(--text2);margin-top:5px}

/* Notes */
.note-w{margin-top:6px}
.note-w textarea{width:100%;min-height:40px;resize:vertical;font-size:12px;padding:5px 8px;background:var(--bg)}

/* Image strip */
.istrip{display:flex;gap:5px;overflow-x:auto;margin-top:10px;padding-bottom:3px;scrollbar-width:thin}
.ithumb{height:var(--thumb-h,165px);width:auto;border-radius:6px;object-fit:cover;cursor:pointer;
  border:2px solid transparent;transition:border-color var(--tr),transform var(--tr);flex-shrink:0}
.ithumb:hover{border-color:var(--accent);transform:scale(1.02)}
.imore{height:var(--thumb-h,165px);display:flex;align-items:center;padding:0 10px;color:var(--text2);font-size:12px;white-space:nowrap}

/* Sandbox */
#sandbox{overflow-y:auto;border-left:1px solid var(--border);padding:11px;display:flex;flex-direction:column;gap:7px}
#sandbox>*{flex-shrink:0}
.sbh{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.09em;color:var(--text2)}
.sbl{font-size:11px;color:var(--text2);margin-bottom:2px}
.sbsel{font-size:12px;font-weight:500;color:var(--accent2);min-height:16px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#sandbox textarea{width:100%;resize:vertical;background:var(--bg);font-size:12px}
.br{display:flex;flex-wrap:wrap;gap:4px}
.div{height:1px;background:var(--border);margin:2px 0}

/* Model tabs */
.mtabs{display:flex;gap:3px;flex-wrap:wrap}
.mtab{font-size:11px;padding:3px 8px;border-radius:5px;cursor:pointer;border:1px solid var(--border);
  background:var(--bg3);color:var(--text2);transition:all var(--tr)}
.mtab:hover{border-color:var(--accent2);color:var(--accent2)}
.mtab.on{background:var(--accent);border-color:var(--accent);color:#fff}
.mpack{display:none;flex-direction:column;gap:5px}
.mpack.on{display:flex}

/* Lightbox */
#lb{position:fixed;inset:0;background:rgba(0,0,0,.94);z-index:1000;
  display:flex;align-items:center;justify-content:center;flex-direction:column;gap:8px;padding:16px}
#lb.h{display:none}
#lbwrap{display:flex;align-items:flex-start;gap:14px;max-width:96vw;max-height:90vh}
#lbimg{max-width:70vw;max-height:85vh;border-radius:8px;object-fit:contain;flex-shrink:0}
#lbmeta{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:8px;
  padding:12px;max-width:340px;max-height:85vh;overflow-y:auto;font-size:12px;color:#ccc;
  display:none;flex-direction:column;gap:8px}
#lbmeta.on{display:flex}
.lbmt{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:rgba(255,255,255,.4);margin-bottom:2px}
.lbmv{font-size:12px;color:#e0e0e0;line-height:1.4;max-height:130px;overflow-y:auto;
  background:rgba(0,0,0,.3);padding:6px 8px;border-radius:5px;white-space:pre-wrap;word-break:break-word}
.lbmc{display:flex;gap:5px;flex-wrap:wrap}
.lbmc button{font-size:11px;padding:3px 8px;background:rgba(255,255,255,.1);
  border:1px solid rgba(255,255,255,.2);color:#fff;border-radius:5px}
.lbmc button:hover{background:rgba(255,255,255,.2)}
.lbsettings{font-size:11px;color:rgba(255,255,255,.6);display:flex;flex-wrap:wrap;gap:6px}
.lbsettings span b{color:rgba(255,255,255,.9)}
#lbnav{display:flex;gap:8px;align-items:center}
#lbnav button{font-size:19px;padding:7px 14px;background:rgba(255,255,255,.08);
  border:1px solid rgba(255,255,255,.15);color:#fff;border-radius:7px}
#lbnav button:hover{background:rgba(255,255,255,.18)}
#lbctr{color:#aaa;font-size:12px;min-width:65px;text-align:center}
#lbclose{position:fixed;top:12px;right:16px;font-size:24px;background:none;border:none;color:#fff;cursor:pointer;line-height:1;padding:4px}

/* Toast */
#toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);
  background:var(--accent);color:#fff;padding:6px 16px;border-radius:18px;
  font-size:13px;opacity:0;pointer-events:none;transition:opacity .2s;z-index:2000}
#toast.show{opacity:1}

/* Misc */
#sentinel{height:48px;display:flex;align-items:center;justify-content:center;color:var(--text2);font-size:12px}
#nores{text-align:center;padding:60px 20px;color:var(--text2);font-size:15px}
#nores.h{display:none}

/* Image wrapper for delete overlay */
.img-wrap{position:relative;flex-shrink:0;height:var(--thumb-h,165px)}
.img-wrap .ithumb{height:100%;width:auto}
.del-img-btn{position:absolute;top:4px;right:4px;background:rgba(180,30,30,.9);
  border:none;color:#fff;border-radius:50%;width:20px;height:20px;
  font-size:13px;line-height:1;cursor:pointer;padding:0;font-family:inherit;
  display:flex;align-items:center;justify-content:center;
  opacity:0;transition:opacity .15s;z-index:2}
.img-wrap:hover .del-img-btn,.del-img-btn.on{opacity:1}
.del-img-btn.on{background:var(--red)}
.ithumb.del-on{opacity:.3;filter:grayscale(.8)}
/* Per-image NSFW toggle */
.nsfw-img-btn{position:absolute;bottom:4px;left:4px;background:rgba(150,60,0,.85);
  border:none;color:#fff;border-radius:4px;padding:2px 5px;
  font-size:9px;font-weight:700;line-height:1.3;cursor:pointer;font-family:inherit;
  opacity:0;transition:opacity .15s;z-index:2}
.img-wrap:hover .nsfw-img-btn,.nsfw-img-btn.on{opacity:1}
.nsfw-img-btn.on{background:var(--red)}
/* NSFW image hiding */
body.hide-nsfw .img-wrap.img-nsfw{display:none}
.img-nsfw-note{display:none;color:var(--text2);font-size:11px;padding:0 8px;
  align-items:center;white-space:nowrap;flex-shrink:0}
body.hide-nsfw .img-nsfw-note{display:flex}
/* Duplicate image hiding */
body.hide-img-dup .img-wrap.img-dedup{display:none}
.img-dedup-note{display:none;color:var(--text2);font-size:11px;padding:0 8px;
  align-items:center;white-space:nowrap;flex-shrink:0}
body.hide-img-dup .img-dedup-note{display:flex}
.img-wrap.img-dedup .ithumb{outline:2px solid var(--yellow)!important;opacity:.6}
/* Duplicate badge */
.dup-b{font-size:10px;padding:2px 6px;border-radius:4px;background:#92400e;
  color:#fde68a;font-weight:700;letter-spacing:.04em;flex-shrink:0;align-self:flex-start;cursor:help}
/* Deletion-marked LoRA row */
.lr.del-on{border-left:3px solid var(--red);opacity:.6}
/* Delete LoRA folder button */
.bdel{font-size:11px;padding:3px 7px;border-radius:4px;cursor:pointer;
  border:1px solid var(--red);background:transparent;color:var(--red);transition:all var(--tr)}
.bdel:hover,.bdel.on{background:var(--red);color:#fff}
/* Deletion counter in toolbar */
#delbtn.has{border-color:var(--red)!important;color:var(--red)!important}
/* Card title is clickable to add to sandbox */
.ctitle{cursor:pointer}
.ctitle:hover{color:var(--accent2)}

/* LoRA Queue */
.sbq-list{display:flex;flex-direction:column;gap:3px;max-height:240px;overflow-y:auto;min-height:0}
.sbq-item{display:flex;align-items:center;gap:4px;background:var(--bg);border:1px solid var(--border);
  border-radius:5px;padding:3px 6px;font-size:11px}
.sbq-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--accent2)}
.sbq-empty{font-size:11px;color:var(--text2);padding:4px 0}
.sbq-w{width:44px;padding:2px 4px;font-size:11px;text-align:center;background:var(--bg3);
  border:1px solid var(--border);border-radius:4px;color:var(--text)}
.sbq-rm{background:none;border:none;color:var(--text2);cursor:pointer;font-size:16px;
  padding:0 2px;line-height:1;flex-shrink:0}
.sbq-rm:hover{color:var(--red)}
/* Prompt history dropdown */
.hist-drop{background:var(--bg2);border:1px solid var(--border);border-radius:6px;
  max-height:190px;overflow-y:auto;display:flex;flex-direction:column}
.hist-drop.h{display:none}
.hist-row{display:flex;gap:6px;padding:5px 8px;cursor:pointer;font-size:11px;align-items:center;border-bottom:1px solid var(--border)}
.hist-row:hover{background:var(--bg3)}
.hist-row:last-child{border-bottom:none}
/* Stats modal */
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:900;
  display:flex;align-items:center;justify-content:center;padding:16px}
.modal-bg.h{display:none}
.modal-box{background:var(--bg2);border:1px solid var(--border);border-radius:10px;
  padding:18px 20px;max-width:580px;width:100%;max-height:85vh;overflow-y:auto;position:relative}
.modal-close{position:absolute;top:10px;right:14px;background:none;border:none;
  color:var(--text2);cursor:pointer;font-size:20px;line-height:1;padding:0}
.modal-close:hover{color:var(--text)}
.stat-h2{font-size:14px;font-weight:700;margin-bottom:10px}
.stat-h{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;
  color:var(--text2);margin:12px 0 5px}
.stat-row{display:flex;align-items:center;gap:7px;margin-bottom:3px;font-size:12px}
.stat-label{width:145px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.stat-bar-wrap{flex:1;background:var(--bg3);border-radius:3px;height:10px}
.stat-bar{background:var(--accent);height:100%;border-radius:3px;min-width:2px}
.stat-val{width:45px;text-align:right;color:var(--text2);flex-shrink:0;font-size:11px}
.stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.stat-card{background:var(--bg3);border-radius:7px;padding:10px;text-align:center}
.stat-card .snum{font-size:20px;font-weight:700;color:var(--accent2)}
.stat-card .slbl{font-size:11px;color:var(--text2);margin-top:2px}
/* Compact grid mode */
body.compact #cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(175px,1fr));gap:6px;align-items:start}
body.compact .card{padding:6px}
body.compact .lr,body.compact .trow,body.compact .note-w,body.compact .lacts,body.compact .cstats{display:none}
body.compact .istrip{margin-top:4px;scrollbar-width:none}
body.compact .istrip::-webkit-scrollbar{display:none}
body.compact .ch{margin-bottom:3px}
body.compact .ctitle{font-size:12px}
body.compact .cfolder{font-size:10px}
body.compact .img-wrap,body.compact .ithumb{height:120px}

/* Wildcards panel */
.wc-group-hdr{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;
  color:var(--text2);padding:5px 0 2px;margin-top:3px;border-bottom:1px solid var(--border)}
.wc-cats-row{display:flex;flex-wrap:wrap;gap:3px;margin:2px 0}
.wc-cat{font-size:11px;padding:2px 8px;border-radius:999px;cursor:pointer;
  border:1px solid var(--border);background:var(--bg3);color:var(--text2);transition:all var(--tr)}
.wc-cat:hover{border-color:var(--accent2);color:var(--accent2)}
.wc-cat.on{border-color:var(--accent);background:rgba(139,92,246,.15);color:var(--accent2);font-weight:600}
.wc-cat.new-f{border-color:var(--green);color:var(--green)}
#wc-cats{max-height:130px;overflow-y:auto;padding-right:2px}
.wc-drop{border:2px dashed var(--border);border-radius:6px;padding:6px 10px;
  text-align:center;font-size:11px;color:var(--text2);cursor:pointer;transition:all var(--tr)}
.wc-drop:hover,.wc-drop.over{border-color:var(--accent);color:var(--accent2);background:rgba(139,92,246,.07)}
#wc-panel{background:var(--bg);border:1px solid var(--border);border-radius:6px;
  padding:7px;display:none;flex-direction:column;gap:5px}
#wc-panel.on{display:flex}
.wc-pname{font-size:11px;font-weight:600;color:var(--accent2)}
.wc-pbtns{display:flex;flex-wrap:wrap;gap:3px;align-items:center}
.wc-vals{display:flex;flex-wrap:wrap;gap:3px;max-height:80px;overflow-y:auto;margin-top:2px}

/* V4 Collections */
.lbl-row{display:flex;flex-wrap:wrap;gap:4px;align-items:center;margin-top:4px;
  padding-top:4px;border-top:1px solid var(--border)}
.lbl-chip{display:inline-flex;align-items:center;gap:3px;background:rgba(34,197,94,.1);
  border:1px solid rgba(34,197,94,.35);border-radius:999px;padding:1px 7px 1px 9px;
  font-size:10px;color:var(--green)}
.lbl-chip .lbl-rm{cursor:pointer;opacity:.55;font-size:13px;line-height:1;padding:0 1px}
.lbl-chip .lbl-rm:hover{opacity:1;color:var(--red)}
.lbl-add{font-size:11px;padding:1px 8px;border-radius:999px;cursor:pointer;
  border:1px dashed var(--border);background:transparent;color:var(--text2);transition:all var(--tr)}
.lbl-add:hover{border-color:var(--green);color:var(--green)}
.lbl-input{font-size:11px;padding:2px 8px;border-radius:999px;width:100px;
  border:1px solid var(--green);color:var(--text);background:var(--bg3);outline:none}
body.compact .lbl-row{display:none}

/* V4 Favorites sidebar */
#favcat{display:flex;align-items:center;justify-content:space-between;padding:5px 12px;
  cursor:pointer;border-left:3px solid transparent;transition:all var(--tr);
  font-size:12px;gap:5px;color:var(--text2)}
#favcat:hover{background:var(--bg3);color:var(--yellow)}
#favcat.on{border-left-color:var(--yellow);color:var(--yellow);background:var(--bg3)}
.fav-n{font-size:10px;color:var(--text2);background:var(--bg3);padding:1px 5px;
  border-radius:999px;flex-shrink:0;transition:all var(--tr)}
#favcat.on .fav-n{background:var(--yellow);color:#111}
.star{font-size:17px;line-height:1;cursor:pointer;user-select:none;transition:color var(--tr);flex-shrink:0}
.star:hover,.star.on{color:var(--yellow)}
.civitai-link{font-size:10px;color:var(--accent2);text-decoration:none;display:inline-block;
  margin-top:2px;opacity:.65;transition:opacity var(--tr)}
.civitai-link:hover{opacity:1;text-decoration:underline}
"""

# ═══════════════════════════════════════════════════════════════════════════════
# HTML body
# ═══════════════════════════════════════════════════════════════════════════════
BODY = """
<div id="toolbar">
  <input id="search" type="text" placeholder="Search LoRAs — AND terms (name, triggers, tags, creator, base model)..." autocomplete="off">
  <button onclick="clearSearch()">x Clear</button>
  <div class="tsep"></div>
  <select id="sort">
    <option value="name">Sort: Name</option>
    <option value="date">Sort: Newest first</option>
    <option value="folder">Sort: Folder</option>
    <option value="triggers">Sort: Triggers</option>
    <option value="usage">Sort: Most used</option>
    <option value="nsfw">Sort: NSFW level</option>
    <option value="size">Sort: Largest</option>
    <option value="favdate">Sort: ★ Fav: Recent</option>
    <option value="likes">Sort: Most Liked</option>
    <option value="downloads">Sort: Most Downloaded</option>
  </select>
  <select id="bmsel"><option value="">All base models</option></select>
  <div class="tsep"></div>
  <label class="chk"><input type="checkbox" id="ckT"> Has triggers</label>
  <label class="chk"><input type="checkbox" id="ckF"> Favs</label>
  <label class="chk"><input type="checkbox" id="ckN" checked> Hide NSFW</label>
  <label class="chk">NSFW max: <input type="number" id="nmax" value="100" min="0" max="100" style="width:48px;margin-left:3px"></label>
  <label class="chk"><input type="checkbox" id="ckD"> Dupes only</label>
  <label class="chk"><input type="checkbox" id="ckU"> Unused only</label>
  <label class="chk" title="Also search your personal notes"><input type="checkbox" id="ckNotes"> +Notes</label>
  <label class="chk" title="Show images with duplicate prompts (auto-marked for deletion)"><input type="checkbox" id="ckShowDup"> Img dupes</label>
  <div class="tsep"></div>
  <button onclick="showRandom()" title="Jump to a random LoRA in current filter">Random</button>
  <button onclick="toggleCompact()" id="compbtn" title="Toggle compact grid / detail view">Compact</button>
  <label class="chk" title="Adjust sample image height (60–300px)">Images: <input type="range" id="thumb-sz" min="60" max="300" value="165" style="width:68px;padding:0;border:none;background:none;cursor:ew-resize;accent-color:var(--accent)"></label>
  <button onclick="showStats()" title="Library statistics">Stats</button>
  <button onclick="toggleTheme()" id="tbtn" title="Toggle dark/light">Moon</button>
  <button onclick="doExport()" title="Copy filtered list to clipboard">Export</button>
  <button id="delbtn" onclick="showDelExport()" title="Download a Python script that moves marked items to _DELETED/">Deletions (0)</button>
</div>

<div id="layout">
  <div id="sidebar">
    <div id="favcat" onclick="toggleFavFilter()" title="Show only favorited LoRAs">
      <span>★ Favorites</span><span id="fav-n" class="fav-n">0</span>
    </div>
    <div class="sh" style="margin-top:8px">Recently Used</div>
    <div id="recent-list"></div>
    <div class="sh" style="margin-top:8px">Collections</div>
    <div id="collist"></div>
    <div class="sh" style="margin-top:8px">Categories</div>
    <div id="catlist"></div>
    <div class="sh" style="margin-top:10px">Tools</div>
    <a class="sidelink" href="https://thetacursed.github.io/Anima-Style-Explorer/" target="_blank">Anima Style Explorer</a>
    <a class="sidelink" href="https://animadex.net/" target="_blank">Animadex.net</a>
  </div>

  <div id="main">
    <div id="stats-bar">
      Showing <b id="ss">0</b> of <b id="st">0</b> folders &nbsp;|&nbsp;
      <b id="sl">0</b> LoRAs &nbsp;|&nbsp; <b id="si">0</b> images
    </div>
    <div id="cards"></div>
    <div id="sentinel">Scroll for more...</div>
    <div id="nores" class="h">No results. Try a different search.</div>
  </div>

  <div id="sandbox">
    <div class="sbh">Prompt Sandbox</div>
    <div class="sbl">LoRA Queue <span id="sq-count" style="font-weight:400;font-size:10px;color:var(--text2)"></span></div>
    <div id="sbq" class="sbq-list"><div class="sbq-empty">Click a card title or "Add to queue" to build your LoRA set</div></div>
    <div class="br">
      <button onclick="sqBuild()" title="Append all LoRA tags + triggers to positive prompt">+ Tags &amp; Triggers</button>
      <button onclick="sqClear()">Clear queue</button>
    </div>
    <div class="sbl">Prompt</div>
    <textarea id="sbp" rows="4" placeholder="Positive prompt..."></textarea>
    <div class="sbl">Negative</div>
    <textarea id="sbn" rows="3" placeholder="Negative prompt..."></textarea>
    <div class="br">
      <button onclick="sbClear()">Clear prompts</button>
      <button class="primary" onclick="sbCopyAndSave()">Copy all</button>
      <button onclick="toggleHistory()" id="histbtn">History</button>
    </div>
    <div id="hist-drop" class="hist-drop h"></div>
    <div class="div"></div>

    <div class="sbh">Presets</div>
    <div class="br">
      <button onclick="savePreset()">Save</button>
      <select id="preset-sel" style="flex:1;font-size:12px;min-width:0" onchange="loadPreset(this.value)"><option value="">Load preset...</option></select>
      <button onclick="deletePreset()">Del</button>
    </div>
    <div class="div"></div>

    <div class="sbh">Quick Inserts</div>
    <div class="sbl">Model preset</div>
    <div class="mtabs" id="mtabs">
      <span class="mtab on" data-model="universal">Universal</span>
      <span class="mtab" data-model="illustrious">Illustrious</span>
      <span class="mtab" data-model="anima">Anima</span>
      <span class="mtab" data-model="pony">Pony</span>
    </div>

    <div id="mpacks"></div>
    <div class="div"></div>

    <div class="sbh">Wildcards <span id="wc-count" style="font-weight:400;font-size:10px;color:var(--text2)"></span></div>
    <input id="wc-search" type="text" placeholder="Filter categories..." style="width:100%;font-size:12px">
    <div id="wc-drop" class="wc-drop">Drop .txt wildcard files here to add / update</div>
    <div id="wc-cats"></div>
    <div id="wc-panel"></div>
    <button onclick="wcClearDropped()" style="font-size:10px;padding:2px 6px;align-self:flex-start;color:var(--text2);border-color:var(--border)">Clear dropped</button>
    <div class="div"></div>
    <div style="font-size:11px;color:var(--text2)">Notes/Favs/Usage saved in browser localStorage.</div>
  </div>
</div>

<!-- Stats modal -->
<div id="stats-modal" class="modal-bg h" onclick="if(event.target===this)this.classList.add('h')">
  <div class="modal-box">
    <button class="modal-close" onclick="document.getElementById('stats-modal').classList.add('h')">x</button>
    <div class="stat-h2">Library Statistics</div>
    <div id="stats-content"></div>
  </div>
</div>

<!-- Lightbox -->
<div id="lb" class="h">
  <button id="lbclose" onclick="lbClose()">x</button>
  <div id="lbwrap">
    <img id="lbimg" src="" alt="">
    <div id="lbmeta">
      <div>
        <div class="lbmt">Positive Prompt</div>
        <div class="lbmv" id="lbpos"></div>
      </div>
      <div>
        <div class="lbmt">Negative Prompt</div>
        <div class="lbmv" id="lbneg"></div>
      </div>
      <div class="lbsettings" id="lbset"></div>
      <div class="lbmc" id="lbbtns"></div>
    </div>
  </div>
  <div id="lbnav">
    <button onclick="lbPrev()">&#8249;</button>
    <span id="lbctr"></span>
    <button onclick="lbNext()">&#8250;</button>
  </div>
</div>
<div id="toast">Copied!</div>
"""

# ═══════════════════════════════════════════════════════════════════════════════
# JavaScript
# ═══════════════════════════════════════════════════════════════════════════════
JS = r"""
const DATA  = __DATA__;
const PACKS = __PACKS__;
const WILDCARDS = __WILDCARDS__;
const BASE_PATH = "__BASE_PATH__";

let filtered=DATA, rendered=0, PAGE=60, _delCount=0;
let _wcData={}, _wcActiveCat=null;
let _queue=[], _compact=false;
let activeCat="", activeLbl="", lbImgs=[], lbIdx=0, stimer=null;
let _obs=null, _rendering=false;

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded",()=>{
  const th=localStorage.getItem("theme");
  if(th){document.documentElement.dataset.theme=th;document.getElementById("tbtn").textContent=th==="light"?"Sun":"Moon";}

  buildBM();
  buildCats();
  buildPacks();

  document.getElementById("mtabs").addEventListener("click",e=>{
    const tab=e.target.closest(".mtab");
    if(!tab)return;
    document.querySelectorAll(".mtab").forEach(t=>t.classList.remove("on"));
    tab.classList.add("on");
    document.querySelectorAll(".mpack").forEach(p=>p.classList.remove("on"));
    const pk=document.getElementById("mp_"+tab.dataset.model);
    if(pk)pk.classList.add("on");
  });

  applyFilter();
  setupObs();
  updateDelCount();
  initWildcards();
  loadQueue();
  refreshPresetSel();
  if(localStorage.getItem("view_compact")==="1"){_compact=true;document.body.classList.add("compact");document.getElementById("compbtn").textContent="Detail";}

  updateFavCount();
  buildCollections();
  buildRecent();

  // Duplicate image visibility
  document.body.classList.add("hide-img-dup");
  if(localStorage.getItem("show_img_dup")==="1"){
    document.getElementById("ckShowDup").checked=true;
    document.body.classList.remove("hide-img-dup");
  }
  document.getElementById("ckShowDup").addEventListener("change",e=>{
    document.body.classList.toggle("hide-img-dup",!e.target.checked);
    localStorage.setItem("show_img_dup",e.target.checked?"1":"0");
  });

  // Thumbnail size restore
  const savedTh=localStorage.getItem("thumb_h");
  if(savedTh){document.documentElement.style.setProperty("--thumb-h",savedTh+"px");document.getElementById("thumb-sz").value=savedTh;}
  document.getElementById("thumb-sz").addEventListener("input",e=>{
    const v=e.target.value;
    document.documentElement.style.setProperty("--thumb-h",v+"px");
    localStorage.setItem("thumb_h",v);
  });

  document.getElementById("search").addEventListener("input",()=>{clearTimeout(stimer);stimer=setTimeout(applyFilter,200);});
  ["sort","bmsel","ckT","ckN","ckD","ckU","ckNotes","nmax"].forEach(id=>document.getElementById(id).addEventListener("change",applyFilter));
  document.getElementById("ckF").addEventListener("change",()=>{updateFavCount();applyFilter();});

  document.getElementById("lb").addEventListener("click",e=>{if(e.target.id==="lb")lbClose();});

  document.addEventListener("keydown",e=>{
    const inText=document.activeElement.tagName==="INPUT"||document.activeElement.tagName==="TEXTAREA";
    if(e.key==="/"&&!inText){e.preventDefault();document.getElementById("search").focus();}
    if(e.key==="Escape"&&!inText){clearSearch();}
    if(!document.getElementById("lb").classList.contains("h")){
      if(e.key==="ArrowLeft"){e.preventDefault();lbPrev();}
      if(e.key==="ArrowRight"){e.preventDefault();lbNext();}
      if(e.key==="Escape"){lbClose();}
    }
  });
});

// ── Base model select ─────────────────────────────────────────────────────────
function buildBM(){
  const sel=document.getElementById("bmsel");
  [...new Set(DATA.map(d=>d.base_model).filter(Boolean))].sort().forEach(m=>{
    const o=document.createElement("option");o.value=m.toLowerCase();o.textContent=m;sel.appendChild(o);
  });
}

// ── Categories ────────────────────────────────────────────────────────────────
function buildCats(){
  const counts={};
  DATA.forEach(d=>{counts[d.category]=(counts[d.category]||0)+1;});
  const el=document.getElementById("catlist");
  el.appendChild(mkCatEl("All","",DATA.length,true));
  Object.entries(counts).sort((a,b)=>a[0].localeCompare(b[0])).forEach(([c,n])=>el.appendChild(mkCatEl(c,c,n,false)));
}
function mkCatEl(label,cat,count,active){
  const d=document.createElement("div");
  d.className="cat"+(active?" on":"");d.dataset.cat=cat;
  d.innerHTML=`<span class="cat-label">${esc(label)}</span><span class="cat-n">${count}</span>`;
  d.onclick=()=>{
    activeCat=cat;
    document.querySelectorAll(".cat").forEach(el=>el.classList.toggle("on",el.dataset.cat===cat));
    applyFilter();
  };
  return d;
}

// ── Model-specific quick inserts ──────────────────────────────────────────────
function buildPacks(){
  const container=document.getElementById("mpacks");
  const models=["universal","illustrious","anima","pony"];
  models.forEach((model,mi)=>{
    const pack=PACKS[model]||{};
    const div=document.createElement("div");
    div.className="mpack"+(mi===0?" on":"");
    div.id="mp_"+model;

    Object.entries(pack).forEach(([section,tags])=>{
      if(!tags||!tags.length)return;
      const label=document.createElement("div");
      label.className="sbl";
      label.style.marginTop="4px";
      const sectionNames={quality:"Quality",negative:"Negative",subjects:"Subjects",
        styles:"Styles",danbooru:"Danbooru Tags",source:"Source"};
      label.textContent=sectionNames[section]||section;
      div.appendChild(label);
      const row=document.createElement("div");row.className="br";
      tags.forEach(tag=>{
        const targetId=section==="negative"?"sbn":"sbp";
        const b=document.createElement("button");
        b.className="bsm";b.textContent=tag;
        b.title="Click: add to "+(section==="negative"?"negative":"positive")+" prompt";
        b.onclick=()=>sbApp(targetId,tag);
        row.appendChild(b);
      });
      div.appendChild(row);
    });

    container.appendChild(div);
  });
}

// ── Filter / search ───────────────────────────────────────────────────────────
function isNSFW(d){return d.nsfw||localStorage.getItem("nsfw_m_"+d.id)==="1";}

function applyFilter(){
  const q=(document.getElementById("search").value||"").toLowerCase().trim();
  const terms=q?q.split(/\s+/):[];
  const ckT=document.getElementById("ckT").checked;
  const ckF=document.getElementById("ckF").checked;
  const ckN=document.getElementById("ckN").checked;
  const ckD=document.getElementById("ckD").checked;
  const ckU=document.getElementById("ckU").checked;
  const ckNotes=document.getElementById("ckNotes").checked;
  const nmax=parseInt(document.getElementById("nmax").value||"100",10);
  const bm=(document.getElementById("bmsel").value||"").toLowerCase();
  const srt=document.getElementById("sort").value;

  filtered=DATA.filter(d=>{
    if(terms.length){
      const inMain=terms.every(t=>d.search_text.includes(t));
      if(!inMain){
        if(!ckNotes)return false;
        const noteText=d.loras.map(le=>(localStorage.getItem("note_"+d.id+"/"+le.filename)||"").toLowerCase()).join(" ");
        if(!terms.every(t=>noteText.includes(t)))return false;
      }
    }
    if(ckT&&!d.has_triggers)return false;
    if(ckF&&!isFav(d.id))return false;
    if(ckN&&isNSFW(d))return false;
    if(!isNaN(nmax)&&d.nsfw_level>nmax)return false;
    if(bm&&d.base_model.toLowerCase()!==bm)return false;
    if(activeCat&&d.category!==activeCat)return false;
    if(activeLbl&&!getLabels(d.id).includes(activeLbl))return false;
    if(ckD&&!d.dup_group)return false;
    if(ckU&&getCardUsage(d.id)>0)return false;
    return true;
  });

  filtered=[...filtered];
  if(srt==="triggers") filtered.sort((a,b)=>b.trigger_count-a.trigger_count);
  else if(srt==="usage")  filtered.sort((a,b)=>getCardUsage(b.id)-getCardUsage(a.id));
  else if(srt==="nsfw")   filtered.sort((a,b)=>b.nsfw_level-a.nsfw_level);
  else if(srt==="folder") filtered.sort((a,b)=>a.folder.localeCompare(b.folder));
  else if(srt==="size")   filtered.sort((a,b)=>(b.total_size||0)-(a.total_size||0));
  else if(srt==="date")   filtered.sort((a,b)=>(b.date_added||0)-(a.date_added||0));
  else if(srt==="favdate") filtered.sort((a,b)=>(parseInt(localStorage.getItem("fav_ts_"+b.id)||"0",10))-(parseInt(localStorage.getItem("fav_ts_"+a.id)||"0",10)));
  else if(srt==="likes")     filtered.sort((a,b)=>(b.loras[0]?.stats?.thumbsUp||0)-(a.loras[0]?.stats?.thumbsUp||0));
  else if(srt==="downloads") filtered.sort((a,b)=>(b.loras[0]?.stats?.downloads||0)-(a.loras[0]?.stats?.downloads||0));
  else filtered.sort((a,b)=>a.title.localeCompare(b.title));

  // Disconnect observer BEFORE clearing cards to prevent it from firing on the
  // now-visible sentinel and triggering a cascade that renders all items at once.
  if(_obs) _obs.disconnect();
  const sen=document.getElementById("sentinel");
  sen.style.display="none";
  document.getElementById("cards").innerHTML="";
  rendered=0;
  _rendering=false;
  renderMore();
  // Reconnect after the current task so layout has settled
  requestAnimationFrame(()=>{if(_obs)_obs.observe(sen);});
  document.body.classList.toggle("hide-nsfw", ckN);
  document.getElementById("nores").classList.toggle("h",filtered.length>0);
  updateStats();
}

function clearSearch(){
  document.getElementById("search").value="";
  ["ckT","ckF","ckN","ckD","ckU","ckNotes"].forEach(id=>document.getElementById(id).checked=false);
  document.getElementById("nmax").value="100";
  document.getElementById("bmsel").value="";
  activeCat="";
  activeLbl="";
  document.querySelectorAll(".cat").forEach(el=>el.classList.toggle("on",el.dataset.cat===""));
  updateFavCount();
  buildCollections();
  applyFilter();
}

// ── Virtual render ────────────────────────────────────────────────────────────
function renderMore(){
  if(_rendering) return;
  _rendering=true;
  const batch=filtered.slice(rendered,rendered+PAGE);
  if(!batch.length){
    document.getElementById("sentinel").style.display="none";
    _rendering=false;
    return;
  }
  const frag=document.createDocumentFragment();
  batch.forEach(d=>{
    try{ frag.appendChild(mkCard(d)); }
    catch(err){ console.error("mkCard error for",d.id,":",err); }
  });
  document.getElementById("cards").appendChild(frag);
  rendered+=batch.length;
  const more=rendered<filtered.length;
  const sen=document.getElementById("sentinel");
  sen.style.display=more?"flex":"none";
  if(more)sen.textContent="Showing "+rendered+" of "+filtered.length+" — scroll for more";
  _rendering=false;
  updateDelCount();
}
function setupObs(){
  _obs=new IntersectionObserver(e=>{
    if(e[0].isIntersecting&&!_rendering) renderMore();
  },{threshold:0,rootMargin:"300px"});
  _obs.observe(document.getElementById("sentinel"));
}

// ── Card builder ──────────────────────────────────────────────────────────────
function mkCard(d){
  const div=document.createElement("div");div.className="card";div.id="card_"+cid(d.id);

  // Header
  const hdr=document.createElement("div");hdr.className="ch";
  const ct=document.createElement("div");ct.className="ct";
  const title=document.createElement("div");title.className="ctitle";title.textContent=d.title;title.title="Click to add to sandbox\n"+d.folder;
  title.addEventListener("click",e=>{
    e.stopPropagation();
    queueAdd(d.loras[0],d.title,d.id);
  });
  const fold=document.createElement("div");fold.className="cfolder";fold.textContent=d.folder||"(root)";
  ct.appendChild(title);ct.appendChild(fold);
  // CivitAI link — shown in both normal and compact mode
  const fl_civ=d.loras.find(le=>le.model_id);
  if(fl_civ){
    const clink=document.createElement("a");
    clink.href="https://civitai.red/models/"+fl_civ.model_id;
    clink.target="_blank";clink.className="civitai-link";clink.textContent="↗ CivitAI";
    clink.onclick=e=>e.stopPropagation();
    ct.appendChild(clink);
  }
  const fl=d.loras[0];
  if(fl&&fl.stats&&(fl.stats.downloads||fl.stats.thumbsUp)){
    const cs=document.createElement("div");cs.className="cstats";
    if(fl.stats.downloads)cs.innerHTML+="Download: "+fl.stats.downloads.toLocaleString()+" ";
    if(fl.stats.thumbsUp) cs.innerHTML+="Likes: "+fl.stats.thumbsUp;
    ct.appendChild(cs);
  }

  // NSFW badge (static from metadata)
  if(d.nsfw||d.nsfw_level>0){
    const b=document.createElement("span");b.className="nsfw-b";
    b.textContent=d.nsfw_level?"NSFW "+d.nsfw_level:"NSFW";hdr.appendChild(b);
  }
  // Duplicate badge
  if(d.dup_group){
    const db=document.createElement("span");db.className="dup-b";
    db.textContent="DUPE";db.title="Possible duplicate — same model found in multiple folders\n"+d.dup_group;
    hdr.appendChild(db);
  }

  // Manual NSFW toggle
  const nsfwTogId=cid(d.id);
  const nsfwTog=document.createElement("span");
  nsfwTog.className="nsfw-tog"+(localStorage.getItem("nsfw_m_"+d.id)==="1"?" on":"");
  nsfwTog.textContent="[18+]";
  nsfwTog.title="Toggle manual NSFW tag (affects Hide NSFW filter)";
  nsfwTog.onclick=()=>toggleManualNSFW(d.id,nsfwTog);
  hdr.appendChild(ct);hdr.appendChild(nsfwTog);

  // Favorite star
  const star=document.createElement("span");
  star.className="star"+(isFav(d.id)?" on":"");
  star.textContent="★";star.title="Toggle favorite";
  star.onclick=()=>toggleFav(d.id,star);
  hdr.appendChild(star);
  div.appendChild(hdr);

  // Labels row
  const lblRow=document.createElement("div");lblRow.className="lbl-row";lblRow.id="lblrow_"+cid(d.id);
  buildLblRow(d.id,lblRow);
  div.appendChild(lblRow);

  // LoRA rows
  d.loras.forEach(le=>{
    const row=document.createElement("div");row.className="lr";
    const nm=document.createElement("div");nm.className="lname";nm.textContent=le.filename;row.appendChild(nm);
    if(le.name&&le.name.toLowerCase()!==le.stem.toLowerCase()){
      const cn=document.createElement("div");cn.className="lcname";cn.textContent=le.name;row.appendChild(cn);
    }
    const info=document.createElement("div");info.className="linfo";
    if(le.base_model)info.innerHTML+="<span>Base: <b>"+esc(le.base_model)+"</b></span>";
    if(le.creator)   info.innerHTML+="<span>By: <a href='#' onclick='filterCreator("+JSON.stringify(le.creator)+");return false' title='Filter to this creator'><b>"+esc(le.creator)+"</b></a></span>";
    if(le.file_size) info.innerHTML+="<span>"+fmtSize(le.file_size)+"</span>";
    if(le.model_id)  info.innerHTML+="<span><a href=\"https://civitai.red/models/"+le.model_id+"\" target=\"_blank\">Civitai</a></span>";
    if(info.innerHTML)row.appendChild(info);

    const acts=document.createElement("div");acts.className="lacts";
    const tag="<lora:"+le.stem+":1>";
    acts.appendChild(bsm("Copy filename",()=>cp(le.filename)));
    acts.appendChild(bsm("Copy <lora>",()=>cp(tag)));
    acts.appendChild(bsm("Add to queue",()=>queueAdd(le,d.title,d.id)));
    const ukey=cid(d.id+"/"+le.filename);
    const ubadge=document.createElement("span");ubadge.className="usage";
    ubadge.id="u_"+ukey;ubadge.innerHTML="Used: <b>"+getLU(d.id,le.filename)+"</b>x";
    acts.appendChild(ubadge);
    // Folder delete button (only for non-root folders)
    if(d.folder){
      const delFKey="del_folder_"+encodeURIComponent(d.folder);
      const isFDel=localStorage.getItem(delFKey)==="1";
      if(isFDel)row.classList.add("del-on");
      const bdel=document.createElement("button");
      bdel.className="bdel"+(isFDel?" on":"");
      bdel.textContent=isFDel?"Unmark":"Delete folder";
      bdel.title="Mark entire LoRA folder for deletion (moves to _DELETED/ when you run the export script)";
      bdel.onclick=()=>{
        const marked=localStorage.getItem(delFKey)==="1";
        if(marked){localStorage.removeItem(delFKey);bdel.classList.remove("on");bdel.textContent="Delete folder";row.classList.remove("del-on");}
        else{localStorage.setItem(delFKey,"1");bdel.classList.add("on");bdel.textContent="Unmark";row.classList.add("del-on");}
        updateDelCount();
      };
      acts.appendChild(bdel);
    }
    row.appendChild(acts);

    // Trigger pills
    if(le.triggers.length){
      const tr=document.createElement("div");tr.className="trow";
      const lb=document.createElement("span");lb.className="tlabel";lb.textContent="Triggers:";tr.appendChild(lb);
      tr.appendChild(bsm("Copy all",()=>{cp(le.triggers.join(", "));bump(d.id,le.filename);}));
      le.triggers.forEach(t=>{tr.appendChild(mkPill(t,true,()=>{cp(t);bump(d.id,le.filename);}));});
      row.appendChild(tr);
    }else{
      const nt=document.createElement("div");nt.className="notrig";nt.textContent="No trigger words found";row.appendChild(nt);
    }

    // Tag pills
    if(le.tags.length){
      const tr2=document.createElement("div");tr2.className="trow";
      const lb2=document.createElement("span");lb2.className="tlabel";lb2.textContent="Tags:";tr2.appendChild(lb2);
      le.tags.slice(0,14).forEach(t=>tr2.appendChild(mkPill(t,false,()=>cp(t))));
      row.appendChild(tr2);
    }

    // Notes
    const nw=document.createElement("div");nw.className="note-w";
    const ta=document.createElement("textarea");ta.placeholder="Your notes...";
    const nk="note_"+d.id+"/"+le.filename;
    ta.value=localStorage.getItem(nk)||"";
    ta.addEventListener("input",()=>localStorage.setItem(nk,ta.value));
    nw.appendChild(ta);row.appendChild(nw);
    div.appendChild(row);
  });

  // Image strip
  if(d.images.length){
    const strip=document.createElement("div");strip.className="istrip";
    d.images.forEach((imgObj,i)=>{
      const src=imgObj.url;
      const nsfwImgKey="nsfw_img_"+src;
      const nsfwManual=localStorage.getItem(nsfwImgKey);
      const isNsfwImg=nsfwManual==="1"||(nsfwManual!=="0"&&imgObj.nsfw);
      const isDupImg=!!imgObj.dup_img;
      const wrap=document.createElement("div");
      wrap.className="img-wrap"+(isNsfwImg?" img-nsfw":"")+(isDupImg?" img-dedup":"");
      const img=document.createElement("img");img.className="ithumb";
      img.src=src;img.loading="lazy";
      img.title=(isDupImg?"Duplicate prompt — ":"")+(imgObj.meta?"Has generation data - ":"")+"Image "+(i+1);
      img.onclick=()=>lbOpen(d.images,i);
      if(imgObj.meta&&!isDupImg)img.style.outline="2px solid rgba(139,92,246,.5)";
      const delImgKey="del_img_"+src;
      // Auto-mark duplicate images for deletion on first encounter
      if(isDupImg&&localStorage.getItem(delImgKey)===null){
        localStorage.setItem(delImgKey,"1");
      }
      if(localStorage.getItem(delImgKey)==="1")img.classList.add("del-on");
      const dBtn=document.createElement("button");
      dBtn.className="del-img-btn"+(localStorage.getItem(delImgKey)==="1"?" on":"");
      dBtn.textContent="x";dBtn.title="Mark/unmark this image for deletion";
      dBtn.onclick=e=>{
        e.stopPropagation();
        const m=localStorage.getItem(delImgKey)==="1";
        if(m){
          // For dup images store "0" (keep) so auto-mark doesn't re-fire on next load
          if(isDupImg)localStorage.setItem(delImgKey,"0");else localStorage.removeItem(delImgKey);
          dBtn.classList.remove("on");img.classList.remove("del-on");
        }else{localStorage.setItem(delImgKey,"1");dBtn.classList.add("on");img.classList.add("del-on");}
        updateDelCount();
      };
      const nBtn=document.createElement("button");
      nBtn.className="nsfw-img-btn"+(isNsfwImg?" on":"");
      nBtn.textContent="18+";nBtn.title="Toggle explicit flag (hides with Hide NSFW)";
      nBtn.onclick=e=>{
        e.stopPropagation();
        const cur=wrap.classList.contains("img-nsfw");
        if(cur){
          if(imgObj.nsfw)localStorage.setItem(nsfwImgKey,"0");
          else localStorage.removeItem(nsfwImgKey);
          wrap.classList.remove("img-nsfw");nBtn.classList.remove("on");
        }else{
          localStorage.setItem(nsfwImgKey,"1");
          wrap.classList.add("img-nsfw");nBtn.classList.add("on");
        }
      };
      wrap.appendChild(img);wrap.appendChild(dBtn);wrap.appendChild(nBtn);
      strip.appendChild(wrap);
    });
    const nsfwImgCount=strip.querySelectorAll(".img-nsfw").length;
    if(nsfwImgCount>0){
      const note=document.createElement("div");note.className="imore img-nsfw-note";
      note.textContent=nsfwImgCount+" explicit image"+(nsfwImgCount>1?"s":"")+" hidden";
      strip.appendChild(note);
    }
    const dupImgCount=strip.querySelectorAll(".img-dedup").length;
    if(dupImgCount>0){
      const note=document.createElement("div");note.className="imore img-dedup-note";
      note.textContent=dupImgCount+" duplicate image"+(dupImgCount>1?"s":"")+" hidden — marked for deletion";
      strip.appendChild(note);
    }
    if(d.image_count>d.images.length){
      const m=document.createElement("div");m.className="imore";
      m.textContent="+"+(d.image_count-d.images.length)+" more";strip.appendChild(m);
    }
    div.appendChild(strip);
  }
  return div;
}

function mkPill(text,isTrig,fn){
  const p=document.createElement("span");
  p.className="pill"+(isTrig?" trig":"");p.textContent=text;p.title="Click to copy";
  p.onclick=()=>{fn();p.classList.add("cp");setTimeout(()=>p.classList.remove("cp"),900);};
  return p;
}
function bsm(label,fn){
  const b=document.createElement("button");b.className="bsm";b.textContent=label;b.onclick=fn;return b;
}

// ── Lightbox with metadata ────────────────────────────────────────────────────
function lbOpen(imgs,idx){
  if(!imgs||!imgs.length) return;
  lbImgs=imgs; lbIdx=Math.min(idx,imgs.length-1);
  lbShow();
  document.getElementById("lb").classList.remove("h");
}
function lbClose(){document.getElementById("lb").classList.add("h");}
function lbShow(){
  if(!lbImgs.length) return;
  const imgObj=lbImgs[lbIdx];
  if(!imgObj||!imgObj.url) return;
  document.getElementById("lbimg").src=imgObj.url;
  document.getElementById("lbctr").textContent=(lbIdx+1)+" / "+lbImgs.length;

  const meta=imgObj.meta;
  const panel=document.getElementById("lbmeta");
  if(meta&&(meta.positive||meta.negative)){
    panel.classList.add("on");
    document.getElementById("lbpos").textContent=meta.positive||"(none)";
    document.getElementById("lbneg").textContent=meta.negative||"(none)";

    // Settings row
    const setEl=document.getElementById("lbset");
    setEl.innerHTML="";
    const settings=[
      ["Steps",meta.steps],["CFG",meta.cfg],["Sampler",meta.sampler],
      ["Seed",meta.seed],["Size",meta.size],["Model",meta.model]
    ];
    settings.forEach(([k,v])=>{
      if(v){const s=document.createElement("span");s.innerHTML=k+": <b>"+esc(String(v))+"</b>";setEl.appendChild(s);}
    });
    if(meta.source){const s=document.createElement("span");s.style.opacity=".5";s.textContent="["+meta.source+"]";setEl.appendChild(s);}

    // Action buttons
    const btns=document.getElementById("lbbtns");btns.innerHTML="";
    if(meta.positive){const b=document.createElement("button");b.textContent="Copy prompt";b.onclick=()=>cp(meta.positive);btns.appendChild(b);}
    if(meta.negative){const b=document.createElement("button");b.textContent="Copy negative";b.onclick=()=>cp(meta.negative);btns.appendChild(b);}
    if(meta.positive||meta.negative){
      const b=document.createElement("button");b.textContent="Send to sandbox";
      b.onclick=()=>{
        if(meta.positive)document.getElementById("sbp").value=meta.positive;
        if(meta.negative)document.getElementById("sbn").value=meta.negative;
        lbClose();toast("Sent to sandbox!");
      };
      btns.appendChild(b);
    }
    if(meta.positive){const b=document.createElement("button");b.textContent="Copy all params";b.onclick=()=>{
      const lines=["PROMPT:\n"+(meta.positive||""),"NEGATIVE:\n"+(meta.negative||"")];
      const s=["steps","cfg","sampler","seed","size","model"].filter(k=>meta[k]).map(k=>k+": "+meta[k]).join(", ");
      if(s)lines.push(s);cp(lines.join("\n\n"));};btns.appendChild(b);}
  }else{
    panel.classList.remove("on");
  }
}
function lbPrev(){lbIdx=(lbIdx-1+lbImgs.length)%lbImgs.length;lbShow();}
function lbNext(){lbIdx=(lbIdx+1)%lbImgs.length;lbShow();}

// ── Clipboard ─────────────────────────────────────────────────────────────────
let _tt=null;
function cp(txt){
  (navigator.clipboard?navigator.clipboard.writeText(txt).catch(()=>_cpFallback(txt)):Promise.resolve(_cpFallback(txt)));
  toast("Copied!");
}
function _cpFallback(txt){
  const ta=document.createElement("textarea");ta.value=txt;
  ta.style.cssText="position:fixed;opacity:0;";document.body.appendChild(ta);
  ta.select();document.execCommand("copy");document.body.removeChild(ta);
}
function toast(msg){
  const el=document.getElementById("toast");el.textContent=msg;el.classList.add("show");
  clearTimeout(_tt);_tt=setTimeout(()=>el.classList.remove("show"),1400);
}

// ── Favorites ─────────────────────────────────────────────────────────────────
function isFav(id){return localStorage.getItem("fav_"+id)==="1";}
function toggleFav(id,el){
  const n=!isFav(id);
  localStorage.setItem("fav_"+id,n?"1":"0");
  if(n)localStorage.setItem("fav_ts_"+id,Date.now().toString());
  else localStorage.removeItem("fav_ts_"+id);
  el.classList.toggle("on",n);
  updateFavCount();
  if(document.getElementById("ckF").checked)applyFilter();
}
function updateFavCount(){
  let n=0;
  for(const k in localStorage){if(k.startsWith("fav_")&&!k.startsWith("fav_ts_")&&localStorage[k]==="1")n++;}
  document.getElementById("fav-n").textContent=n;
  document.getElementById("favcat").classList.toggle("on",document.getElementById("ckF").checked);
}
function toggleFavFilter(){
  const ck=document.getElementById("ckF");
  ck.checked=!ck.checked;
  updateFavCount();
  applyFilter();
}

// ── Collections ────────────────────────────────────────────────────────────────
function getLabels(id){try{return JSON.parse(localStorage.getItem("labels_"+id)||"[]");}catch(e){return[];}}
function addLabel(id,lbl){
  lbl=lbl.trim().toLowerCase();if(!lbl)return;
  const ls=getLabels(id);if(ls.includes(lbl))return;
  ls.push(lbl);localStorage.setItem("labels_"+id,JSON.stringify(ls));
  buildCollections();
}
function removeLabel(id,lbl){
  const ls=getLabels(id).filter(l=>l!==lbl);
  localStorage.setItem("labels_"+id,JSON.stringify(ls));
  buildCollections();
}
function buildLblRow(id,container){
  container.innerHTML="";
  getLabels(id).forEach(lbl=>{
    const chip=document.createElement("span");chip.className="lbl-chip";
    const txt=document.createElement("span");txt.textContent=lbl;
    const rm=document.createElement("span");rm.className="lbl-rm";rm.textContent="\xd7";
    rm.onclick=e=>{e.stopPropagation();removeLabel(id,lbl);buildLblRow(id,container);};
    chip.appendChild(txt);chip.appendChild(rm);container.appendChild(chip);
  });
  const addBtn=document.createElement("button");addBtn.className="lbl-add";addBtn.textContent="+ Label";
  addBtn.onclick=e=>{
    e.stopPropagation();addBtn.style.display="none";
    const inp=document.createElement("input");inp.className="lbl-input";inp.placeholder="label...";inp.type="text";
    inp.onkeydown=ev=>{
      if(ev.key==="Enter"){addLabel(id,inp.value);buildLblRow(id,container);}
      if(ev.key==="Escape"){buildLblRow(id,container);}
    };
    inp.onblur=()=>setTimeout(()=>buildLblRow(id,container),200);
    container.appendChild(inp);inp.focus();
  };
  container.appendChild(addBtn);
}
function buildCollections(){
  const counts={};
  for(const k in localStorage){
    if(!k.startsWith("labels_"))continue;
    try{JSON.parse(localStorage[k]).forEach(l=>{counts[l]=(counts[l]||0)+1;});}catch(e){}
  }
  const el=document.getElementById("collist");if(!el)return;
  el.innerHTML="";
  if(!Object.keys(counts).length){
    const e=document.createElement("div");e.style.cssText="font-size:11px;color:var(--text2);padding:3px 12px";
    e.textContent="No collections yet";el.appendChild(e);return;
  }
  Object.entries(counts).sort((a,b)=>a[0].localeCompare(b[0])).forEach(([lbl,n])=>{
    const d=document.createElement("div");
    d.className="cat"+(activeLbl===lbl?" on":"");
    d.innerHTML=`<span class="cat-label">${esc(lbl)}</span><span class="cat-n">${n}</span>`;
    d.onclick=()=>{activeLbl=activeLbl===lbl?"":lbl;buildCollections();applyFilter();};
    el.appendChild(d);
  });
}

// ── Recently Used ──────────────────────────────────────────────────────────────
function buildRecent(){
  const el=document.getElementById("recent-list");if(!el)return;
  el.innerHTML="";
  const entries=[];
  for(const k in localStorage){
    if(k.startsWith("lu_ts_"))entries.push({id:k.slice(6),ts:parseInt(localStorage[k]||"0",10)});
  }
  if(!entries.length){
    const e=document.createElement("div");e.style.cssText="font-size:11px;color:var(--text2);padding:3px 12px";
    e.textContent="None yet";el.appendChild(e);return;
  }
  entries.sort((a,b)=>b.ts-a.ts).slice(0,8).forEach(({id})=>{
    const d=DATA.find(x=>x.id===id);if(!d)return;
    const a=document.createElement("div");a.className="sidelink";
    a.style.cssText="cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px";
    a.textContent=d.title;a.title=d.folder||d.title;
    a.onclick=()=>jumpToCard(id);
    el.appendChild(a);
  });
}
function jumpToCard(id){
  const idx=filtered.findIndex(d=>d.id===id);
  if(idx===-1){clearSearch();requestAnimationFrame(()=>jumpToCard(id));return;}
  while(rendered<=idx&&rendered<filtered.length)renderMore();
  const el=document.getElementById("card_"+cid(id));
  if(el){
    el.scrollIntoView({behavior:"smooth",block:"center"});
    el.style.transition="box-shadow .1s";el.style.boxShadow="0 0 0 3px var(--accent2)";
    setTimeout(()=>{el.style.boxShadow="";el.style.transition="";},1600);
  }
}

// ── Manual NSFW ───────────────────────────────────────────────────────────────
function toggleManualNSFW(id,el){
  const cur=localStorage.getItem("nsfw_m_"+id)==="1";
  localStorage.setItem("nsfw_m_"+id,cur?"0":"1");
  el.classList.toggle("on",!cur);
  if(document.getElementById("ckN").checked)applyFilter();
}

// ── Usage ─────────────────────────────────────────────────────────────────────
function getLU(cid,fn){return parseInt(localStorage.getItem("use_"+cid+"/"+fn)||"0",10);}
function getCardUsage(cid){return parseInt(localStorage.getItem("uc_"+cid)||"0",10);}
function bump(cardId,fn){
  const k="use_"+cardId+"/"+fn;
  const v=(parseInt(localStorage.getItem(k)||"0",10)+1);
  localStorage.setItem(k,v);
  localStorage.setItem("uc_"+cardId,(getCardUsage(cardId)+1).toString());
  localStorage.setItem("lu_ts_"+cardId,Date.now().toString());
  const el=document.getElementById("u_"+cid(cardId+"/"+fn));
  if(el)el.innerHTML="Used: <b>"+v+"</b>x";
  buildRecent();
}

// ── LoRA Queue ────────────────────────────────────────────────────────────────
function queueAdd(le,cardTitle,cardId){
  if(!le)return;
  if(_queue.find(q=>q.stem===le.stem))return toast(le.filename+" already in queue");
  _queue.push({stem:le.stem,filename:le.filename,triggers:le.triggers||[],cardTitle,weight:1.0});
  if(cardId)localStorage.setItem("lu_ts_"+cardId,Date.now().toString());
  saveQueue();renderQueue();buildRecent();
  toast("Added: "+le.filename);
}
function queueRemove(stem){
  _queue=_queue.filter(q=>q.stem!==stem);
  saveQueue();renderQueue();
}
function renderQueue(){
  const el=document.getElementById("sbq");
  el.innerHTML="";
  const cnt=document.getElementById("sq-count");
  cnt.textContent=_queue.length?"("+_queue.length+")":"";
  if(!_queue.length){
    const e=document.createElement("div");e.className="sbq-empty";
    e.textContent="Click a card title or Add to queue";
    el.appendChild(e);return;
  }
  _queue.forEach(q=>{
    const row=document.createElement("div");row.className="sbq-item";
    const nm=document.createElement("span");nm.className="sbq-name";nm.textContent=q.filename;nm.title=q.cardTitle;
    const w=document.createElement("input");
    w.type="number";w.className="sbq-w";w.value=q.weight;w.min="0.1";w.max="2";w.step="0.05";
    w.addEventListener("change",()=>{q.weight=Math.min(2,Math.max(0.1,parseFloat(w.value)||1));w.value=q.weight;saveQueue();});
    const rm=document.createElement("button");rm.className="sbq-rm";rm.textContent="x";rm.title="Remove";
    rm.onclick=()=>queueRemove(q.stem);
    row.appendChild(nm);row.appendChild(w);row.appendChild(rm);
    el.appendChild(row);
  });
}
function sqBuild(){
  if(!_queue.length)return toast("Queue is empty — add LoRAs first");
  const tags=_queue.map(q=>"<lora:"+q.stem+":"+q.weight+">").join(", ");
  const trigs=[...new Set(_queue.flatMap(q=>q.triggers).filter(Boolean))];
  sbApp("sbp",tags+(trigs.length?", "+trigs.join(", "):""));
  toast("Built "+_queue.length+" LoRA"+ (_queue.length>1?"s":""));
}
function sqClear(){_queue=[];saveQueue();renderQueue();toast("Queue cleared");}
function saveQueue(){localStorage.setItem("lora_queue",JSON.stringify(_queue));}
function loadQueue(){
  try{
    const q=JSON.parse(localStorage.getItem("lora_queue")||"[]");
    if(Array.isArray(q))_queue=q;
  }catch(e){_queue=[];}
  renderQueue();
}

// ── Sandbox ───────────────────────────────────────────────────────────────────
function sbApp(id,txt){const ta=document.getElementById(id);ta.value=ta.value?ta.value.trimEnd()+", "+txt:txt;}
function sbClear(){document.getElementById("sbp").value="";document.getElementById("sbn").value="";}
function sbCopyAndSave(){
  const pos=document.getElementById("sbp").value;
  const neg=document.getElementById("sbn").value;
  if(pos||neg)saveToHistory(pos,neg);
  cp("PROMPT:\n"+pos+"\n\nNEGATIVE:\n"+neg);
}

// ── Presets ───────────────────────────────────────────────────────────────────
function getPresets(){try{return JSON.parse(localStorage.getItem("sb_presets")||"{}");}catch(e){return {};}}
function refreshPresetSel(){
  const sel=document.getElementById("preset-sel");
  const ps=getPresets();
  sel.innerHTML='<option value="">Load preset...</option>';
  Object.keys(ps).sort().forEach(name=>{
    const o=document.createElement("option");o.value=name;o.textContent=name;sel.appendChild(o);
  });
}
function savePreset(){
  const name=prompt("Preset name:");
  if(!name||!name.trim())return;
  const ps=getPresets();
  ps[name.trim()]={positive:document.getElementById("sbp").value,negative:document.getElementById("sbn").value,queue:JSON.parse(JSON.stringify(_queue))};
  localStorage.setItem("sb_presets",JSON.stringify(ps));
  refreshPresetSel();toast("Saved: "+name.trim());
}
function loadPreset(name){
  if(!name)return;
  const p=getPresets()[name];if(!p)return;
  document.getElementById("sbp").value=p.positive||"";
  document.getElementById("sbn").value=p.negative||"";
  if(Array.isArray(p.queue)){_queue=p.queue;saveQueue();renderQueue();}
  document.getElementById("preset-sel").value="";
  toast("Loaded: "+name);
}
function deletePreset(){
  const sel=document.getElementById("preset-sel");const name=sel.value;
  if(!name)return toast("Select a preset first");
  if(!confirm("Delete preset \""+name+"\"?"))return;
  const ps=getPresets();delete ps[name];
  localStorage.setItem("sb_presets",JSON.stringify(ps));
  refreshPresetSel();toast("Deleted: "+name);
}

// ── Prompt history ────────────────────────────────────────────────────────────
function getHistory(){try{return JSON.parse(localStorage.getItem("prompt_history")||"[]");}catch(e){return [];}}
function saveToHistory(pos,neg){
  const hist=getHistory();
  hist.unshift({pos,neg,ts:Date.now()});
  if(hist.length>20)hist.pop();
  localStorage.setItem("prompt_history",JSON.stringify(hist));
}
function toggleHistory(){
  const drop=document.getElementById("hist-drop");
  if(!drop.classList.contains("h")){drop.classList.add("h");return;}
  const hist=getHistory();
  drop.innerHTML="";
  if(!hist.length){
    const e=document.createElement("div");e.style.cssText="font-size:11px;color:var(--text2);padding:6px 8px";e.textContent="No history yet";
    drop.appendChild(e);
  }
  hist.forEach(h=>{
    const row=document.createElement("div");row.className="hist-row";
    const preview=(h.pos||h.neg||"").slice(0,45)+"…";
    const ts=new Date(h.ts).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});
    row.innerHTML='<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc(preview)+'</span>'
      +'<span style="font-size:10px;color:var(--text2);flex-shrink:0">'+ts+'</span>';
    row.onclick=()=>{
      document.getElementById("sbp").value=h.pos||"";
      document.getElementById("sbn").value=h.neg||"";
      drop.classList.add("h");toast("Loaded from history");
    };
    drop.appendChild(row);
  });
  drop.classList.remove("h");
}

// ── Stats ─────────────────────────────────────────────────────────────────────
function updateStats(){
  document.getElementById("ss").textContent=filtered.length;
  document.getElementById("st").textContent=DATA.length;
  document.getElementById("sl").textContent=filtered.reduce((s,d)=>s+d.loras.length,0);
  document.getElementById("si").textContent=filtered.reduce((s,d)=>s+d.image_count,0).toLocaleString();
}

// ── Theme ─────────────────────────────────────────────────────────────────────
function toggleTheme(){
  const dark=document.documentElement.dataset.theme!=="light";
  document.documentElement.dataset.theme=dark?"light":"dark";
  document.getElementById("tbtn").textContent=dark?"Sun":"Moon";
  localStorage.setItem("theme",dark?"light":"dark");
}

// ── Export ────────────────────────────────────────────────────────────────────
function doExport(){
  const lines=filtered.map(d=>{
    const t=d.loras.flatMap(l=>l.triggers);
    return d.folder+"\n  "+d.loras.map(l=>l.filename).join(", ")+"\n  Triggers: "+(t.join(", ")||"(none)");
  });
  cp(lines.join("\n\n"));toast("Exported "+filtered.length+" entries");
}

// ── Deletion management ───────────────────────────────────────────────────────
function updateDelCount(){
  let n=0;
  for(const k in localStorage){if(localStorage[k]==="1"&&(k.startsWith("del_img_")||k.startsWith("del_folder_")))n++;}
  _delCount=n;
  const b=document.getElementById("delbtn");
  b.textContent="Deletions ("+n+")";
  b.classList.toggle("has",n>0);
}
function showDelExport(){
  const imgPaths=[],folderPaths=[];
  for(const k in localStorage){
    if(localStorage[k]!=="1")continue;
    if(k.startsWith("del_img_"))imgPaths.push(decodeURIComponent(k.slice(8)));
    else if(k.startsWith("del_folder_"))folderPaths.push(decodeURIComponent(k.slice(11)));
  }
  if(!imgPaths.length&&!folderPaths.length)return toast("Nothing marked for deletion");
  const blob=new Blob([buildDelScript(imgPaths,folderPaths)],{type:"text/plain"});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="run_deletions.py";a.click();
  toast("Downloaded run_deletions.py ("+_delCount+" items) — run it to move files to _DELETED/");
}
function buildDelScript(imgs,folders){
  const bp=BASE_PATH.replace(/\\/g,"\\\\");
  const L=[
    "# LoRA Gallery - Deletion Script",
    "# Moves marked items to _DELETED/ subfolder (reversible!)",
    "# Run: python run_deletions.py",
    "import shutil","from pathlib import Path","",
    "BASE=Path(\""+bp+"\")",
    "TRASH=BASE/\"_DELETED\"","TRASH.mkdir(parents=True,exist_ok=True)","",
  ];
  if(imgs.length){
    L.push("# Images to delete ("+imgs.length+")","images=[");
    imgs.forEach(p=>L.push("  \""+p.replace(/\\/g,"\\\\").replace(/"/g,'\\"')+"\","));
    L.push("]","for rel in images:",
      "  src=BASE/rel","  if src.exists():",
      "    dst=TRASH/rel","    dst.parent.mkdir(parents=True,exist_ok=True)",
      "    shutil.move(str(src),str(dst))","    print('Moved image:',src.name)","");
  }
  if(folders.length){
    L.push("# LoRA folders to delete ("+folders.length+")","folders=[");
    folders.forEach(p=>L.push("  \""+p.replace(/\\/g,"\\\\").replace(/"/g,'\\"')+"\","));
    L.push("]","for rel in folders:",
      "  src=BASE/rel","  if src.is_dir():",
      "    dst=TRASH/rel","    dst.parent.mkdir(parents=True,exist_ok=True)",
      "    shutil.move(str(src),str(dst))","    print('Moved folder:',rel)","");
  }
  L.push("print('Done! "+imgs.length+" images, "+folders.length+" folders moved to _DELETED/')");
  L.push("input('Press Enter to close...')");
  return L.join("\n");
}

// ── Wildcards ─────────────────────────────────────────────────────────────────
function initWildcards(){
  buildWcData();
  renderWcCats();
  setupWcDrop();
  document.getElementById("wc-search").addEventListener("input",renderWcCats);
}

function buildWcData(){
  // Deep copy built-in data, merge localStorage-dropped files
  _wcData={};
  Object.entries(WILDCARDS).forEach(([g,cats])=>{_wcData[g]=Object.assign({},cats);});
  try{
    const dropped=JSON.parse(localStorage.getItem("wc_dropped")||"{}");
    if(Object.keys(dropped).length)_wcData["[dropped]"]=dropped;
  }catch(e){}
}

function renderWcCats(){
  const q=(document.getElementById("wc-search").value||"").toLowerCase();
  const el=document.getElementById("wc-cats");
  el.innerHTML="";
  let totalFiles=0,totalOpts=0;

  Object.entries(_wcData).forEach(([group,cats])=>{
    const matched=Object.entries(cats).filter(([name])=>!q||name.toLowerCase().includes(q)||group.toLowerCase().includes(q));
    if(!matched.length)return;

    if(group){
      const hdr=document.createElement("div");hdr.className="wc-group-hdr";
      hdr.textContent=group==="[dropped]"?"Dropped files (session)":group;
      el.appendChild(hdr);
    }

    const row=document.createElement("div");row.className="wc-cats-row";
    matched.forEach(([name,items])=>{
      totalFiles++;totalOpts+=items.length;
      const isDropped=group==="[dropped]";
      const isActive=_wcActiveCat&&_wcActiveCat.g===group&&_wcActiveCat.n===name;
      const chip=document.createElement("span");
      chip.className="wc-cat"+(isActive?" on":"")+(isDropped?" new-f":"");
      chip.textContent=name;
      chip.title=items.slice(0,6).join(", ")+(items.length>6?"…":"");
      chip.onclick=()=>selectWcCat(group,name,items,chip);
      row.appendChild(chip);
    });
    el.appendChild(row);
  });

  const count=document.getElementById("wc-count");
  count.textContent=totalFiles?"("+totalFiles+" files, "+totalOpts+" options)":"(none)";
}

function selectWcCat(group,name,items){
  // Toggle off if same category
  if(_wcActiveCat&&_wcActiveCat.g===group&&_wcActiveCat.n===name){
    _wcActiveCat=null;
    const panel=document.getElementById("wc-panel");
    panel.classList.remove("on");panel.innerHTML="";
    renderWcCats();return;
  }
  _wcActiveCat={g:group,n:name};
  renderWcCats();
  renderWcPanel(name,items);
}

function renderWcPanel(name,items){
  const panel=document.getElementById("wc-panel");
  panel.classList.add("on");panel.innerHTML="";

  // Header row
  const hdr=document.createElement("div");hdr.className="wc-pbtns";
  const nm=document.createElement("span");nm.className="wc-pname";
  nm.textContent="__"+name+"__  ("+items.length+" options)";
  hdr.appendChild(nm);

  const mkB=(lbl,fn)=>{const b=document.createElement("button");b.className="bsm";b.textContent=lbl;b.onclick=fn;return b;};
  hdr.appendChild(mkB("Rand →P",()=>wcRand("sbp",items)));
  hdr.appendChild(mkB("Rand →N",()=>wcRand("sbn",items)));
  hdr.appendChild(mkB("Insert token",()=>{sbApp("sbp","__"+name+"__");toast("Inserted __"+name+"__");}));
  panel.appendChild(hdr);

  // Value pills (capped for performance)
  const vals=document.createElement("div");vals.className="wc-vals";
  const CAP=100;
  items.slice(0,CAP).forEach(v=>{
    const p=document.createElement("span");p.className="pill";
    p.textContent=v;p.title="Click to insert into positive prompt";
    p.onclick=()=>{sbApp("sbp",v);p.classList.add("cp");setTimeout(()=>p.classList.remove("cp"),700);toast("Inserted: "+v);};
    vals.appendChild(p);
  });
  if(items.length>CAP){
    const more=document.createElement("span");
    more.style.cssText="font-size:11px;color:var(--text2);padding:2px 6px;align-self:center";
    more.textContent="+"+(items.length-CAP)+" more — use Random or search";
    vals.appendChild(more);
  }
  panel.appendChild(vals);
}

function wcRand(targetId,items){
  if(!items.length)return;
  const pick=items[Math.floor(Math.random()*items.length)];
  sbApp(targetId,pick);
  toast("Random: "+pick);
}

function setupWcDrop(){
  const drop=document.getElementById("wc-drop");
  ["dragenter","dragover"].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add("over");}));
  ["dragleave","dragend"].forEach(ev=>drop.addEventListener(ev,()=>drop.classList.remove("over")));
  drop.addEventListener("drop",e=>{
    e.preventDefault();drop.classList.remove("over");
    const files=Array.from(e.dataTransfer.files).filter(f=>f.name.toLowerCase().endsWith(".txt"));
    if(!files.length)return toast("Drop .txt files only");
    let loaded=0;
    const dropped=JSON.parse(localStorage.getItem("wc_dropped")||"{}");
    files.forEach(file=>{
      const reader=new FileReader();
      reader.onload=ev=>{
        const items=ev.target.result.split(/\r?\n/)
          .map(l=>l.trim()).filter(l=>l&&!l.startsWith("#")&&!l.startsWith("//"));
        const name=file.name.replace(/\.txt$/i,"");
        dropped[name]=items.slice(0,500);
        loaded++;
        if(loaded===files.length){
          localStorage.setItem("wc_dropped",JSON.stringify(dropped));
          buildWcData();renderWcCats();
          toast("Added "+loaded+" wildcard file"+(loaded>1?"s":"")+" (session)");
        }
      };
      reader.readAsText(file);
    });
  });
}

function wcClearDropped(){
  localStorage.removeItem("wc_dropped");
  buildWcData();renderWcCats();
  const panel=document.getElementById("wc-panel");
  panel.classList.remove("on");panel.innerHTML="";
  _wcActiveCat=null;
  toast("Cleared dropped wildcards");
}

// ── Random LoRA ───────────────────────────────────────────────────────────────
function showRandom(){
  if(!filtered.length)return toast("No LoRAs in current filter");
  const d=filtered[Math.floor(Math.random()*filtered.length)];
  const idx=filtered.indexOf(d);
  // Ensure it's rendered
  while(rendered<=idx&&rendered<filtered.length)renderMore();
  const el=document.getElementById("card_"+cid(d.id));
  if(el){
    el.scrollIntoView({behavior:"smooth",block:"center"});
    el.style.transition="box-shadow .1s";
    el.style.boxShadow="0 0 0 3px var(--accent2)";
    setTimeout(()=>{el.style.boxShadow="";el.style.transition="";},1600);
  }
  toast("Random: "+d.title);
}

// ── Creator filter ────────────────────────────────────────────────────────────
function filterCreator(name){
  document.getElementById("search").value=name;
  applyFilter();
  toast("Filtering by creator: "+name);
}

// ── Compact mode ──────────────────────────────────────────────────────────────
function toggleCompact(){
  _compact=!_compact;
  document.body.classList.toggle("compact",_compact);
  document.getElementById("compbtn").textContent=_compact?"Detail":"Compact";
  localStorage.setItem("view_compact",_compact?"1":"0");
}

// ── Stats dashboard ───────────────────────────────────────────────────────────
function showStats(){
  const modal=document.getElementById("stats-modal");
  modal.classList.remove("h");
  const byModel={},byCat={},byCreator={};
  let totalSize=0,usedCount=0,totalLoras=0;
  DATA.forEach(d=>{
    totalLoras+=d.loras.length;
    totalSize+=(d.total_size||0);
    if(getCardUsage(d.id)>0)usedCount++;
    const bm=d.base_model||(d.loras[0]?.base_model)||"(unknown)";
    byModel[bm]=(byModel[bm]||0)+d.loras.length;
    byCat[d.category]=(byCat[d.category]||0)+1;
    d.loras.forEach(le=>{if(le.creator)byCreator[le.creator]=(byCreator[le.creator]||0)+1;});
  });
  const cont=document.getElementById("stats-content");cont.innerHTML="";
  // Summary cards
  const grid=document.createElement("div");grid.className="stat-grid";
  [[DATA.length,"Folders"],[totalLoras,"LoRAs"],
   [usedCount+" / "+DATA.length,"Folders used"],
   [totalSize?fmtSize(totalSize):"n/a","Total size"]
  ].forEach(([n,l])=>{
    const c=document.createElement("div");c.className="stat-card";
    c.innerHTML='<div class="snum">'+n+'</div><div class="slbl">'+l+'</div>';
    grid.appendChild(c);
  });
  cont.appendChild(grid);
  // Bar chart helper
  function bars(title,data,n=10){
    const h=document.createElement("div");h.className="stat-h";h.textContent=title;cont.appendChild(h);
    const sorted=Object.entries(data).sort((a,b)=>b[1]-a[1]).slice(0,n);
    const mx=sorted[0]?.[1]||1;
    sorted.forEach(([lbl,v])=>{
      const row=document.createElement("div");row.className="stat-row";
      const l=document.createElement("span");l.className="stat-label";l.textContent=lbl;l.title=lbl;
      const bw=document.createElement("div");bw.className="stat-bar-wrap";
      const b=document.createElement("div");b.className="stat-bar";b.style.width=(v/mx*100).toFixed(1)+"%";
      bw.appendChild(b);
      const val=document.createElement("span");val.className="stat-val";val.textContent=v;
      row.appendChild(l);row.appendChild(bw);row.appendChild(val);cont.appendChild(row);
    });
  }
  bars("LoRAs by Base Model",byModel);
  bars("Folders by Category (top 10)",byCat);
  bars("LoRAs by Creator (top 10)",byCreator);
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function fmtSize(b){
  if(!b)return"";
  if(b>=1e9)return(b/1e9).toFixed(2)+" GB";
  if(b>=1e6)return(b/1e6).toFixed(1)+" MB";
  return Math.round(b/1e3)+" KB";
}
function esc(s){return(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
function cid(s){return(s||"").replace(/[^a-zA-Z0-9_-]/g,"_");}
"""

# ── CivitAI metadata updater ──────────────────────────────────────────────────
def update_civitai_metadata(base: Path):
    """Re-fetch CivitAI metadata with folder picker, change detection, and update report."""
    import urllib.request, urllib.error

    HEADERS = {"User-Agent": "LoRAGallery/5 (local gallery tool)"}
    DELAY   = 0.1   # seconds between requests

    # ── Folder picker ──────────────────────────────────────────────────────────
    top_dirs = sorted(
        [d for d in base.iterdir() if d.is_dir() and not d.name.startswith("_")],
        key=lambda d: d.name.lower()
    )
    print("\n  Which folder to update?")
    print("  [0] All folders")
    for i, d in enumerate(top_dirs, 1):
        print(f"  [{i}] {d.name}")
    raw = input("\n  Enter number (default=0 for all): ").strip()
    try:
        idx = int(raw) if raw else 0
        scan_root = top_dirs[idx - 1] if 1 <= idx <= len(top_dirs) else base
    except (ValueError, IndexError):
        scan_root = base
    scope_label = scan_root.name if scan_root != base else "ALL folders"
    print(f"\n  Updating: {scope_label}\n")

    # ── Helpers ────────────────────────────────────────────────────────────────
    def civitai_url(data: dict) -> str:
        mid = data.get("id") if "modelVersions" in data else data.get("modelId")
        return f"https://civitai.red/models/{mid}" if mid else ""

    def fetch_url(data: dict):
        if "modelVersions" in data:
            mid = data.get("id")
            return (f"https://civitai.com/api/v1/models/{mid}", mid) if mid else (None, None)
        mid = data.get("modelId")
        vid = data.get("id")
        if mid:
            return f"https://civitai.com/api/v1/models/{mid}", mid
        if vid:
            return f"https://civitai.com/api/v1/model-versions/{vid}", None
        return None, None

    def get_triggers(data: dict) -> set:
        if "modelVersions" in data:
            versions = data.get("modelVersions") or []
            return set(versions[0].get("trainedWords") or []) if versions else set()
        return set(data.get("trainedWords") or [])

    def detect_changes(old: dict, new: dict) -> list:
        """Return list of human-readable change tags. Empty = unchanged."""
        flags = []
        old_v = old.get("modelVersions") or [] if "modelVersions" in old else []
        new_v = new.get("modelVersions") or [] if "modelVersions" in new else []
        if len(new_v) > len(old_v):
            tag = new_v[0].get("name", "") if new_v else ""
            flags.append("NEW VERSION" + (f": {tag}" if tag else ""))
        old_ts = old.get("updatedAt", "")
        new_ts = new.get("updatedAt", "")
        if new_ts and old_ts and new_ts != old_ts and not flags:
            flags.append("UPDATED")
        added   = get_triggers(new) - get_triggers(old)
        removed = get_triggers(old) - get_triggers(new)
        if added:
            flags.append("+triggers: " + ", ".join(sorted(added)[:4]))
        if removed:
            flags.append("-triggers: " + ", ".join(sorted(removed)[:4]))
        return flags

    # ── Walk & fetch ───────────────────────────────────────────────────────────
    changed = skipped = errors = unchanged = 0
    report_lines = [f"CivitAI Update Report  —  {scope_label}", "=" * 52, ""]

    for dirpath, dirnames, filenames in os.walk(scan_root):
        dirnames.sort(key=str.lower)
        dp = Path(dirpath)
        info_files = [dp / f for f in filenames if is_info(f)]
        if not info_files:
            continue

        for info_fp in info_files:
            old_data = load_json(info_fp) or {}
            url, _   = fetch_url(old_data)
            if not url:
                skipped += 1
                continue

            try:
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    raw = resp.read().decode("utf-8")
                new_data = json.loads(raw)

                flags    = detect_changes(old_data, new_data) if old_data else ["NEW"]
                page_url = civitai_url(new_data) or civitai_url(old_data)
                name     = (new_data.get("name") or old_data.get("name") or info_fp.stem)

                info_fp.write_text(raw, encoding="utf-8")

                if flags:
                    changed += 1
                    tag_str = " | ".join(flags)
                    line = f"  [{tag_str}]  {name}"
                    if page_url:
                        line += f"\n    {page_url}"
                    print(line)
                    report_lines.append(line)
                else:
                    unchanged += 1

            except urllib.error.HTTPError as e:
                errors += 1
                page_url = civitai_url(old_data)
                line = f"  [HTTP {e.code}]  {info_fp.stem}"
                if page_url:
                    line += f"\n    {page_url}"
                print(line)
                report_lines.append(line)
            except Exception as e:
                errors += 1
                line = f"  [ERROR]  {info_fp.name}: {e}"
                print(line)
                report_lines.append(line)

            time.sleep(DELAY)

    # ── Summary & report file ──────────────────────────────────────────────────
    summary = (f"\n  Done: {changed} changed, {unchanged} unchanged, "
               f"{skipped} skipped (no ID), {errors} errors")
    print(summary)
    report_lines += ["", "=" * 52, summary.strip()]

    report_path = base / "_civitai_update_report.txt"
    try:
        report_path.write_text("\n".join(report_lines), encoding="utf-8")
        print(f"  Report saved → {report_path.name}")
    except Exception:
        pass
    print()

# ── CivitAI image fetcher ──────────────────────────────────────────────────────
def fetch_civitai_images(base: Path, count: int):
    """Download top-reacted CivitAI images for each LoRA folder, with A1111 metadata sidecars."""
    import urllib.request, urllib.error

    HEADERS   = {"User-Agent": "LoRAGallery/5 (local gallery tool)"}
    API_DELAY = 0.1   # between model API calls
    IMG_DELAY = 0.1   # between image downloads

    # ── Folder picker ──────────────────────────────────────────────────────────
    top_dirs = sorted(
        [d for d in base.iterdir() if d.is_dir() and not d.name.startswith("_")],
        key=lambda d: d.name.lower()
    )
    print("\n  Which folder to fetch images for?")
    print("  [0] All folders")
    for i, d in enumerate(top_dirs, 1):
        print(f"  [{i}] {d.name}")
    raw = input("\n  Enter number (default=0 for all): ").strip()
    try:
        idx = int(raw) if raw else 0
        scan_root = top_dirs[idx - 1] if 1 <= idx <= len(top_dirs) else base
    except (ValueError, IndexError):
        scan_root = base
    scope_label = scan_root.name if scan_root != base else "ALL folders"
    print(f"\n  Fetching top {count} images for: {scope_label}\n")

    # ── Helpers ────────────────────────────────────────────────────────────────
    def get_ids(data: dict):
        """Return (model_id, version_id) — prefer version for targeted image results."""
        if "modelVersions" in data:
            model_id   = data.get("id")
            versions   = data.get("modelVersions") or []
            version_id = versions[0].get("id") if versions else None
            return model_id, version_id
        return data.get("modelId"), data.get("id")

    def build_params(meta: dict) -> str:
        """Convert CivitAI image meta dict to A1111-format text for .params sidecar."""
        pos = (meta.get("prompt") or "").strip()
        neg = (meta.get("negativePrompt") or "").strip()
        settings = []
        for key, label in [("steps","Steps"), ("cfgScale","CFG scale"), ("sampler","Sampler"),
                            ("seed","Seed"), ("Size","Size"), ("Model","Model")]:
            v = meta.get(key)
            if v is not None:
                settings.append(f"{label}: {v}")
        lines = []
        if pos:            lines.append(pos)
        if neg:            lines.append(f"Negative prompt: {neg}")
        if settings:       lines.append(", ".join(settings))
        return "\n".join(lines)

    # ── Walk & fetch ───────────────────────────────────────────────────────────
    dl_total = already = skipped = errors = 0

    for dirpath, dirnames, filenames in os.walk(scan_root):
        dirnames.sort(key=str.lower)
        dp = Path(dirpath)
        info_files = [dp / f for f in filenames if is_info(f)]
        if not info_files:
            continue

        info_data = next((d for d in (load_json(fp) for fp in info_files) if d), None)
        if not info_data:
            continue

        model_id, version_id = get_ids(info_data)
        if not model_id and not version_id:
            skipped += 1
            continue

        # Image list API — prefer version ID for focused results
        if version_id:
            api_url = (f"https://civitai.com/api/v1/images"
                       f"?modelVersionId={version_id}"
                       f"&sort=Most+Reactions&limit={count}&nsfw=true")
        else:
            api_url = (f"https://civitai.com/api/v1/images"
                       f"?modelId={model_id}"
                       f"&sort=Most+Reactions&limit={count}&nsfw=true")

        try:
            req = urllib.request.Request(api_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                items = json.loads(resp.read().decode("utf-8")).get("items", [])
        except Exception as e:
            errors += 1
            print(f"  [ERROR] {dp.name}: {e}")
            time.sleep(API_DELAY)
            continue

        if not items:
            skipped += 1
            time.sleep(API_DELAY)
            continue

        time.sleep(API_DELAY)

        dl_this = 0
        for rank, item in enumerate(items[:count], 1):
            img_url = item.get("url", "")
            if not img_url:
                continue
            # Infer extension from URL path
            url_stem = img_url.split("?")[0].split("/")[-1]
            ext = Path(url_stem).suffix.lower()
            if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
                ext = ".jpg"

            out_img    = dp / f"_civitai_top_{rank}{ext}"
            out_params = dp / f"_civitai_top_{rank}{ext}.params"

            if out_img.exists():
                already += 1
                continue

            try:
                req = urllib.request.Request(img_url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    out_img.write_bytes(resp.read())

                meta_dict = item.get("meta") or {}
                if meta_dict:
                    params_txt = build_params(meta_dict)
                    if params_txt:
                        out_params.write_text(params_txt, encoding="utf-8")

                dl_this   += 1
                dl_total  += 1
            except Exception as e:
                errors += 1
                print(f"  [ERROR] {dp.name} img {rank}: {e}")

            time.sleep(IMG_DELAY)

        if dl_this:
            name = (info_data.get("name")
                    or (info_data.get("model") or {}).get("name")
                    or dp.name)
            print(f"  +{dl_this}  {name}")

    print(f"\n  Done: {dl_total} images downloaded, {already} already existed, "
          f"{skipped} skipped (no ID or no images), {errors} errors\n")

# ── Build & write ─────────────────────────────────────────────────────────────
def main():
    print("LoRA Gallery V5")
    print("Base dir : " + str(BASE_DIR))
    print("Out file : " + str(OUT_FILE))
    print()

    t0 = time.perf_counter()

    if ARGS.update_civitai:
        print("Fetching updated metadata from CivitAI...")
        update_civitai_metadata(BASE_DIR)

    if ARGS.fetch_images > 0:
        print(f"Fetching top {ARGS.fetch_images} CivitAI images per LoRA...")
        fetch_civitai_images(BASE_DIR, ARGS.fetch_images)

    _load_cache()
    data     = scan(BASE_DIR)
    _save_cache()
    dup_count = detect_duplicates(data)
    extra    = load_extra_pack()

    wc_dir = (ARGS.wildcards_dir or BASE_DIR / "wildcards").resolve()
    wildcards = scan_wildcards(wc_dir)
    wc_file_count = sum(len(cats) for cats in wildcards.values())
    wc_opt_count  = sum(len(v) for cats in wildcards.values() for v in cats.values())
    print(f"  Wildcards    : {wc_file_count} files, {wc_opt_count} options (from {wc_dir})")

    # Merge extra pack into PACKS
    packs = dict(PROMPT_PACKS)
    for model, sections in extra.items():
        if model in packs and isinstance(sections, dict):
            for section, tags in sections.items():
                packs[model][section] = list(packs[model].get(section, [])) + list(tags)
        elif isinstance(sections, list):
            packs.setdefault("universal", {}).setdefault("quality", []).extend(sections)

    data_json      = json.dumps(data,      ensure_ascii=False, separators=(",", ":"))
    packs_json     = json.dumps(packs,     ensure_ascii=False, separators=(",", ":"))
    wildcards_json = json.dumps(wildcards, ensure_ascii=False, separators=(",", ":"))

    base_path_js = str(BASE_DIR).replace("\\", "\\\\")
    js_final = (JS
        .replace("__DATA__",      data_json)
        .replace("__PACKS__",     packs_json)
        .replace("__WILDCARDS__", wildcards_json)
        .replace("__BASE_PATH__", base_path_js)
    )

    html_out = (
        '<!DOCTYPE html>\n'
        '<html data-theme="dark">\n'
        '<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '<title>LoRA Gallery V5</title>\n'
        '<style>' + CSS + '</style>\n'
        '</head>\n'
        '<body>\n'
        + BODY +
        '\n<script>\n' + js_final + '\n</script>\n'
        '</body>\n</html>'
    )

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(html_out, encoding="utf-8")

    elapsed = time.perf_counter() - t0
    total_loras  = sum(len(d["loras"]) for d in data)
    total_images = sum(d["image_count"] for d in data)
    with_meta    = sum(1 for d in data for img in d["images"] if img.get("meta"))

    print()
    print("Done in " + f"{elapsed:.1f}s")
    print("   Folders      : " + str(len(data)))
    print("   LoRAs        : " + str(total_loras))
    print("   Images       : " + f"{total_images:,}")
    print("   With PNG meta: " + str(with_meta))
    print("   Duplicates   : " + str(dup_count) + " flagged")
    print("   Output       : " + str(OUT_FILE))
    print("   Size         : " + f"{OUT_FILE.stat().st_size/1024/1024:.1f} MB")

if __name__ == "__main__":
    main()
