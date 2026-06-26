import os, json, uuid, gzip, io, asyncio, tempfile
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

API_ID     = int(os.environ.get("API_ID", "0"))
API_HASH   = os.environ.get("API_HASH", "")
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
API_PORT   = int(os.environ.get("PORT", "8080"))
# Railway gives you a public URL — set this in env vars
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")

sticker_store = {}

app = Client("sticker_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ── HTML MINI APP (embedded) ──────────────────────────────────────
HTML = open("index.html").read() if os.path.exists("index.html") else "<h1>index.html not found</h1>"

# ── BOT HANDLERS ─────────────────────────────────────────────────

@app.on_message(filters.command("start"))
async def start(_, message: Message):
    await message.reply(
        "hey 👋\n\n"
        "just send me a `.json` or `.tgs` sticker file and i'll open the editor for you 🎨\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "this Bot made By @GTK26"
    )

@app.on_message(filters.document)
async def handle_doc(_, message: Message):
    name = message.document.file_name
    if not (name.endswith(".json") or name.endswith(".tgs")):
        await message.reply("hey that format won't work 😅\njust send a .json or .tgs sticker file")
        return

    with tempfile.TemporaryDirectory() as tmp:
        path = await message.download(file_name=os.path.join(tmp, name))
        with open(path, "rb") as f:
            raw = f.read()

    if name.endswith(".tgs"):
        try:
            raw = gzip.decompress(raw)
        except Exception:
            await message.reply("couldn't read this .tgs file 😕")
            return

    try:
        lottie = json.loads(raw)
    except Exception:
        await message.reply("invalid json inside the file 😕")
        return

    token = uuid.uuid4().hex[:12]
    sticker_store[token] = json.dumps(lottie)

    webapp_url = f"{PUBLIC_URL}/app?token={token}"

    await message.reply(
        "your sticker is ready to edit ✨\n\ntap below to open the editor 👇",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎨 Tap to Customize your sticker", web_app=WebAppInfo(url=webapp_url))
        ]])
    )

@app.on_message(filters.create(lambda _, __, m: bool(m.web_app_data)))
async def handle_webapp_data(_, message: Message):
    try:
        lottie_json = message.web_app_data.data
        compressed = gzip.compress(lottie_json.encode())
        buf = io.BytesIO(compressed)
        buf.name = "sticker.tgs"
        buf.seek(0)
        await message.reply_sticker(buf)
        await message.reply("here's your customised sticker! 🔥")
    except Exception as e:
        await message.reply(f"something went wrong 😕\n{e}")

# ── API + HTML SERVER ─────────────────────────────────────────────

async def serve_app(request):
    token = request.rel_url.query.get("token", "")
    # inject bot api url + token into html
    html = HTML.replace(
        "%%BOT_API_URL%%", PUBLIC_URL
    ).replace(
        "%%TOKEN%%", token
    )
    return web.Response(text=html, content_type="text/html")

async def api_get_sticker(request):
    token = request.rel_url.query.get("token", "")
    if token not in sticker_store:
        return web.Response(status=404, text="not found")
    return web.Response(
        text=sticker_store[token],
        content_type="application/json",
        headers={"Access-Control-Allow-Origin": "*"}
    )

async def api_options(request):
    return web.Response(headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST",
        "Access-Control-Allow-Headers": "*"
    })

async def start_server():
    server = web.Application()
    server.router.add_get("/app", serve_app)
    server.router.add_get("/sticker", api_get_sticker)
    server.router.add_options("/sticker", api_options)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", API_PORT)
    await site.start()
    print(f"Server running on port {API_PORT}")

async def main():
    await start_server()
    await app.start()
    print("sticker bot is live...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())