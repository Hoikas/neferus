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
from aiohttp import web
import logging
import random

# Maimum number of commits in a push to blab about.
_max_commits = 3

_quotes = [
    "YOU HAVE DIED OF DYSENTERY",
    "the cake is a lie",
    "War is where the young and stupid are tricked by the old and bitter into killing each other.",
    "I used to be an adventurer like you until I took an arrow to the knee.",
    "welcome to zombocom",
    "Hocus pocus abracadabra arse blathanna.",
    "We understanded",
]

class GitHub:
    def __init__(self, cfg, irc, loop):
        assert cfg and irc and loop
        self.eventloop = loop
        self._cfg = cfg
        self._irc = irc

        self.logger = logging.getLogger(__name__)
        self._events = {
            "issues": self._handle_issue,
            "ping": self._handle_ping,
            "pull_request": self._handle_pull_request,
            "push": self._handle_push,
        }

    async def _handle_issue(self, event):
        if event["action"] not in {"opened", "deleted", "closed", "reopened"}:
            return

        msg = (f"\x02{event['sender']['login']}\x02 has {event['action']} issue #"
               f"{event['issue']['number']} ({event['issue']['title']}) on "
               f"{event['repository']['full_name']}: {event['issue']['html_url']}")
        await self._irc.send_notification(msg)

    async def _handle_ping(self, event):
        await self._irc.send_notification(f"\x02GitHub\x02 has pinged {event['repository']['full_name']}")

    async def _handle_pull_request(self, event):
        act_key = event["action"]
        if act_key == "opened":
            action = f"opened pull request #{event['number']} ({event['pull_request']['title']})"
        elif act_key == "closed":
            action = (f"{'merged' if event['pull_request']['merged'] else 'closed'}"
                      f" pull request #{event['number']} ({event['pull_request']['title']})")
        elif act_key == "ready_for_review":
            action = f"marked pull request #{event['number']} ({event['pull_request']['title']}) ready for review"
        elif act_key == "reopened":
            action = f"reopened pull request #{event['number']} ({event['pull_request']['title']})"
        else:
            return

        msg = (f"\x02{event['sender']['login']}\x02 has {action} on {event['repository']['full_name']}: "
               f"{event['pull_request']['html_url']}")
        await self._irc.send_notification(msg)

    async def _handle_push(self, event):
        try:
            _, ref_type, ref_name = event["ref"].split('/')
        except:
            self.logger.warning(f"Weird ass-ref in push event '{event['ref']}'")
            ref_type, ref_name = None, "<unknown>"

        sha = lambda x: x[:7]
        num_commits = len(event["commits"])
        commits = "commit" if num_commits == 1 else "commits"
        push_type = "\x03\x01\x02force-pushed\x0f" if event["forced"] else "pushed"
        notifications = []

        if ref_type in {"heads", "tags"}:
            ref_msg = f"/{ref_name}"
        else:
            ref_msg = ""
        msg = (f"\x02{event['sender']['login']}\x02 has {push_type} {num_commits} {commits} to "
               f"{event['repository']['full_name']}{ref_msg}: {event['compare']}")
        notifications.append(msg)

        if ref_type == "heads" and num_commits <= _max_commits:
            for i in range(min(num_commits, _max_commits)):
                commit = event["commits"][i]
                commit_msg = commit["message"]
                newline_idx = commit_msg.find("\n")
                if newline_idx != -1:
                    commit_msg = commit_msg[:newline_idx]

                notifications.append(f"{commit['author']['name']} {sha(commit['id'])} {commit_msg}")

        await self._irc.send_notification("\n".join(notifications))

    async def _on_request(self, request):
        if request.method != "POST":
            self.logger.warning(f"Invalid request '{request.method}' from {request.remote}")
            return web.Response(status=405, text=random.choice(_quotes))

        if request.content_type != "application/json":
            self.logger.error(f"Invalid Content-Type '{request.content_type}' from {request.remote}")
            raise web.HTTPBadRequest()

        post = request.headers
        event_type = post.get("X-GitHub-Event")
        if not event_type:
            self.logger.error(f"Missing X-GitHub-Event from {request.remote}")
            raise web.HTTPBadRequest()

        # verify hmac
        secret = self._cfg.get("webhook", "secret")
        digest = post.get("X-Hub-Signature")
        if secret:
            if not digest:
                self.logger.error(f"Missing X-Hub-Signature from {request.remote}")
                raise web.HTTPForbidden()
            # ... todo ...
        elif digest:
            self.logger.error(f"Got X-Hub-Signature from {request.remote} but the secret is not configured!")

        try:
            event = await request.json()
        except:
            self.logger.exception(f"Unable to load event JSON from {request.remote}")
            raise web.HTTPBadRequest()
        else:
            self.logger.debug(f"JSON from {request.remote}:\n{event}")

        handler = self._events.get(event_type)
        if not handler:
            self.logger.warning(f"Unhandled event '{event_type}' from {request.remote}")
            raise web.HTTPNotImplemented()

        try:
            await handler(event)
        except:
            self.logger.exception(f"Error handling event '{event_type}' from {request.remote}")
            raise web.HTTPInternalServerError()
        else:
            return web.Response(status=202, text="Accepted")

    async def _start(self):
        self._server = web.Server(self._on_request)
        self._runner = web.ServerRunner(self._server)
        await self._runner.setup()

        # todo unix socket
        host = self._cfg.get("webhook", "host")
        port = self._cfg.getint("webhook", "port")
        self._site = web.TCPSite(self._runner, host, port)
        await self._site.start()

    def start(self):
        self.logger.info("Starting Webhook...")

        # The main module will ensure that the event loop is run forever. For now, we just
        # want to run long enough to start our site.
        self.eventloop.run_until_complete(self._start())

    async def _stop(self):
        self.logger.info("Shutting down Webhook...")

        await self._site.stop()
        await self._runner.cleanup()
        await self._server.shutdown(2.0)

    def stop(self):
        self.eventloop.run_until_complete(self._stop())
