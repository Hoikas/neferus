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

import argparse
import asyncio
import logging
from pathlib import Path
import signal

import config
import irc
import log
import webhook

def dumpconfig(args):
    config.dump_default_config(args.config)

def gensecret(args):
    import secrets

    # This value was suggested by the GitHub documentation. Disclaimer: I am no cryptographer.
    print(secrets.token_hex(20))

def run(args):
    if args.quiet:
        level = "ERROR"
    elif args.verbose:
        level = "DEBUG"
    else:
        level = "INFO"
    logpath = Path(args.log) if args.log else None
    log.init(level, logpath)
    logging.info("YEE-HAW!")

    # fixme: handle errors
    cfg = config.read_config(args.config)

    loop = asyncio.get_event_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, loop.stop)
    except NotImplementedError:
        # Must be running on Windows...
        pass
    bot = irc.IRCBot(cfg, eventloop=loop)
    web = webhook.GitHub(cfg, bot, loop)

    bot.start()
    web.start()
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        # This is not an error, just exit nao.
        pass
    finally:
        web.stop()
        bot.stop()

        async def _wait_shutdown():
            # copy all tasks, because we're about to make another one.
            tasks = list(asyncio.all_tasks())
            try:
                await asyncio.wait(tasks, timeout=1.0)
            except asyncio.TimeoutError:
                logging.warning("Pending Tasks shutdown timeout! (Who gives a rat's ass?)")

        # Ensure any other pending tasks (eg the IRC client's worker) shuts down.
        loop.run_until_complete(_wait_shutdown())
        loop.close()
    logging.info("Goodbye.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GitHub Webhook Powered IRC Notification Bot")
    parser.add_argument("--config", default="config.ini", type=Path, help="path to configuration file")
    parser.add_argument("--log", default="", help="path to log file")

    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument("-q", "--quiet", action="store_true", help="log only errors")
    log_group.add_argument("-v", "--verbose", action="store_true", help="log lots of stuff")
    
    sub_parsers = parser.add_subparsers(title="command", dest="command", required=True)
    sub_parsers.add_parser("dumpconfig")
    sub_parsers.add_parser("gensecret")
    sub_parsers.add_parser("run")

    args = parser.parse_args()
    globals()[args.command](args)
