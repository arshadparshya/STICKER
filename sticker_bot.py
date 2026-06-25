import os
import json
import uuid
import gzip
import io
import tempfile
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

API_ID    = int(os.environ.get("API_ID", "0"))
API_HASH  = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://your-webapp-url.com")
API_PORT   = int(os.environ.get("PORT", "8080"))

# in-memory store: token -> lottie json string
sticker_store = {}

app = Client("sticker_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


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

    # if .tgs, it's gzip — decode to get lottie json
    if name.endswith(".tgs"):
        import gzip
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

    # encode lottie as url-safe base64 to pass to webapp
    import base64
    b64 = base64.urlsafe_b64encode(json.dumps(lottie).encode()).decode()

    url = f"{WEBAPP_URL}?data={b64}"

    await message.reply(
        "your sticker is ready to edit ✨\n\ntap the button below to open the editor 👇",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎨 Tap to Customize your sticker", web_app=WebAppInfo(url=url))
        ]])
    )


@app.on_message(filters.create(lambda _, __, m: bool(m.web_app_data)))
async def handle_webapp_data(_, message: Message):
    # webapp sends back the final lottie json
    import gzip, io
    try:
        lottie_json = message.web_app_data.data
        compressed = gzip.compress(lottie_json.encode())
        buf = io.BytesIO(compressed)
        buf.name = "sticker.tgs"
        buf.seek(0)
        await message.reply_sticker(buf)
    except Exception as e:
        await message.reply(f"something went wrong exporting 😕\n{e}")


# ── aiohttp API server (mini app fetches sticker data from here) ──
async def api_get_sticker(request):
    token = request.rel_url.query.get("token","")
    if token not in sticker_store:
        return web.Response(status=404, text="not found")
    return web.Response(
        text=sticker_store[token],
        content_type="application/json",
        headers={"Access-Control-Allow-Origin": "*"}
    )

async def api_options(request):
    return web.Response(headers={"Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET,POST","Access-Control-Allow-Headers":"*"})

async def start_api():
    server = web.Application()
    server.router.add_get("/sticker", api_get_sticker)
    server.router.add_options("/sticker", api_options)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", API_PORT)
    await site.start()
    print(f"API server running on port {API_PORT}")

async def main():
    await start_api()
    await app.start()
    print("sticker bot is live...")
    await app.idle()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())