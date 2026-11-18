"""Prepare the Schat iPhone app with the patched native call package."""

import argparse
import subprocess
from pathlib import Path

from fork import configure_ios, replace


def apply(root, filename):
    patch = Path(__file__).with_name(filename).resolve()
    subprocess.run(["git", "-C", str(root), "apply", str(patch)], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("native", type=Path)
    args = parser.parse_args()
    configure_ios(args.app)
    apply(args.app, "hd-ios-app.patch")
    apply(args.native, "hd-ios-native.patch")
    replace(args.app, "project.yml", [
        ("CURRENT_PROJECT_VERSION: 4", "CURRENT_PROJECT_VERSION: 6"),
        ("    url: https://github.com/element-hq/element-call-ios # Native implementation\n"
         "    exactVersion: 0.1.0-rc.16\n"
         "    # path: ../element-call-ios",
         "    path: ../element-call-ios"),
    ])
    replace(args.native, "Package.swift", [
        ('        .package(url: "https://github.com/element-hq/matrix-rust-rtc", exact: "0.5.0-rc.11"),\n'
         '        // .package(path: "../matrix-rust-rtc"),',
         '        .package(path: "../matrix-rust-rtc"),'),
        ('swift-snapshot-testing", exact: "1.19.4"', 'swift-snapshot-testing", exact: "1.19.7"'),
    ])
