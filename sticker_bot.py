import gzip
import os
import tempfile
from pyrogram import Client, filters
from pyrogram.types import Message

# ── Config ──────────────────────────────────────────────
API_ID   = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
# ────────────────────────────────────────────────────────

app = Client("sticker_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


@app.on_message(filters.document)
async def handle_json(client: Client, message: Message):
    doc = message.document

    # Accept only .json or .tgs files
    if not (doc.file_name.endswith(".json") or doc.file_name.endswith(".tgs")):
        await message.reply("hey that format won't work 😅\njust send a .json or .tgs file")
        return

    await message.reply("on it... ⚙️")

    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. Download the file
        file_path = await message.download(file_name=os.path.join(tmpdir, doc.file_name))

        # 2. If it's a .json, compress it to .tgs (gzip)
        if file_path.endswith(".json"):
            tgs_path = os.path.join(tmpdir, "sticker.tgs")
            with open(file_path, "rb") as f_in:
                with gzip.open(tgs_path, "wb") as f_out:
                    f_out.write(f_in.read())
        else:
            # Already a .tgs
            tgs_path = file_path

        # 3. Send as animated sticker
        await message.reply_sticker(tgs_path)


@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply(
        "hey 👋\n\n"
        "just drop your `.json` or `.tgs` file and i'll turn it into a sticker for you 🔥\n\n"
        "make sure the file is in Lottie format (512×512)\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "this Bot made By @GTK26"
    )


if __name__ == "__main__":
    print("Bot chalu ho gaya...")
    app.run()
