import asyncio
import json
import websockets
import aiohttp
import niobot
from nio import MatrixRoom, RoomMessageText, RoomMessageImage
import pathlib
import tempfile

try:
    from config import DISCORD_BRIDGE_TOKEN
except ImportError:
    DISCORD_BRIDGE_TOKEN = None


class QuoteModule(niobot.Module):
    def __init__(self, bot: niobot.NioBot):
        super().__init__(bot)
        self.bot.add_event_callback(self.on_message, (RoomMessageText, RoomMessageImage))
        self.fifo_task = asyncio.create_task(self.message_poller())
        self.last_author: str = "@jimmy-bot:nexy7574.co.uk"

    async def message_poller(self):
        if not DISCORD_BRIDGE_TOKEN:
            return
        ROOM_ID = "!WrLNqENUnEZvLJiHsu:nexy7574.co.uk"
        room = self.bot.rooms[ROOM_ID]
        while True:
            try:
                async with aiohttp.ClientSession(headers={"User-Agent": niobot.__user_agent__()}) as client:
                    self.log.info("Starting fifo task")
                    async for ws in websockets.connect(
                            "wss://droplet.nexy7574.co.uk/jimmy/bridge/recv",
                            extra_headers={"secret": DISCORD_BRIDGE_TOKEN}
                    ):
                        async for payload in ws:
                            self.log.debug("Decoding payload...")
                            payload = json.loads(payload)
                            self.log.debug("Received payload: %s", payload)
                            if payload["author"] == "Jimmy Savile#3762":
                                continue
                            _author = self.last_author
                            self.last_author = payload["author"]
                            if payload["content"]:
                                await self.bot.send_message(
                                    room,
                                    "**%s**:<br><blockquote>%s</blockquote>" % (
                                        payload["author"], payload["content"]
                                    ),
                                    message_type="m.text"
                                )

                            if payload["attachments"]:
                                for attachment in payload["attachments"]:
                                    try:
                                        async with client.get(attachment["url"]) as response:
                                            if response.status != 200:
                                                continue

                                            with tempfile.NamedTemporaryFile(
                                                    suffix=pathlib.Path(attachment["url"]).suffix
                                            ) as tmp:
                                                tmp.write(await response.read())
                                                tmp.flush()
                                                tmp.seek(0)
                                                media = niobot.MediaAttachment(
                                                    tmp.name,
                                                    mime=attachment["content_type"],
                                                    height=attachment["height"],
                                                    width=attachment["width"],
                                                )
                                                await self.bot.send_message(
                                                    room,
                                                    attachment["filename"],
                                                    file=media
                                                )
                                    except Exception as e:
                                        self.log.exception("Error while mirroring discord media: %r", e, exc_info=e)
                                        continue
            except Exception as e:
                self.log.exception("Error while reading from websocket: %r", e, exc_info=e)
                continue

    # @niobot.event("message")
    async def on_message(self, room: MatrixRoom, event: RoomMessageText | RoomMessageImage):
        self.log.debug("Processing message: %s in %s", event, room)
        if self.bot.is_old(event):
            self.log.debug("Ignoring old message: %s in %s", event, room)
            return

        if room.room_id != "!WrLNqENUnEZvLJiHsu:nexy7574.co.uk":
            self.log.debug("Ignoring message in %s", room)
            return

        if event.body.startswith("~"):
            self.log.debug("Ignoring escaped message: %s", event)
            return

        if event.sender == self.bot.user_id:
            self.log.debug("Ignoring message from self: %s", event)
            return

        if DISCORD_BRIDGE_TOKEN:
            payload = {
                "secret": DISCORD_BRIDGE_TOKEN,
                "sender": event.sender,
                "message": event.body
            }
            if isinstance(event, RoomMessageImage):
                payload["message"] = event.url
            async with aiohttp.ClientSession(headers={"User-Agent": niobot.__user_agent__()}) as client:
                self.log.debug("Sending message to discord bridge")
                async with client.post(
                    "https://droplet.nexy7574.co.uk/jimmy/bridge",
                    json=payload,
                    headers={
                        "Connection": "Close"
                    },
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status != 200:
                        self.log.error(
                            "Error while sending message to discord bridge (%d): %s",
                            response.status,
                            await response.text()
                        )
                        return
                    self.log.info("Message sent to discord bridge")
        else:
            self.log.debug("No discord bridge token set, ignoring message")