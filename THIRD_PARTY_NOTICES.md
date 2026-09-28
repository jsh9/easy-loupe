# Third-Party Notices

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Bundled Components](#1-bundled-components)
- [2. License Texts](#2-license-texts)
- [3. Source Code](#3-source-code)

______________________________________________________________________

<!--TOC-->

EasyLoupe is free software licensed under the GNU General Public License,
version 3 or (at your option) any later version. See [LICENSE](LICENSE).

The packaged EasyLoupe apps for macOS and Windows also include the third-party
components below. Each component remains under its own license.

## 1. Bundled Components

| Component                                            | Used for                            | License                                                                                                            | Source                                                                                                                       |
| ---------------------------------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| [Python](https://www.python.org/)                    | App runtime                         | PSF-2.0, with [bundled components](https://docs.python.org/3/license.html) under their own licenses                | https://github.com/python/cpython                                                                                            |
| [Qt](https://www.qt.io/), via PySide6 and Shiboken6  | User interface                      | LGPL-3.0-only, with [bundled components](https://doc.qt.io/qt-6/licenses-used-in-qt.html) under their own licenses | https://code.qt.io/                                                                                                          |
| [Pillow](https://python-pillow.github.io/)           | Image loading and resizing          | MIT-CMU, with bundled codec libraries under their own licenses                                                     | https://github.com/python-pillow/Pillow                                                                                      |
| pillow-heif                                          | HEIC/HEIF decoding                  | BSD-3-Clause                                                                                                       | https://github.com/bigcat88/pillow_heif                                                                                      |
| libheif (bundled by pillow-heif)                     | HEIF container decoding             | LGPL-3.0                                                                                                           | https://github.com/strukturag/libheif                                                                                        |
| libde265 (bundled by pillow-heif)                    | HEVC decoding                       | LGPL-3.0                                                                                                           | https://github.com/strukturag/libde265                                                                                       |
| x265 (bundled by pillow-heif)                        | HEVC codec                          | GPL-2.0-or-later                                                                                                   | https://bitbucket.org/multicoreware/x265_git/src/master/                                                                     |
| pillow-jxl-plugin                                    | JPEG XL decoding                    | GPL-3.0-or-later                                                                                                   | https://github.com/Isotr0py/pillow-jpegxl-plugin                                                                             |
| libjxl (built into pillow-jxl-plugin)                | JPEG XL codec                       | BSD-3-Clause, with a royalty-free patent grant                                                                     | https://github.com/libjxl/libjxl                                                                                             |
| rawpy                                                | RAW decoding                        | MIT                                                                                                                | https://github.com/letmaik/rawpy                                                                                             |
| LibRaw (bundled by rawpy)                            | RAW decoding                        | LGPL-2.1 or CDDL-1.0                                                                                               | https://github.com/LibRaw/LibRaw                                                                                             |
| JasPer, libjpeg-turbo, Little CMS (bundled by rawpy) | Image codecs and color management   | JasPer License 2.0; IJG, BSD-3-Clause, and Zlib; MIT                                                               | https://github.com/jasper-software/jasper, https://github.com/libjpeg-turbo/libjpeg-turbo, https://github.com/mm2/Little-CMS |
| ImageHash                                            | Scene detection                     | BSD-2-Clause                                                                                                       | https://github.com/JohannesBuchner/imagehash                                                                                 |
| NumPy                                                | Numeric support                     | BSD-3-Clause, with bundled components under their own licenses                                                     | https://github.com/numpy/numpy                                                                                               |
| SciPy                                                | Numeric support for ImageHash       | BSD-3-Clause, with bundled components under their own licenses                                                     | https://github.com/scipy/scipy                                                                                               |
| PyWavelets                                           | Numeric support for ImageHash       | MIT                                                                                                                | https://github.com/PyWavelets/pywt                                                                                           |
| packaging                                            | Version checks in pillow-jxl-plugin | Apache-2.0 OR BSD-2-Clause                                                                                         | https://github.com/pypa/packaging                                                                                            |
| [ExifTool](https://exiftool.org/)                    | Photo metadata reading              | Same terms as Perl (Artistic License or GPL)                                                                       | https://github.com/exiftool/exiftool                                                                                         |

## 2. License Texts

License files for the bundled Python packages are included inside the packaged
app, in each package's metadata folder (`<package>-<version>.dist-info`). Every
component's full license is also available from its source link above.

## 3. Source Code

EasyLoupe's complete source code is available at
[github.com/jsh9/easy-loupe](https://github.com/jsh9/easy-loupe). Source code
for each component above is available from its source link. The exact component
versions used for a release are recorded in `uv.lock` at that release's tag.
