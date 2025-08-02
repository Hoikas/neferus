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

from azure.appconfiguration.aio import AzureAppConfigurationClient
import azure.functions as func
from azure.identity.aio import DefaultAzureCredential
from azure.keyvault.secrets.aio import SecretClient
import pydle

import asyncio
import codecs
from contextlib import AsyncExitStack
from hashlib import sha1
import hmac
from http import HTTPStatus
import json
import logging
import os
from pathlib import PurePosixPath
import random
import sys
from typing import *
import urllib.parse

# Create a named logger for your function
logger = logging.getLogger("neferus")
logger.setLevel(logging.DEBUG)

# Add handler only if it's not already configured
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    handler.setFormatter(formatter)

    logger.addHandler(handler)


class IRCClient(pydle.MinimalClient):
    RECONNECT_DELAYS = [1]
    RECONNECT_MAX_ATTEMPTS = None

    def __init__(self):
        # Set up a lock so we don't start blabbing before we're completely connected.
        self.connection_event = asyncio.Event()

        nickname = config["IRC_NICKNAME"]

        # Make a bunch of fallback nicknames due to the scaling nature of Azure Functions.
        # Even though I have a maximum scale out of 1 set, sometimes we can get a conflict.
        fallback_nicknames = []
        for i in range(4, -1, -1):
            nick = f"{nickname}{'_' * i}"
            nick_inverse = f"{nickname[::-1]}{'_' * i}"
            fallback_nicknames.insert(0, nick_inverse)
            fallback_nicknames.insert(0, nick)
        for i in range(4):
            nick = f"{nickname}{'_' * i}"
            nick_inverse = f"{nickname[::-1]}{'_' * i}"
            fallback_nicknames.append(codecs.encode(nick, "rot13"))
            fallback_nicknames.append(codecs.encode(nick_inverse, "rot13"))

        super().__init__(
            nickname=nickname,
            fallback_nicknames=fallback_nicknames,
            username=nickname
        )

    async def on_connect(self):
        logger.debug("Connected to IRC!")
        self.connection_event.set()
        await super().on_connect()

    async def on_nick_change(self, old, new):
        logging.debug(f"IRC nick changed {old=} {new=}")
        await super().on_nick_change(old, new)

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

    async def on_kick(self, channel, target, by, reason=None):
        if self.is_same_nick(self.nickname, target):
            self.logger.error(f"Kicked from {channel} by {by} -- rejoining")
            await self.join(channel)

    async def send_notification(self, notification):
        """Sends a message to all joined channels. Multiple messages may be sent by separating
           them with newlines."""
        channels = config["IRC_CHANNELS"].split()
        for i in notification.split("\n"):
            logger.info(
                f"Dispatching notification to channels {', '.join(channels)}: {i}"
            )
        coros = (self.notice(i, notification) for i in channels)
        await asyncio.gather(*coros)


async def _handle_issue(irc: IRCClient, event) -> HTTPStatus:
    if event["action"] not in {"opened", "deleted", "closed", "reopened"}:
        return HTTPStatus.NOT_IMPLEMENTED

    msg = (f"\x02{event['sender']['login']}\x02 has {event['action']} issue #"
            f"{event['issue']['number']} ({event['issue']['title']}) on "
            f"{event['repository']['full_name']}: {event['issue']['html_url']}")
    await irc.send_notification(msg)

    return HTTPStatus.ACCEPTED

async def _handle_ping(irc: IRCClient, event) -> HTTPStatus:
    if "organization" in event:
        what = event["organization"]["login"]
    elif "repository" in event:
        what = event["repository"]["full_name"]
    else:
        what = "?UNKNOWN?"

    who = "I'm neferus, running on "
    if sys.platform == "win32":
        info = sys.getwindowsversion()
        who += f"(Windows {info.major} [build {info.build}]) "
    else:
        who += f"{sys.platform} "
    who += f"Python/{sys.version}"

    await irc.send_notification(
        f"\x02GitHub\x02 has pinged {what}\n{who}"
    )

    return HTTPStatus.ACCEPTED

async def _handle_pull_request(irc: IRCClient, event) -> HTTPStatus:
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
        return HTTPStatus.NOT_IMPLEMENTED

    msg = (
        f"\x02{event['sender']['login']}\x02 has {action} on {event['repository']['full_name']}: "
        f"{event['pull_request']['html_url']}"
    )
    await irc.send_notification(msg)

    return HTTPStatus.ACCEPTED

async def _handle_push(irc: IRCClient, event) -> HTTPStatus:
    try:
        _, ref_type, ref_name = event["ref"].split('/')
    except:
        logger.warning(f"Weird ass-ref in push event '{event['ref']}'")
        ref_type, ref_name = "<unknown>", "<unknown>"

    # The last-successful tag is for our "nightly" release. Don't spam the channel
    # about that.
    if ref_type == "tags" and ref_name == "last-successful":
        return HTTPStatus.ACCEPTED

    author = f"\x02{event['sender']['login']}\x02"
    sha = lambda x: x[:7]
    num_commits = len(event["commits"])
    commits = "commit" if num_commits == 1 else "commits"
    push_type = "\x034\x02force-pushed\x0f" if event["forced"] else "pushed"
    ref_msg = f"/{ref_name}" if ref_type in {"heads", "tags"} else ""
    ref_path = f"{event['repository']['full_name']}{ref_msg}"

    if ref_type == "heads" and not event["deleted"]:
        if num_commits:
            msg = f"{author} has {push_type} {num_commits} {commits} to {ref_path}: {event['compare']}"
        else:
            msg = f"{author} has {push_type} to {ref_path}"
        notifications = [msg]

        kMaxNumCommits = int(config["MAX_COMMITS_PER_EVENT"])
        if ref_type == "heads" and num_commits <= kMaxNumCommits:
            for i in range(min(num_commits, kMaxNumCommits)):
                commit = event["commits"][i]
                commit_msg = commit["message"]
                newline_idx = commit_msg.find("\n")
                if newline_idx != -1:
                    commit_msg = commit_msg[:newline_idx]

                notifications.append(f"{commit['author']['name']} {sha(commit['id'])} {commit_msg}")

        await irc.send_notification("\n".join(notifications))
    elif event["deleted"]:
        msg = f"{author} has deleted {ref_path}"
        await irc.send_notification(msg)
    elif ref_type == "tags":
        msg = (
            f"{author} has {push_type} tag {ref_name} to {ref_path}: "
            f"{event['repository']['html_url']}/releases/tag/{ref_name}"
        )
        await irc.send_notification(msg)
    else:
        logger.warning(f"Unhandled push notification for {event['ref']}")
        return HTTPStatus.NOT_IMPLEMENTED

    return HTTPStatus.ACCEPTED


# IRC Client singleton
_irc: Optional[IRCClient] = None

# Event handlers
_handlers = {
    "issues": _handle_issue,
    "ping": _handle_ping,
    "pull_request": _handle_pull_request,
    "push": _handle_push,
}

_quotes = [
    "YOU HAVE DIED OF DYSENTERY",
    "the cake is a lie",
    "War is where the young and stupid are tricked by the old and bitter into killing each other.",
    "I used to be an adventurer like you until I took an arrow to the knee.",
    "welcome to zombocom",
    "Hocus pocus abracadabra arse blathanna.",
    "We understanded",
]

_config_defaults = {
    "MAX_COMMITS_PER_EVENT": "3",
    "IRC_NICKNAME": "Neferus",
    "IRC_HOST": "tiana.guildofwriters.org",
    "IRC_PORT": "6667",
    "IRC_CHANNELS": "#notifications_test",
    # Ideally, you would put this in a key vault and add a
    # key vault reference to the App Configuration resource.
    "GITHUB_SECRET": "",
}

config: Dict[str, str] = {}
_config_lock = asyncio.Lock()

async def _get_secret(credential, keyvaultref: str) -> str:
    ref = json.loads(keyvaultref)
    url = urllib.parse.urlparse(ref["uri"])
    vault_url = f"{url.scheme}://{url.netloc}"
    secret_key = PurePosixPath(url.path).parts[-1]

    logger.debug(f"Looking up {secret_key=} from {vault_url=}")
    async with SecretClient(vault_url, credential) as client:
        secret = await client.get_secret(secret_key)
        if secret.value is None:
            logger.error(f"Could not find {secret_key=} in {vault_url=}")
            return ""
        return secret.value

async def _load_config():
    global config

    # Don't re-load the config if we still have a worker running.
    # Lazy hack, but whatever.
    if config:
        logger.debug("Config already loaded, bailing!")
        return

    # Load AppConfig from either AzureAppConfig or the local settings.
    if endpoint := os.getenv("APPCONFIG_ENDPOINT"):
        logger.debug("Fetching config from AppConfiguration...")
        async with AsyncExitStack() as stack:
            credential = await stack.enter_async_context(
                DefaultAzureCredential()
            )
            client = await stack.enter_async_context(
                AzureAppConfigurationClient(
                    base_url=endpoint,
                    credential=credential
                )
            )
            fetch_coros = (
                client.get_configuration_setting(i)
                for i in _config_defaults.keys()
            )
            config_results = await asyncio.gather(*fetch_coros)
            for result, (key, default) in zip(config_results, _config_defaults.items()):
                if result is not None:
                    logger.debug(f"... Got config {key=} = {result.value=}")
                    if result.content_type == "application/vnd.microsoft.appconfig.keyvaultref+json;charset=utf-8":
                        config[key] = await _get_secret(credential, result.value)
                    else:
                        config[key] = result.value
                else:
                    logger.debug(f"... Using config default {key=} = {default=}")
                    config[key] = default

        logger.debug("Config fetched!")
    else:
        logger.debug("Loading config from local settings...")
        # This is running locally, so no need to worry about aio
        with open("local.settings.json") as fp:
            local_config = json.load(fp)
            config = local_config.get("Values", {})

        # The values from `config` need to overwrite the defaults,
        # so it needs to be listed second.
        config = _config_defaults | config
        logger.debug("Config loaded!")

async def _connect_irc():
    global _irc

    # The IRC client may or may not be around when we get here.
    # Azure Functions may be running us in the same worker that we
    # were called in previously. If so, we might already have a connected
    # IRC client. If we do have a client already, it should be good
    # because pydle's `connect()` schedules a task to maintain the connection.
    # It does not return or await this task at all, though, so the IRC connection
    # should not cause the function to stay alive. # Open question is how well this
    # will work in practice. We'll see.
    if _irc is None:
        _irc = IRCClient()

    # If we've inherited a connection, ping the server to make sure the connection
    # is still working. There should be an asyncio task schedulled to handle incoming
    # data if we are already connected, so we will either get a PONG or some kind
    # of error, causing a reconnect.
    #
    # ALSO! If the function has been restarted, or we've been scaling out, then we
    # may be using a fallback nickname instead of our nickname. Eventually, we will
    # be able to claim that nickname, so give it a shot.
    if _irc.connected:
        await _irc.rawmsg("PING", _irc.server_tag)
        if not _irc.is_same_nick(_irc.nickname, config["IRC_NICKNAME"]):
            logger.debug(f"IRC Bot nick is {_irc.nickname=} - trying to change to {config['IRC_NICKNAME']=}")
            # This may not work. If it doesn't, the server says nothing, so
            # we better not wait on it.
            await _irc.set_nickname(config['IRC_NICKNAME'])

    if not _irc.connected:
        await _irc.connect(
            hostname=config["IRC_HOST"],
            port=int(config["IRC_PORT"])
        )
        await _irc.connection_event.wait()

def _validate_request(req: func.HttpRequest) -> HTTPStatus:
    if req.method != "POST":
        return HTTPStatus.METHOD_NOT_ALLOWED

    if "X-GitHub-Event" not in req.headers:
        return HTTPStatus.BAD_REQUEST

    # Verify message is legit
    gh_digest = req.headers.get("X-Hub-Signature")
    if gh_digest is not None:
        secret = config.get("GITHUB_SECRET")
        if not secret:
            logger.error("GitHub sent X-Hub-Signature, but the secret isn't known!")
            return HTTPStatus.INTERNAL_SERVER_ERROR

        body = req.get_body()
        my_digest = f"sha1={hmac.digest(secret.encode(), body, sha1).hex()}"
        if not hmac.compare_digest(my_digest, gh_digest):
            logger.error(f"HMAC Digest failed")
            return HTTPStatus.FORBIDDEN
    elif config.get("GITHUB_SECRET"):
        logger.error("Someone tried to send us a request without X-Hub-Signature!")
        return HTTPStatus.FORBIDDEN
    else:
        logger.warning("Handling a request without signature verification!")

    # Must be ok...
    return HTTPStatus.OK

async def _main(req: func.HttpRequest) -> HTTPStatus:
    global config

    logger.debug("Back in the saddle!")

    async with _config_lock:
        try:
            await asyncio.wait_for(
                _load_config(),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            logger.warning("Timed out loading config")
            config = {}
            raise

    status = _validate_request(req)
    if not status.is_success:
        return status

    handler = _handlers.get(req.headers["X-GitHub-Event"])
    if handler is None:
        return HTTPStatus.NOT_IMPLEMENTED

    # Don't wait forever on a connection to IRC. Azure functions
    # are billed by the second. If we can't connect, just error
    # out.
    try:
        await asyncio.wait_for(
            _connect_irc(),
            timeout=10.0
        )
    except asyncio.TimeoutError:
        logger.warning("Timed out connecting to IRC")
        raise

    # Less likely to take a long time, but we still don't want to
    # dally around.
    try:
        status = await asyncio.wait_for(
            handler(_irc, req.get_json()),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        logger.warning("Timed out handling payload")
        raise

    return status

app = func.FunctionApp()

@app.function_name("Trigger")
@app.route(route="neferus", auth_level=func.AuthLevel.ANONYMOUS)
async def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        status = await _main(req)
    except asyncio.TimeoutError:
        return func.HttpResponse(
            random.choice(_quotes),
            status_code=HTTPStatus.GATEWAY_TIMEOUT
        )
    except Exception as e:
        logger.exception(e)
        return func.HttpResponse(
            random.choice(_quotes),
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR
        )
    else:
        body = None if status.is_success else random.choice(_quotes)
        return func.HttpResponse(
            body,
            status_code=status
        )
