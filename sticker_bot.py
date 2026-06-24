import gzip
import json
import os
import tempfile
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)

# ── Config ──────────────────────────────────────────────
API_ID    = int(os.environ.get("API_ID", "0"))
API_HASH  = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
# ────────────────────────────────────────────────────────

app = Client("sticker_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

sessions: dict = {}

# ── Color presets (RGBA 0.0-1.0) ─────────────────────────
COLORS = {
    "🔴 Red":    [1.0, 0.0, 0.0, 1.0],
    "🟢 Green":  [0.0, 0.8, 0.0, 1.0],
    "🔵 Blue":   [0.0, 0.3, 1.0, 1.0],
    "⚪ White":  [1.0, 1.0, 1.0, 1.0],
    "⚫ Black":  [0.0, 0.0, 0.0, 1.0],
    "🟡 Yellow": [1.0, 0.9, 0.0, 1.0],
    "🟣 Purple": [0.5, 0.0, 0.8, 1.0],
    "🟠 Orange": [1.0, 0.5, 0.0, 1.0],
    "🩷 Pink":   [1.0, 0.3, 0.6, 1.0],
    "🩵 Cyan":   [0.0, 0.9, 1.0, 1.0],
    "🟤 Brown":  [0.5, 0.25, 0.0, 1.0],
    "🌿 Olive":  [0.4, 0.6, 0.0, 1.0],
}

COLOR_KEYS = list(COLORS.keys())  # stable order for index

# ── Lottie load/save ─────────────────────────────────────

def load_lottie(path: str) -> dict:
    if path.endswith(".tgs"):
        with gzip.open(path, "rb") as f:
            return json.loads(f.read())
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_tgs(data: dict, out_path: str):
    raw = json.dumps(data, separators=(",", ":")).encode()
    with gzip.open(out_path, "wb") as f:
        f.write(raw)


# ── Build a human-readable label for each layer ───────────
def describe_layers(data: dict) -> list[dict]:
    """
    Returns list of:
      { "label": str, "source": "top"|"asset", "asset_id": str|None, "index": int }
    Only layers that have fl/st colors (editable) or are precomps (logo).
    """
    result = []

    def has_colors(obj):
        if isinstance(obj, dict):
            if obj.get("ty") in ("fl", "st"):
                return True
            return any(has_colors(v) for v in obj.values())
        if isinstance(obj, list):
            return any(has_colors(v) for v in obj)
        return False

    # Top-level layers
    for i, layer in enumerate(data.get("layers", [])):
        ty = layer.get("ty")
        if ty == 0:  # precomp = logo
            ref = layer.get("refId", f"precomp_{i}")
            result.append({
                "label": f"Logo ({ref})",
                "source": "top",
                "index": i,
                "asset_id": None,
                "ty": ty,
            })
        elif ty == 4 and has_colors(layer.get("shapes", [])):
            # Give it a positional name
            shape_count = len(layer.get("shapes", []))
            result.append({
                "label": f"Shape Layer {i} (ind={layer.get('ind')})",
                "source": "top",
                "index": i,
                "asset_id": None,
                "ty": ty,
            })

    # Asset layers
    for asset in data.get("assets", []):
        aid = asset.get("id", "?")
        for i, layer in enumerate(asset.get("layers", [])):
            if has_colors(layer):
                result.append({
                    "label": f"Asset '{aid}' L{i}",
                    "source": "asset",
                    "index": i,
                    "asset_id": aid,
                    "ty": layer.get("ty"),
                })

    return result


# ── Color manipulation ────────────────────────────────────

def set_all_colors(obj, rgba: list):
    """Recursively set ALL fl/st colors in obj to rgba."""
    if isinstance(obj, dict):
        if obj.get("ty") in ("fl", "st"):
            c = obj.get("c", {})
            k = c.get("k")
            if isinstance(k, list):
                if len(k) == 4 and isinstance(k[0], (int, float)):
                    c["k"] = rgba  # static
                else:
                    for kf in k:  # animated keyframes
                        if isinstance(kf, dict) and "s" in kf:
                            kf["s"] = rgba
        for v in obj.values():
            set_all_colors(v, rgba)
    elif isinstance(obj, list):
        for v in obj:
            set_all_colors(v, rgba)


def apply_color_to_layer(data: dict, layer_info: dict, rgba: list):
    if layer_info["source"] == "top":
        layer = data["layers"][layer_info["index"]]
        set_all_colors(layer, rgba)
    else:
        for asset in data.get("assets", []):
            if asset.get("id") == layer_info["asset_id"]:
                layer = asset["layers"][layer_info["index"]]
                set_all_colors(layer, rgba)


def toggle_layer_visibility(data: dict, layer_info: dict, visible: bool):
    if layer_info["source"] == "top":
        layer = data["layers"][layer_info["index"]]
    else:
        layer = None
        for asset in data.get("assets", []):
            if asset.get("id") == layer_info["asset_id"]:
                layer = asset["layers"][layer_info["index"]]
    if layer is not None:
        layer["hd"] = not visible


# ── Keyboard builders ─────────────────────────────────────

def main_menu_kb(layers: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for i, info in enumerate(layers):
        rows.append([InlineKeyboardButton(f"✏️ {info['label']}", callback_data=f"L{i}")])
    rows.append([InlineKeyboardButton("✅ Export Sticker", callback_data="EXPORT")])
    return InlineKeyboardMarkup(rows)


def layer_actions_kb(li: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👁 Show",   callback_data=f"VIS_{li}_1"),
            InlineKeyboardButton("🙈 Hide",   callback_data=f"VIS_{li}_0"),
        ],
        [InlineKeyboardButton("🎨 Change Color", callback_data=f"CLR_{li}_0")],
        [InlineKeyboardButton("⬅️ Back",         callback_data="BACK")],
    ])


def color_page_kb(li: int, page: int) -> InlineKeyboardMarkup:
    per_page = 6
    start = page * per_page
    end   = min(start + per_page, len(COLOR_KEYS))
    rows  = []
    row   = []
    for ci in range(start, end):
        cname = COLOR_KEYS[ci]
        row.append(InlineKeyboardButton(cname, callback_data=f"SETCLR_{li}_{ci}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅ Prev", callback_data=f"CLR_{li}_{page-1}"))
    if end < len(COLOR_KEYS):
        nav.append(InlineKeyboardButton("Next ➡", callback_data=f"CLR_{li}_{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([
        InlineKeyboardButton("✏️ Custom Hex", callback_data=f"HEXINPUT_{li}"),
        InlineKeyboardButton("⬅️ Back",       callback_data=f"L{li}"),
    ])
    return InlineKeyboardMarkup(rows)


# ── Handlers ─────────────────────────────────────────────

@app.on_message(filters.command("start"))
async def start(_, message: Message):
    await message.reply(
        "hey 👋\n\n"
        "drop your `.json` or `.tgs` Lottie file\n"
        "main saare layers detect karunga aur\n"
        "colors change karne dunga — step by step 🎨\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "made by @GTK26"
    )


@app.on_message(filters.document)
async def handle_file(_, message: Message):
    doc = message.document
    if not (doc.file_name.endswith(".json") or doc.file_name.endswith(".tgs")):
        await message.reply("sirf .json ya .tgs file bhejo 😅")
        return

    msg = await message.reply("loading layers... ⚙️")
    user_id = message.from_user.id
    tmpdir  = tempfile.mkdtemp(prefix=f"sbot_{user_id}_")
    path    = await message.download(file_name=os.path.join(tmpdir, doc.file_name))

    try:
        lottie = load_lottie(path)
    except Exception as e:
        await msg.edit(f"parse nahi hua 😬\n`{e}`")
        return

    layers = describe_layers(lottie)
    if not layers:
        await msg.edit("koi editable layer nahi mili 🤔")
        return

    sessions[user_id] = {
        "json":   lottie,
        "path":   tmpdir,
        "layers": layers,
        "waiting": None,
    }

    text = "**Layers mili:**\n"
    for i, info in enumerate(layers):
        text += f"`{i}` — {info['label']}\n"
    text += "\nKaunsi layer edit karni hai? 👇"

    await msg.edit(text, reply_markup=main_menu_kb(layers))


@app.on_callback_query()
async def cb(_, query: CallbackQuery):
    uid  = query.from_user.id
    data = query.data
    sess = sessions.get(uid)

    if sess is None:
        await query.answer("session khatam — dobara file bhejo", show_alert=True)
        return

    lottie = sess["json"]
    layers = sess["layers"]

    # ── Back to main menu ──────────────────────────────
    if data == "BACK":
        text = "Kaunsi layer edit karni hai? 👇"
        await query.message.edit_text(text, reply_markup=main_menu_kb(layers))

    # ── Open layer menu ───────────────────────────────
    elif data.startswith("L") and data[1:].isdigit():
        li   = int(data[1:])
        info = layers[li]
        await query.message.edit_text(
            f"**{info['label']}**\nKya change karna hai?",
            reply_markup=layer_actions_kb(li)
        )

    # ── Visibility ────────────────────────────────────
    elif data.startswith("VIS_"):
        _, li, flag = data.split("_")
        li      = int(li)
        visible = flag == "1"
        toggle_layer_visibility(lottie, layers[li], visible)
        state = "visible ✅" if visible else "hidden 🙈"
        await query.answer(f"{layers[li]['label']} → {state}")
        await query.message.edit_text(
            f"**{layers[li]['label']}** — {state}\nAur kya karna hai?",
            reply_markup=layer_actions_kb(li)
        )

    # ── Color picker page ─────────────────────────────
    elif data.startswith("CLR_"):
        _, li, page = data.split("_")
        li, page    = int(li), int(page)
        await query.message.edit_text(
            f"**{layers[li]['label']}** ke liye color chuno 🎨",
            reply_markup=color_page_kb(li, page)
        )

    # ── Apply preset color ────────────────────────────
    elif data.startswith("SETCLR_"):
        _, li, ci = data.split("_")
        li, ci    = int(li), int(ci)
        cname     = COLOR_KEYS[ci]
        rgba      = COLORS[cname]
        apply_color_to_layer(lottie, layers[li], rgba)
        await query.answer(f"✅ {cname} apply hua!")
        await query.message.edit_text(
            f"**{layers[li]['label']}** → {cname} ✅\nAur kya karna hai?",
            reply_markup=layer_actions_kb(li)
        )

    # ── Custom hex input prompt ───────────────────────
    elif data.startswith("HEXINPUT_"):
        li = int(data.split("_")[1])
        sess["waiting"] = ("hex", li)
        await query.message.edit_text(
            f"**{layers[li]['label']}** ke liye hex color bhejo\n"
            "Example: `#FF5733` ya `FF5733`"
        )
        await query.answer()

    # ── Export ────────────────────────────────────────
    elif data == "EXPORT":
        await query.answer("generating...")
        await query.message.edit_text("sticker bana raha hoon... ⚙️")
        out = os.path.join(sess["path"], "out.tgs")
        save_tgs(lottie, out)
        await query.message.reply_sticker(out)
        await query.message.delete()
        sessions.pop(uid, None)

    else:
        await query.answer("unknown")


# ── Text input (custom hex) ───────────────────────────────
@app.on_message(filters.text & ~filters.command(["start"]))
async def text_input(_, message: Message):
    uid  = message.from_user.id
    sess = sessions.get(uid)

    if not sess or not sess.get("waiting"):
        await message.reply("pehle .json ya .tgs file bhejo 🙂")
        return

    action, li = sess["waiting"]
    sess["waiting"] = None
    lottie = sess["json"]
    layers = sess["layers"]

    if action == "hex":
        h = message.text.strip().lstrip("#")
        try:
            if len(h) == 6:
                r, g, b = int(h[0:2],16)/255, int(h[2:4],16)/255, int(h[4:6],16)/255
                rgba = [r, g, b, 1.0]
            elif len(h) == 8:
                r, g, b, a = int(h[0:2],16)/255, int(h[2:4],16)/255, int(h[4:6],16)/255, int(h[6:8],16)/255
                rgba = [r, g, b, a]
            else:
                raise ValueError
            apply_color_to_layer(lottie, layers[li], rgba)
            await message.reply(
                f"**{layers[li]['label']}** → `#{h}` ✅\nAur kya karna hai?",
                reply_markup=layer_actions_kb(li)
            )
        except Exception:
            await message.reply("galat hex hai 😬 phir se bhejo jaise `#FF5733`")
            sess["waiting"] = ("hex", li)


if __name__ == "__main__":
    print("Bot chalu ho gaya...")
    app.run()
