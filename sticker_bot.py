import gzip
import json
import os
import copy
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

# ── In-memory session store ──────────────────────────────
# Structure: { user_id: { "json": {...}, "path": "...", "edits": { layer_name: {...} } } }
sessions: dict = {}

# ── Known layer names (tune these to match your JSON files) ──
KNOWN_LAYERS = ["logo", "border", "solid", "black logo"]

# ── Color presets ────────────────────────────────────────
COLOR_PRESETS = {
    "red":    [1.0, 0.0, 0.0, 1.0],
    "green":  [0.0, 1.0, 0.0, 1.0],
    "blue":   [0.0, 0.0, 1.0, 1.0],
    "white":  [1.0, 1.0, 1.0, 1.0],
    "black":  [0.0, 0.0, 0.0, 1.0],
    "yellow": [1.0, 1.0, 0.0, 1.0],
    "purple": [0.5, 0.0, 0.5, 1.0],
    "orange": [1.0, 0.5, 0.0, 1.0],
    "pink":   [1.0, 0.4, 0.7, 1.0],
    "cyan":   [0.0, 1.0, 1.0, 1.0],
}

# ── Lottie helpers ───────────────────────────────────────

def load_lottie(path: str) -> dict:
    """Load .json or .tgs into a dict."""
    if path.endswith(".tgs"):
        with gzip.open(path, "rb") as f:
            return json.loads(f.read())
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_lottie_as_tgs(data: dict, out_path: str):
    """Dump dict → gzip → .tgs"""
    raw = json.dumps(data, separators=(",", ":")).encode()
    with gzip.open(out_path, "wb") as f:
        f.write(raw)


def get_layer_names(data: dict) -> list[str]:
    """Return all layer nm fields from the Lottie JSON."""
    return [l.get("nm", "") for l in data.get("layers", [])]


def find_layer(data: dict, name: str):
    """Find a layer by nm (case-insensitive partial match)."""
    name_lower = name.lower()
    for layer in data.get("layers", []):
        if name_lower in layer.get("nm", "").lower():
            return layer
    return None


def set_layer_visibility(data: dict, name: str, visible: bool):
    """Toggle layer hidden flag (hd field)."""
    layer = find_layer(data, name)
    if layer is not None:
        layer["hd"] = not visible


def recolor_layer(data: dict, name: str, rgba: list):
    """
    Walk through a layer's shapes/items and recolor all fill/stroke colors.
    rgba = [r, g, b, a]  values 0.0–1.0
    """
    layer = find_layer(data, name)
    if layer is None:
        return

    def walk(obj):
        if isinstance(obj, dict):
            # Lottie solid color: { "ty": "fl" } or { "ty": "st" }
            if obj.get("ty") in ("fl", "st"):
                c = obj.get("c", {})
                if isinstance(c.get("k"), list):
                    # Static color
                    if len(c["k"]) == 4 and isinstance(c["k"][0], (int, float)):
                        c["k"] = rgba
                    # Animated keyframes — patch every keyframe
                    else:
                        for kf in c["k"]:
                            if isinstance(kf, dict) and "s" in kf:
                                kf["s"] = rgba
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(layer)


def scale_layer(data: dict, name: str, sx: float, sy: float):
    """
    Patch the transform scale of a layer.
    sx, sy: scale percentage (100 = original size).
    """
    layer = find_layer(data, name)
    if layer is None:
        return
    ks = layer.get("ks", {})
    s = ks.get("s", {})
    if isinstance(s.get("k"), list):
        k = s["k"]
        # Static [sx, sy, sz]
        if len(k) >= 2 and isinstance(k[0], (int, float)):
            s["k"] = [sx, sy, k[2] if len(k) > 2 else 100]
        else:
            # Animated keyframes
            for kf in k:
                if isinstance(kf, dict) and "s" in kf:
                    kf["s"] = [sx, sy, kf["s"][2] if len(kf["s"]) > 2 else 100]


def rotate_layer(data: dict, name: str, degrees: float):
    """Patch static rotation of a layer's transform."""
    layer = find_layer(data, name)
    if layer is None:
        return
    ks = layer.get("ks", {})
    r = ks.get("r", {})
    if isinstance(r.get("k"), (int, float)):
        r["k"] = degrees
    elif isinstance(r.get("k"), list):
        for kf in r["k"]:
            if isinstance(kf, dict) and "s" in kf:
                kf["s"] = [degrees]


# ── Keyboard builders ────────────────────────────────────

def main_menu_kb(layer_names: list[str]) -> InlineKeyboardMarkup:
    """Show one button per detected layer + Done."""
    rows = []
    for nm in layer_names:
        rows.append([InlineKeyboardButton(f"✏️ {nm}", callback_data=f"layer|{nm}")])
    rows.append([InlineKeyboardButton("✅ Done — export sticker", callback_data="export")])
    return InlineKeyboardMarkup(rows)


def layer_menu_kb(layer_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👁 Show",  callback_data=f"vis|{layer_name}|1"),
            InlineKeyboardButton("🙈 Hide",  callback_data=f"vis|{layer_name}|0"),
        ],
        [InlineKeyboardButton("🎨 Recolor", callback_data=f"recolor|{layer_name}")],
        [InlineKeyboardButton("📐 Scale",   callback_data=f"scale|{layer_name}")],
        [InlineKeyboardButton("🔄 Rotate",  callback_data=f"rotate|{layer_name}")],
        [InlineKeyboardButton("⬅️ Back",    callback_data="back")],
    ])


def color_picker_kb(layer_name: str) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for cname in COLOR_PRESETS:
        row.append(InlineKeyboardButton(cname.capitalize(), callback_data=f"color|{layer_name}|{cname}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("✏️ Custom hex", callback_data=f"customcolor|{layer_name}"),
        InlineKeyboardButton("⬅️ Back",       callback_data=f"layer|{layer_name}"),
    ])
    return InlineKeyboardMarkup(rows)


def scale_kb(layer_name: str) -> InlineKeyboardMarkup:
    scales = [("50%", 50), ("75%", 75), ("100%", 100), ("125%", 125), ("150%", 150)]
    rows = [[InlineKeyboardButton(label, callback_data=f"doscale|{layer_name}|{v}") for label, v in scales]]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"layer|{layer_name}")])
    return InlineKeyboardMarkup(rows)


def rotate_kb(layer_name: str) -> InlineKeyboardMarkup:
    angles = [("0°", 0), ("45°", 45), ("90°", 90), ("135°", 135), ("180°", 180), ("-90°", -90)]
    rows = [[InlineKeyboardButton(label, callback_data=f"dorotate|{layer_name}|{v}") for label, v in angles]]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"layer|{layer_name}")])
    return InlineKeyboardMarkup(rows)


# ── Handlers ─────────────────────────────────────────────

@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply(
        "hey 👋\n\n"
        "drop your `.json` or `.tgs` Lottie file and I'll let you\n"
        "customize each layer — visibility, color, scale, rotation — "
        "then export as a sticker 🔥\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "made by @GTK26"
    )


@app.on_message(filters.document)
async def handle_file(client: Client, message: Message):
    doc = message.document
    if not (doc.file_name.endswith(".json") or doc.file_name.endswith(".tgs")):
        await message.reply("hey that format won't work 😅\njust send a .json or .tgs file")
        return

    await message.reply("loading layers... ⚙️")

    # Download to a persistent temp dir per user
    user_id = message.from_user.id
    tmpdir = tempfile.mkdtemp(prefix=f"sbot_{user_id}_")
    file_path = await message.download(file_name=os.path.join(tmpdir, doc.file_name))

    try:
        lottie = load_lottie(file_path)
    except Exception as e:
        await message.reply(f"couldn't parse the file 😬\n`{e}`")
        return

    layer_names = get_layer_names(lottie)
    if not layer_names:
        await message.reply("no layers found in this file 🤔")
        return

    sessions[user_id] = {
        "json":  lottie,
        "path":  tmpdir,
        "edits": {},
        "waiting_for": None,   # for text input states
    }

    text = "**Layers detected:**\n" + "\n".join(f"• `{n}`" for n in layer_names)
    text += "\n\nChoose a layer to edit 👇"
    await message.reply(text, reply_markup=main_menu_kb(layer_names))


@app.on_callback_query()
async def handle_callback(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    data    = query.data
    session = sessions.get(user_id)

    if session is None:
        await query.answer("session expired — send your file again", show_alert=True)
        return

    lottie = session["json"]
    layer_names = get_layer_names(lottie)

    # ── back to main menu ──────────────────────────────
    if data == "back":
        await query.message.edit_text(
            "Choose a layer to edit 👇",
            reply_markup=main_menu_kb(layer_names)
        )

    # ── open layer menu ────────────────────────────────
    elif data.startswith("layer|"):
        layer_name = data.split("|", 1)[1]
        await query.message.edit_text(
            f"**{layer_name}** — what do you want to change?",
            reply_markup=layer_menu_kb(layer_name)
        )

    # ── visibility ────────────────────────────────────
    elif data.startswith("vis|"):
        _, layer_name, flag = data.split("|")
        visible = flag == "1"
        set_layer_visibility(lottie, layer_name, visible)
        state = "visible ✅" if visible else "hidden 🙈"
        await query.answer(f"{layer_name} is now {state}")
        await query.message.edit_text(
            f"**{layer_name}** — {state}\nWhat else?",
            reply_markup=layer_menu_kb(layer_name)
        )

    # ── recolor menu ──────────────────────────────────
    elif data.startswith("recolor|"):
        layer_name = data.split("|", 1)[1]
        await query.message.edit_text(
            f"Pick a color for **{layer_name}** 🎨",
            reply_markup=color_picker_kb(layer_name)
        )

    # ── apply preset color ────────────────────────────
    elif data.startswith("color|"):
        _, layer_name, cname = data.split("|")
        rgba = COLOR_PRESETS[cname]
        recolor_layer(lottie, layer_name, rgba)
        await query.answer(f"colored {layer_name} → {cname} ✅")
        await query.message.edit_text(
            f"**{layer_name}** recolored to {cname}!\nWhat else?",
            reply_markup=layer_menu_kb(layer_name)
        )

    # ── custom hex prompt ─────────────────────────────
    elif data.startswith("customcolor|"):
        layer_name = data.split("|", 1)[1]
        session["waiting_for"] = ("hex", layer_name)
        await query.message.edit_text(
            f"send a hex color for **{layer_name}**\nExample: `#FF5733`"
        )
        await query.answer()

    # ── scale menu ────────────────────────────────────
    elif data.startswith("scale|"):
        layer_name = data.split("|", 1)[1]
        await query.message.edit_text(
            f"Choose scale for **{layer_name}** 📐",
            reply_markup=scale_kb(layer_name)
        )

    # ── apply scale ───────────────────────────────────
    elif data.startswith("doscale|"):
        _, layer_name, val = data.split("|")
        s = float(val)
        scale_layer(lottie, layer_name, s, s)
        await query.answer(f"scaled to {val}% ✅")
        await query.message.edit_text(
            f"**{layer_name}** scaled to {val}%!\nWhat else?",
            reply_markup=layer_menu_kb(layer_name)
        )

    # ── rotate menu ───────────────────────────────────
    elif data.startswith("rotate|"):
        layer_name = data.split("|", 1)[1]
        await query.message.edit_text(
            f"Choose rotation for **{layer_name}** 🔄",
            reply_markup=rotate_kb(layer_name)
        )

    # ── apply rotation ────────────────────────────────
    elif data.startswith("dorotate|"):
        _, layer_name, val = data.split("|")
        rotate_layer(lottie, layer_name, float(val))
        await query.answer(f"rotated to {val}° ✅")
        await query.message.edit_text(
            f"**{layer_name}** rotated to {val}°!\nWhat else?",
            reply_markup=layer_menu_kb(layer_name)
        )

    # ── export ────────────────────────────────────────
    elif data == "export":
        await query.answer("generating sticker...")
        await query.message.edit_text("exporting your sticker... ⚙️")

        tmpdir = session["path"]
        out_path = os.path.join(tmpdir, "output.tgs")
        save_lottie_as_tgs(lottie, out_path)
        await query.message.reply_sticker(out_path)
        await query.message.delete()

        # clean up
        sessions.pop(user_id, None)

    else:
        await query.answer("unknown action")


# ── Handle text input for custom hex colors ──────────────
@app.on_message(filters.text & ~filters.command(["start"]))
async def handle_text_input(client: Client, message: Message):
    user_id = message.from_user.id
    session = sessions.get(user_id)

    if session is None or session.get("waiting_for") is None:
        await message.reply("send a .json or .tgs file to begin 🙂")
        return

    action, layer_name = session["waiting_for"]
    session["waiting_for"] = None

    if action == "hex":
        hex_str = message.text.strip().lstrip("#")
        try:
            if len(hex_str) == 6:
                r = int(hex_str[0:2], 16) / 255
                g = int(hex_str[2:4], 16) / 255
                b = int(hex_str[4:6], 16) / 255
                rgba = [r, g, b, 1.0]
            elif len(hex_str) == 8:
                r = int(hex_str[0:2], 16) / 255
                g = int(hex_str[2:4], 16) / 255
                b = int(hex_str[4:6], 16) / 255
                a = int(hex_str[6:8], 16) / 255
                rgba = [r, g, b, a]
            else:
                raise ValueError("bad length")

            recolor_layer(session["json"], layer_name, rgba)
            lottie = session["json"]
            layer_names = get_layer_names(lottie)
            await message.reply(
                f"**{layer_name}** recolored to `#{hex_str}` ✅\nWhat else?",
                reply_markup=layer_menu_kb(layer_name)
            )
        except Exception:
            await message.reply("invalid hex 😬 try again like `#FF5733`")
            session["waiting_for"] = ("hex", layer_name)


# ── Run ──────────────────────────────────────────────────
if __name__ == "__main__":
    print("Bot chalu ho gaya...")
    app.run()
