"""Set Schat test identities and the default Matrix homeserver."""

import argparse
import subprocess
from pathlib import Path

SERVER_NAME = "voice.800play.win:5289"
BASE_URL = f"https://{SERVER_NAME}"


def replace(root, relative_path, replacements):
    path = root / relative_path
    content = path.read_text(encoding="utf-8")
    for old, new in replacements:
        if content.count(old) != 1:
            raise ValueError(f"Unexpected upstream configuration: {relative_path}: {old}")
        content = content.replace(old, new)
    path.write_text(content, encoding="utf-8", newline="\n")


def apply_patch(root, filename):
    patch = Path(__file__).with_name(filename).resolve()
    subprocess.run(["git", "-C", str(root), "apply", str(patch)], check=True)


def configure_ios(root):
    apply_patch(root, "ios-call-audio.patch")
    replace(root, "app.yml", [
        ("APP_DISPLAY_NAME: Element X", "APP_DISPLAY_NAME: Schat Matrix"),
        ("APP_GROUP_IDENTIFIER: group.io.element", "APP_GROUP_IDENTIFIER: group.win.play800.schat.matrix"),
        ("BASE_BUNDLE_IDENTIFIER: io.element.elementx", "BASE_BUNDLE_IDENTIFIER: win.play800.schat.matrix"),
        ("DEVELOPMENT_TEAM: 7J4U792NQT", 'DEVELOPMENT_TEAM: ""'),
    ])
    replace(root, "ElementX/Sources/Application/Settings/AppSettings.swift", [
        ('[.managed(serverName: "matrix.org", baseURL: "https://matrix-client.matrix.org")]',
         f'[.managed(serverName: "{SERVER_NAME}", baseURL: "{BASE_URL}")]'),
    ])


def configure_android(root):
    apply_patch(root, "android-call-audio.patch")
    replace(root, "plugins/src/main/kotlin/config/BuildTimeConfig.kt", [
        ('APPLICATION_ID = "io.element.android.x"', 'APPLICATION_ID = "win.play800.schat.matrix"'),
        ('APPLICATION_NAME = "Element X"', 'APPLICATION_NAME = "Schat Matrix"'),
        ('METADATA_HOST_REVERSED: String? = null', 'METADATA_HOST_REVERSED: String? = "win.play800.schat.matrix"'),
    ])
    replace(root, "features/login/impl/src/main/kotlin/io/element/android/features/login/impl/accountprovider/AccountProviderDataSource.kt", [
        ("import io.element.android.libraries.matrix.api.accountprovider.matrixOrgAccountProvider\n", ""),
        ("// else matrix.org.", "// else the Schat homeserver."),
        ("?: matrixOrgAccountProvider", f'?: AccountProvider.Generic(serverName = "{SERVER_NAME}")'),
    ])
    replace(root, "app/build.gradle.kts", [
        ('signingConfig = signingConfigs.getByName("debug")\n\n            optimization',
         "signingConfig = null\n\n            optimization"),
    ])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=("ios", "android"))
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    configure = {"ios": configure_ios, "android": configure_android}[args.platform]
    configure(args.source)
