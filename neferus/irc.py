#    This file is part of neferus
#
#    neferus is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    neferus is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with neferus.  If not, see <https://www.gnu.org/licenses/>.

import asyncio
import codecs
from collections import Sequence
import logging
import pydle
import sys

class IRCBot(pydle.MinimalClient):
    RECONNECT_ON_ERROR = True
    RECONNECT_MAX_ATTEMPTS = None

    def __init__(self, cfg, **kwargs):
        assert cfg
        self._cfg = cfg

        nickname = cfg.get("irc", "nick")
        nickname_inverse = nickname[::-1]

        fallback_nicknames = []
        fallback_nicknames.append(nickname_inverse)
        fallback_nicknames.append(codecs.encode(nickname, "rot13"))
        fallback_nicknames.append(codecs.encode(nickname_inverse, "rot13"))

        super().__init__(nickname=nickname, fallback_nicknames=fallback_nicknames, **kwargs)

    async def on_ctcp_time(self, by, target, contents):
        await self.ctcp_reply(by, "TIME", "PEANUT BUTTER JELLY TIME!")

    async def on_ctcp_version(self, by, target, contents):
        version = f"neferus - "
        if sys.platform == "win32":
            info = sys.getwindowsversion()
            version += f"Windows {info.major} (build {info.build})"
        else:
            version += sys.platform
        version += f" - Python {sys.version}"
        await self.ctcp_reply(by, "VERSION", version.replace('\n', ''))

    async def send_notification(self, notification):
        """Sends a message to all joined channels. Multiple messages may be sent by separating
           them with newlines."""
        coros = (self.message(i, notification) for i in self.channels.keys())
        await asyncio.gather(*coros)

    def start(self):
        logging.info("Starting IRC...")

        host = self._cfg.get("irc", "host")
        port = self._cfg.getint("irc", "port")
        channels = self._cfg.get("irc", "channels").split(' ')
        coro = self.connect(hostname=host, port=port, channels=channels)

        # The main module will ensure that the event loop is run forever. For now, we just want to
        # connect to IRC.
        self.eventloop.run_until_complete(coro)

    async def _stop(self):
        logging.info("Disconnecting from IRC...")
        try:
            await asyncio.wait_for(self.quit("hsgNeferus::Neferus()->Shutdown();"), timeout=2.0)
        except asyncio.TimeoutError:
            self.logger.warning("IRC Quit Timeout (who gives a rat's ass?)")

    def stop(self):
        self.eventloop.run_until_complete(self._stop())
