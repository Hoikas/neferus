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
_handlers = []

class _Logging(logging.Logger):
    def __init__(self, name):
        super().__init__(name, _level)
        for i in _handlers:
            self.addHandler(i)


def init(level, path=None):
    global _level, _handler
    _level = level

    fmt = logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s")
    if path is not None:
        if path.exists():
            path = path.joinpath("neferus.log") if path.is_dir() else path
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(path.with_suffix(".log"))
        handler.setFormatter(fmt)
        _handlers.append(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(fmt)
    _handlers.append(handler)

    logging.basicConfig(level=level, handlers=_handlers)
    logging.setLoggerClass(_Logging)
