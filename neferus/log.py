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

import functools
import logging
import logging.handlers

_level = None
_path = None

class _Logging(logging.Logger):
    def __init__(self, name):
        super().__init__(name, _level)
        if _path is None:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s"))
        else:
            handler = logging.handlers.RotatingFileHandler(_path.joinpath(f"{name}.log"))
            handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
        self.addHandler(handler)


def init(level, path):
    logging.setLoggerClass(_Logging)

    global _level, _path
    _level = level
    _path = path
