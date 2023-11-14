# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import ansible

ANSIBLE_VERSION = tuple([int(v) for v in ansible.__version__.split(".")[:3]])
