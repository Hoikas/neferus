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
from pathlib import Path

import config
import irc
import log
import webhook

def dumpconfig(args):
    config.dump_default_config(args.config)

def run(args):
    if args.quiet:
        level = "ERROR"
    elif args.verbose:
        level = "DEBUG"
    else:
        level = "INFO"
    # todo: log file output
    log.init(level, None)

    # fixme: handle errors
    cfg = config.read_config(args.config)

    loop = asyncio.get_event_loop()
    bot = irc.IRCBot(cfg, eventloop=loop)
    web = webhook.GitHub(cfg, bot, loop)

    bot.start()
    web.start()
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        web.stop()
        bot.stop()
        loop.close()
    finally:
        loop.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GitHub Webhook Powered IRC Notification Bot")
    parser.add_argument("--config", default="config.ini", type=Path, help="path to configuration file")

    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument("-q", "--quiet", action="store_true", help="log only errors")
    log_group.add_argument("-v", "--verbose", action="store_true", help="log lots of stuff")
    
    sub_parsers = parser.add_subparsers(title="command", dest="command", required=True)
    dumpconfig_parser = sub_parsers.add_parser("dumpconfig")
    generate_parser = sub_parsers.add_parser("run")

    args = parser.parse_args()
    globals()[args.command](args)
