# Third-Party Licenses

Resistine AI EDR includes, bundles, depends on, or installs the third-party
software listed in this document. It is provided for transparency, compliance
audits, and enterprise procurement reviews.

**Resistine AI EDR itself is licensed under GPL-2.0-or-later.** See
[`LICENSE.md`](LICENSE.md) for the full license text.

The "Python Dependencies" section below is **auto-generated** at release time
by `scripts/build/generate-license-third-party.sh` using `pip-licenses` from
the installed virtual environment. Do not edit it by hand — your changes will
be overwritten on the next release build.

The "Bundled and Installed Components" section is hand-maintained because it
covers binaries and tools that are not Python packages (ClamAV, WireGuard,
Wazuh, Sysmon, Sparkle, etc.). It lives in
`scripts/build/license-3rd-party-bundled.md` and is appended verbatim to this
file at generation time.

If you believe any third-party software is used by Resistine but is not
listed here, or if license information needs correction, please open an issue
at https://github.com/Resistine/Resistine-Desktop/issues.

## Python Dependencies

| Name                                              | Version     | License                                                        | URL                                                                                                                |
|---------------------------------------------------|-------------|----------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------|
| CairoSVG                                          | 2.9.0       | LGPL-3.0-or-later                                              | https://courtbouillon.org/cairosvg                                                                                 |
| Markdown                                          | 3.10.2      | BSD-3-Clause                                                   | https://Python-Markdown.github.io/                                                                                 |
| Pygments                                          | 2.20.0      | BSD-2-Clause                                                   | https://pygments.org                                                                                               |
| SecretStorage                                     | 3.5.0       | BSD-3-Clause                                                   | https://github.com/mitya57/secretstorage                                                                           |
| altgraph                                          | 0.17.5      | MIT License                                                    | https://altgraph.readthedocs.io                                                                                    |
| annotated-types                                   | 0.7.0       | MIT License                                                    | https://github.com/annotated-types/annotated-types                                                                 |
| anyio                                             | 4.13.0      | MIT                                                            | https://anyio.readthedocs.io/en/stable/versionhistory.html                                                         |
| cairocffi                                         | 1.7.1       | BSD License                                                    | https://doc.courtbouillon.org/cairocffi/stable/changelog.html                                                      |
| certifi                                           | 2026.5.20   | Mozilla Public License 2.0 (MPL 2.0)                           | https://github.com/certifi/python-certifi                                                                          |
| cffi                                              | 2.0.0       | MIT                                                            | https://cffi.readthedocs.io/en/latest/whatsnew.html                                                                |
| charset-normalizer                                | 3.4.7       | MIT                                                            | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md                                               |
| contourpy                                         | 1.3.3       | BSD License                                                    | https://github.com/contourpy/contourpy                                                                             |
| coverage                                          | 7.13.5      | Apache-2.0                                                     | https://github.com/coveragepy/coveragepy                                                                           |
| cryptography                                      | 48.0.0      | Apache-2.0 OR BSD-3-Clause                                     | https://github.com/pyca/cryptography                                                                               |
| cssselect2                                        | 0.9.0       | BSD License                                                    | https://doc.courtbouillon.org/cssselect2/                                                                          |
| customtkinter                                     | 5.2.2       | MIT License                                                    | https://customtkinter.tomschimansky.com                                                                            |
| cycler                                            | 0.12.1      | BSD License                                                    | https://matplotlib.org/cycler/                                                                                     |
| darkdetect                                        | 0.8.0       | BSD License                                                    | http://github.com/albertosottile/darkdetect                                                                        |
| decorator                                         | 5.3.1       | BSD-2-Clause                                                   | UNKNOWN                                                                                                            |
| defusedxml                                        | 0.7.1       | Python Software Foundation License                             | https://github.com/tiran/defusedxml                                                                                |
| distro                                            | 1.9.0       | Apache Software License                                        | https://github.com/python-distro/distro                                                                            |
| elevate                                           | 0.1.3       | MIT                                                            | https://github.com/barneygale/elevate                                                                              |
| fonttools                                         | 4.62.1      | MIT                                                            | http://github.com/fonttools/fonttools                                                                              |
| googleapis-common-protos                          | 1.73.1      | Apache Software License                                        | https://github.com/googleapis/google-cloud-python/tree/main/packages/googleapis-common-protos                      |
| grpcio                                            | 1.80.0      | Apache-2.0                                                     | https://grpc.io                                                                                                    |
| h11                                               | 0.16.0      | MIT License                                                    | https://github.com/python-hyper/h11                                                                                |
| html2text                                         | 2025.4.15   | GPL-3.0-or-later                                               | https://github.com/Alir3z4/html2text/                                                                              |
| httpcore                                          | 1.0.9       | BSD-3-Clause                                                   | https://www.encode.io/httpcore/                                                                                    |
| httpx                                             | 0.28.1      | BSD License                                                    | https://github.com/encode/httpx                                                                                    |
| idna                                              | 3.18        | BSD-3-Clause                                                   | https://github.com/kjd/idna                                                                                        |
| importlib_metadata                                | 8.7.1       | Apache-2.0                                                     | https://github.com/python/importlib_metadata                                                                       |
| iniconfig                                         | 2.3.0       | MIT                                                            | https://github.com/pytest-dev/iniconfig                                                                            |
| jaraco.classes                                    | 3.4.0       | MIT License                                                    | https://github.com/jaraco/jaraco.classes                                                                           |
| jaraco.context                                    | 6.1.2       | MIT                                                            | https://github.com/jaraco/jaraco.context                                                                           |
| jaraco.functools                                  | 4.5.0       | MIT                                                            | https://github.com/jaraco/jaraco.functools                                                                         |
| jeepney                                           | 0.9.0       | MIT                                                            | https://gitlab.com/takluyver/jeepney                                                                               |
| jiter                                             | 0.15.0      | MIT                                                            | https://github.com/pydantic/jiter/                                                                                 |
| keyring                                           | 25.7.0      | MIT                                                            | https://github.com/jaraco/keyring                                                                                  |
| kiwisolver                                        | 1.5.0       | BSD License                                                    | https://github.com/nucleic/kiwi                                                                                    |
| loguru                                            | 0.7.3       | MIT License                                                    | https://github.com/Delgan/loguru                                                                                   |
| macholib                                          | 1.16.4      | MIT License                                                    | http://github.com/ronaldoussoren/macholib                                                                          |
| matplotlib                                        | 3.10.9      | Python Software Foundation License                             | https://matplotlib.org                                                                                             |
| more-itertools                                    | 11.1.0      | MIT                                                            | https://github.com/more-itertools/more-itertools                                                                   |
| numpy                                             | 2.4.4       | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0             | https://numpy.org                                                                                                  |
| openai                                            | 2.41.0      | Apache Software License                                        | https://github.com/openai/openai-python                                                                            |
| opentelemetry-api                                 | 1.42.1      | Apache-2.0                                                     | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-api                                 |
| opentelemetry-exporter-otlp                       | 1.42.1      | Apache-2.0                                                     | https://github.com/open-telemetry/opentelemetry-python/tree/main/exporter/opentelemetry-exporter-otlp              |
| opentelemetry-exporter-otlp-proto-common          | 1.42.1      | Apache-2.0                                                     | https://github.com/open-telemetry/opentelemetry-python/tree/main/exporter/opentelemetry-exporter-otlp-proto-common |
| opentelemetry-exporter-otlp-proto-grpc            | 1.42.1      | Apache-2.0                                                     | https://github.com/open-telemetry/opentelemetry-python/tree/main/exporter/opentelemetry-exporter-otlp-proto-grpc   |
| opentelemetry-exporter-otlp-proto-http            | 1.42.1      | Apache-2.0                                                     | https://github.com/open-telemetry/opentelemetry-python/tree/main/exporter/opentelemetry-exporter-otlp-proto-http   |
| opentelemetry-proto                               | 1.42.1      | Apache-2.0                                                     | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-proto                               |
| opentelemetry-sdk                                 | 1.42.1      | Apache-2.0                                                     | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-sdk                                 |
| opentelemetry-semantic-conventions                | 0.63b1      | Apache-2.0                                                     | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-semantic-conventions                |
| packaging                                         | 26.2        | Apache-2.0 OR BSD-2-Clause                                     | https://github.com/pypa/packaging                                                                                  |
| pillow                                            | 12.2.0      | MIT-CMU                                                        | https://python-pillow.github.io                                                                                    |
| pluggy                                            | 1.6.0       | MIT License                                                    | UNKNOWN                                                                                                            |
| protobuf                                          | 6.33.6      | 3-Clause BSD License                                           | https://developers.google.com/protocol-buffers/                                                                    |
| pycparser                                         | 3.0         | BSD-3-Clause                                                   | https://github.com/eliben/pycparser                                                                                |
| pydantic                                          | 2.13.4      | MIT                                                            | https://github.com/pydantic/pydantic                                                                               |
| pydantic_core                                     | 2.46.4      | MIT                                                            | https://github.com/pydantic                                                                                        |
| pyinstaller                                       | 6.20.0      | GNU General Public License v2 (GPLv2)                          | https://pyinstaller.org                                                                                            |
| pyinstaller-hooks-contrib                         | 2026.4      | Apache Software License; GNU General Public License v2 (GPLv2) | https://github.com/pyinstaller/pyinstaller-hooks-contrib                                                           |
| pyobjc                                            | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-core                                       | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ARKit                            | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-AVFoundation                     | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-AVKit                            | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-AVRouting                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Accessibility                    | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Accounts                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-AdServices                       | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-AdSupport                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-AddressBook                      | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-AppTrackingTransparency          | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-AppleScriptKit                   | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-AppleScriptObjC                  | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ApplicationServices              | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-AudioVideoBridging               | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-AuthenticationServices           | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-AutomaticAssessmentConfiguration | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Automator                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-BackgroundAssets                 | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-BrowserEngineKit                 | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-BusinessChat                     | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CFNetwork                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CalendarStore                    | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CallKit                          | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Carbon                           | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Cinematic                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ClassKit                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CloudKit                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Cocoa                            | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Collaboration                    | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ColorSync                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CompositorServices               | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Contacts                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ContactsUI                       | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreAudio                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreAudioKit                     | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreBluetooth                    | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreData                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreHaptics                      | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreLocation                     | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreMIDI                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreML                           | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreMedia                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreMediaIO                      | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreMotion                       | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreServices                     | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreSpotlight                    | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreText                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CoreWLAN                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-CryptoTokenKit                   | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-DVDPlayback                      | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-DataDetection                    | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-DeviceCheck                      | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-DeviceDiscoveryExtension         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-DictionaryServices               | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-DiscRecording                    | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-DiscRecordingUI                  | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-DiskArbitration                  | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-EventKit                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ExceptionHandling                | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ExecutionPolicy                  | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ExtensionKit                     | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ExternalAccessory                | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-FSEvents                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-FSKit                            | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-FileProvider                     | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-FileProviderUI                   | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-FinderSync                       | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-GameCenter                       | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-GameController                   | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-GameKit                          | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-GameSave                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-GameplayKit                      | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-HealthKit                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-IOBluetooth                      | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-IOBluetoothUI                    | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-IOSurface                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ImageCaptureCore                 | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-InputMethodKit                   | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-InstallerPlugins                 | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-InstantMessage                   | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Intents                          | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-IntentsUI                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-KernelManagement                 | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-LatentSemanticMapping            | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-LaunchServices                   | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-LinkPresentation                 | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-LocalAuthentication              | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-LocalAuthenticationEmbeddedUI    | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-MLCompute                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-MailKit                          | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-MapKit                           | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-MediaAccessibility               | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-MediaExtension                   | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-MediaLibrary                     | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-MediaPlayer                      | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-MediaToolbox                     | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Metal                            | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-MetalFX                          | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-MetalKit                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-MetalPerformanceShaders          | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-MetalPerformanceShadersGraph     | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-MetricKit                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ModelIO                          | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-MultipeerConnectivity            | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-NaturalLanguage                  | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-NetFS                            | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Network                          | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-NetworkExtension                 | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-NotificationCenter               | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-OSAKit                           | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-OSLog                            | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-OpenDirectory                    | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-PHASE                            | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-PassKit                          | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-PencilKit                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Photos                           | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-PhotosUI                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-PreferencePanes                  | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-PushKit                          | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Quartz                           | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-QuickLookThumbnailing            | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ReplayKit                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SafariServices                   | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SafetyKit                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SceneKit                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ScreenCaptureKit                 | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ScreenSaver                      | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ScreenTime                       | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ScriptingBridge                  | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SearchKit                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Security                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SecurityFoundation               | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SecurityInterface                | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SecurityUI                       | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SensitiveContentAnalysis         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ServiceManagement                | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SharedWithYou                    | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SharedWithYouCore                | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ShazamKit                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Social                           | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SoundAnalysis                    | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Speech                           | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SpriteKit                        | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-StoreKit                         | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Symbols                          | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SyncServices                     | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SystemConfiguration              | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-SystemExtensions                 | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-ThreadNetwork                    | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-UniformTypeIdentifiers           | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-UserNotifications                | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-UserNotificationsUI              | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-VideoSubscriberAccount           | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-VideoToolbox                     | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Virtualization                   | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-Vision                           | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-WebKit                           | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-iTunesLibrary                    | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-libdispatch                      | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyobjc-framework-libxpc                           | 12.2        | MIT                                                            | https://github.com/ronaldoussoren/pyobjc                                                                           |
| pyparsing                                         | 3.3.2       | MIT                                                            | https://github.com/pyparsing/pyparsing/                                                                            |
| pytest                                            | 9.0.3       | MIT                                                            | https://docs.pytest.org/en/latest/                                                                                 |
| pytest-cov                                        | 7.1.0       | MIT                                                            | https://pytest-cov.readthedocs.io/en/latest/changelog.html                                                         |
| pytest-mock                                       | 3.15.1      | MIT License                                                    | https://github.com/pytest-dev/pytest-mock/                                                                         |
| pytest-timeout                                    | 2.4.0       | DFSG approved; MIT License                                     | https://github.com/pytest-dev/pytest-timeout                                                                       |
| python-dateutil                                   | 2.9.0.post0 | Apache Software License; BSD License                           | https://github.com/dateutil/dateutil                                                                               |
| python-dotenv                                     | 1.2.2       | BSD-3-Clause                                                   | https://github.com/theskumar/python-dotenv                                                                         |
| python-wireguard                                  | 0.2.2       | GPL-3.0-or-later                                               | https://github.com/jarnoaxel/python-wireguard                                                                      |
| pyuac                                             | 0.0.3       | MIT License                                                    | https://github.com/Preston-Landers/pyuac                                                                           |
| requests                                          | 2.34.2      | Apache Software License                                        | https://github.com/psf/requests                                                                                    |
| six                                               | 1.17.0      | MIT License                                                    | https://github.com/benjaminp/six                                                                                   |
| sniffio                                           | 1.3.1       | Apache Software License; MIT License                           | https://github.com/python-trio/sniffio                                                                             |
| tee                                               | 0.0.3       | MIT License                                                    | https://github.com/algrebe/python-tee                                                                              |
| tinycss2                                          | 1.5.1       | BSD License                                                    | https://www.courtbouillon.org/tinycss2                                                                             |
| tkinterweb                                        | 4.25.3      | Freeware; MIT License                                          | https://github.com/Andereoo/TkinterWeb                                                                             |
| tkinterweb-tkhtml                                 | 2.1.1       | Freeware; MIT License                                          | https://github.com/Andereoo/TkinterWeb-Tkhtml                                                                      |
| tqdm                                              | 4.68.1      | MPL-2.0 AND MIT                                                | https://tqdm.github.io                                                                                             |
| typing-inspection                                 | 0.4.2       | MIT                                                            | https://github.com/pydantic/typing-inspection                                                                      |
| typing_extensions                                 | 4.15.0      | PSF-2.0                                                        | https://github.com/python/typing_extensions                                                                        |
| urllib3                                           | 2.7.0       | MIT                                                            | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst                                                           |
| webencodings                                      | 0.5.1       | BSD License                                                    | https://github.com/SimonSapin/python-webencodings                                                                  |
| zipp                                              | 3.23.0      | MIT                                                            | https://github.com/jaraco/zipp                                                                                     |

## Bundled and Installed Components

These components are either packaged inside the Resistine installer or
downloaded directly from the original vendor at install time. They are
governed by their own licenses and are not Python packages, so they do not
appear in the auto-generated section above.

### ClamAV
- **License**: GPL-2.0
- **Source**: https://www.clamav.net/
- **Used for**: On-access and on-demand antivirus scanning
- **Distribution**: Bundled in installer on macOS (custom build from the
  `Resistine/ClamAV-Mac` CI). Installed via system package manager on Linux
  (`apt`, `yum`, `dnf`, `pacman`). Not used on Windows — see Microsoft
  Defender AMSI below.

### WireGuard
- **License**: GPL-2.0 (kernel module and tools) / MIT (Go userspace implementation)
- **Source**: https://www.wireguard.com/
- **Used for**: VPN tunnel
- **Distribution**: Bundled in installer on Windows (WireGuard 1.1 MSI).
  Uses system WireGuard on Linux. Uses a Resistine-built Swift CLI
  (`resistine-vpn-cli`, GPL-2.0+) that bridges to macOS NetworkExtension.

### Wazuh Agent
- **License**: GPL-2.0
- **Source**: https://wazuh.com/ — https://github.com/wazuh/wazuh
- **Used for**: SIEM / endpoint monitoring agent
- **Distribution**: Downloaded from `packages.wazuh.com` when the user
  enables the Wazuh plugin. Not bundled in the Resistine installer.

### Microsoft Sysinternals Sysmon (Windows only)
- **License**: Microsoft Sysinternals License Terms (proprietary; free for
  personal and commercial use)
- **Source**: https://learn.microsoft.com/sysinternals/downloads/sysmon
- **Used for**: Enhanced Windows event monitoring (process, network,
  registry, file events) consumed by the Wazuh agent
- **Distribution**: Downloaded directly from Microsoft
  (`download.sysinternals.com`) when the user enables Wazuh on Windows.
  **Resistine does not redistribute, repackage, or modify the Sysmon
  binary.** The user implicitly accepts Microsoft's Sysinternals license
  via the `-accepteula` flag at install.

### SwiftOnSecurity Sysmon Config (Windows only)
- **License**: MIT
- **Source**: https://github.com/SwiftOnSecurity/sysmon-config
- **Used for**: Default Sysmon configuration (event filtering rules)
- **Distribution**: Downloaded from the SwiftOnSecurity GitHub repository
  at Sysmon install time.

### Microsoft Defender AMSI (Windows only)
- **License**: Part of the Microsoft Windows operating system
- **Used for**: Real-time antivirus scanning on Windows
- **Distribution**: Built into Windows. Resistine calls into the system
  AMSI interface. No additional software installed.

### Python 3.13
- **License**: Python Software Foundation License (PSF)
- **Source**: https://www.python.org/
- **Distribution**: Bundled inside the Windows MSI installer so end users
  do not need a separate Python installation. macOS and Linux use the
  system Python.

### Tcl/Tk
- **License**: Tcl/Tk License (BSD-style, permissive)
- **Source**: https://www.tcl.tk/
- **Used for**: GUI rendering (via Python's `tkinter` and CustomTkinter)
- **Distribution**: Shipped with Python on Windows. Provided by Homebrew
  on macOS / system packages on Linux.

### Sparkle (macOS only)
- **License**: MIT
- **Source**: https://sparkle-project.org/
- **Used for**: macOS auto-update mechanism
- **Distribution**: Built into the macOS app bundle.

### resistine-vpn-cli (macOS only)
- **License**: GPL-2.0-or-later (Resistine-authored)
- **Source**: https://github.com/Resistine/resistine-vpn-macos
- **Used for**: Swift CLI bridge between Python and the macOS
  NetworkExtension that hosts the WireGuard tunnel
- **Distribution**: Bundled in the macOS .app.

---

## Build-Time Tools (not shipped with the product)

These tools run on the build machine and are not distributed inside the
Resistine installer.

- **PyInstaller** (GPL-2.0-or-later, bootloader carries a linking
  exception) — packages the Python source into a self-contained app
- **Inno Setup** (proprietary, free for any use including commercial) —
  builds the Windows MSI installer
- **create-dmg** (MIT) — builds the macOS DMG
