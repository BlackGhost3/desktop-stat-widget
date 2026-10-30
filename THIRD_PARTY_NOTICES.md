# Third-party notices

Desktop Stat Widget is released under the MIT License (see `LICENSE`). The packaged `DesktopStatWidget.exe`
bundles the following open-source components, which keep their own licenses.

| Component | Used for | License |
| --- | --- | --- |
| [PySide6 (Qt for Python)](https://doc.qt.io/qtforpython-6/) and the [Qt](https://www.qt.io/) libraries | The user interface | LGPL-3.0 (Qt is also available under GPL-3.0 and a commercial license) |
| [psutil](https://github.com/giampaolo/psutil) | CPU, RAM, disk, network and battery readings | BSD-3-Clause |
| [segno](https://github.com/heuer/segno) | Drawing the QR code | BSD-3-Clause |
| [PyInstaller](https://pyinstaller.org/) | Packaging the exe | GPL-2.0 with an exception that allows bundling any program |
| [Python](https://www.python.org/) | The runtime | PSF License |

The Qt libraries are included unmodified, as separate files that the exe unpacks when it starts. Their source code
and license texts are available from the Qt project and from the PySide6 package on PyPI.

The widget also contacts a few public services (ipify, Cloudflare, jsDelivr and GitHub) as described under
"Privacy and network requests" in the README. It doesn't bundle any of their content.
