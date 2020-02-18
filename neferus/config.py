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

import configparser
from dataclasses import dataclass

@dataclass
class _ConfigItem:
    default : str
    comment : str = ""

    def __repr__(self):
        return self.default


_defaults = {
    "irc": {
        "host": _ConfigItem("localhost"),
        "port": _ConfigItem("6667"),
        "nick": _ConfigItem("Neferus"),
        "channels": _ConfigItem("#notifications"),
    },

    "webhook": {
        "host": _ConfigItem("0.0.0.0"),
        "port": _ConfigItem("8000"),
        "secret": _ConfigItem(""),
    }
}

_header = """
;    This file is part of neferus
;
;    neferus is free software: you can redistribute it and/or modify
;    it under the terms of the GNU Affero General Public License as published
;    by the Free Software Foundation, either version 3 of the License, or
;    (at your option) any later version.
;
;    neferus is distributed in the hope that it will be useful,
;    but WITHOUT ANY WARRANTY; without even the implied warranty of
;    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
;    GNU Affero General Public License for more details.
;
;    You should have received a copy of the GNU Affero General Public License
;    along with neferus.  If not, see <https://www.gnu.org/licenses/>.

"""

def dump_default_config(config_path):
    with config_path.open("w") as fp:
        fp.write(_header.lstrip())
        for section, values in _defaults.items():
            fp.write(f"\n[{section}]\n\n")
            for option_name, option_value in values.items():
                if option_value.comment:
                    for comment_line in option_value.comment.split("\n"):
                        fp.write(f"; {comment_line}\n")
                fp.write(f"{option_name} = {option_value}\n\n")

def read_config(config_path):
    parser = configparser.ConfigParser()
    parser.read_dict(_defaults)
    if config_path.is_file():
        parser.read(config_path)
        return parser
    return None
