#!/usr/bin/env python3
"""Build a cloud-init NoCloud seed ISO (label CIDATA) from user-data + meta-data.

Usage: make-seed.py <user-data> <meta-data> <output.iso>
No root required; uses pycdlib.
"""
from __future__ import annotations

import io
import os
import sys

try:
    import pycdlib
except ImportError:
    sys.exit("pycdlib not installed. Run: pip install pycdlib")


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    user_data, meta_data, out = sys.argv[1:4]

    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, joliet=3, rock_ridge="1.09", vol_ident="CIDATA")

    for path in (user_data, meta_data):
        name = os.path.basename(path)          # "user-data" / "meta-data"
        iso_name = name.upper().replace("-", "_") + ".;1"  # ISO9660 8.3-ish
        with open(path, "rb") as fh:
            data = fh.read()
        iso.add_fp(
            io.BytesIO(data),
            len(data),
            "/" + iso_name,
            rr_name=name,
            joliet_path="/" + name,
        )

    iso.write(out)
    iso.close()
    print(out)


if __name__ == "__main__":
    main()
