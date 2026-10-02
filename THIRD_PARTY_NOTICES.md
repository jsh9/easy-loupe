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

| Component                                                                                     | Used for                                       | License                                                                                                                             | License text in the app                                                                                 | Source                                                                  |
| --------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| [Python](https://www.python.org/)                                                             | App runtime                                    | PSF-2.0                                                                                                                             | `third_party_licenses/Python.txt`                                                                       | https://github.com/python/cpython                                       |
| [Qt](https://www.qt.io/), PySide6, and Shiboken6                                              | User interface                                 | LGPL-3.0-only; Qt's own third-party components are listed in [Licenses Used in Qt](https://doc.qt.io/qt-6/licenses-used-in-qt.html) | `third_party_licenses/Qt-PySide6-Shiboken6-LGPL-3.0.txt`, which builds on the GPL-3.0 text in `LICENSE` | https://code.qt.io/                                                     |
| [Pillow](https://python-pillow.github.io/)                                                    | Image loading and resizing                     | MIT-CMU, with bundled codec libraries under their own licenses                                                                      | Pillow package metadata, including the bundled libraries' licenses                                      | https://github.com/python-pillow/Pillow                                 |
| pillow-heif                                                                                   | HEIC/HEIF decoding                             | BSD-3-Clause                                                                                                                        | pillow-heif package metadata                                                                            | https://github.com/bigcat88/pillow_heif                                 |
| libheif (bundled by pillow-heif)                                                              | HEIF container decoding                        | LGPL-3.0                                                                                                                            | `third_party_licenses/libheif.txt`                                                                      | https://github.com/strukturag/libheif                                   |
| libde265 (bundled by pillow-heif)                                                             | HEVC decoding                                  | LGPL-3.0                                                                                                                            | `third_party_licenses/libde265.txt`                                                                     | https://github.com/strukturag/libde265                                  |
| x265 (bundled by pillow-heif)                                                                 | HEVC codec                                     | GPL-2.0-or-later                                                                                                                    | `third_party_licenses/x265.txt`                                                                         | https://bitbucket.org/multicoreware/x265_git/src/master/                |
| pillow-jxl-plugin                                                                             | JPEG XL decoding                               | GPL-3.0-or-later                                                                                                                    | pillow-jxl-plugin package metadata                                                                      | https://github.com/Isotr0py/pillow-jpegxl-plugin                        |
| libjxl (bundled by pillow-jxl-plugin)                                                         | JPEG XL codec                                  | BSD-3-Clause, with a royalty-free patent grant                                                                                      | `third_party_licenses/libjxl.txt`                                                                       | https://github.com/libjxl/libjxl                                        |
| Brotli (bundled by pillow-jxl-plugin; Python bindings from the brotli package)                | Compression and JPEG XL metadata decompression | MIT                                                                                                                                 | `third_party_licenses/Brotli.txt` and brotli package metadata                                           | https://github.com/google/brotli                                        |
| Highway (bundled by pillow-jxl-plugin)                                                        | SIMD support                                   | Apache-2.0 or BSD-3-Clause                                                                                                          | `third_party_licenses/Highway.txt`                                                                      | https://github.com/google/highway                                       |
| Little CMS (bundled by pillow-jxl-plugin and rawpy)                                           | Color management                               | MIT                                                                                                                                 | `third_party_licenses/Little-CMS.txt`                                                                   | https://github.com/mm2/Little-CMS                                       |
| rawpy                                                                                         | RAW decoding                                   | MIT                                                                                                                                 | rawpy package metadata                                                                                  | https://github.com/letmaik/rawpy                                        |
| LibRaw (bundled by rawpy)                                                                     | RAW decoding                                   | LGPL-2.1 or CDDL-1.0                                                                                                                | `third_party_licenses/LibRaw.txt`                                                                       | https://github.com/LibRaw/LibRaw                                        |
| JasPer (bundled by rawpy)                                                                     | JPEG 2000 decoding                             | JasPer License 2.0                                                                                                                  | `third_party_licenses/JasPer.txt`                                                                       | https://github.com/jasper-software/jasper                               |
| libjpeg-turbo (bundled by rawpy)                                                              | JPEG decoding                                  | IJG, BSD-3-Clause, and Zlib                                                                                                         | `third_party_licenses/libjpeg-turbo.txt`                                                                | https://github.com/libjpeg-turbo/libjpeg-turbo                          |
| GCC runtime libraries (Windows; bundled by pillow-heif and pillow-jxl-plugin)                 | C and C++ runtime                              | GPL-3.0 with the GCC Runtime Library Exception                                                                                      | `third_party_licenses/GCC-Runtime-Library-Exception.txt` and `LICENSE`                                  | https://gcc.gnu.org/                                                    |
| mingw-w64 winpthreads (Windows; bundled by pillow-heif and pillow-jxl-plugin)                 | Threading runtime                              | MIT and BSD-3-Clause                                                                                                                | `third_party_licenses/mingw-w64-winpthreads.txt`                                                        | https://www.mingw-w64.org/                                              |
| Microsoft OpenMP runtime, `vcomp140.dll` (Windows; bundled by rawpy)                          | Parallel processing                            | Microsoft Visual C++ Redistributable terms                                                                                          | Not applicable                                                                                          | https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files |
| ImageHash                                                                                     | Scene detection                                | BSD-2-Clause                                                                                                                        | ImageHash package metadata                                                                              | https://github.com/JohannesBuchner/imagehash                            |
| NumPy                                                                                         | Numeric support                                | BSD-3-Clause, with bundled components under their own licenses                                                                      | NumPy package metadata                                                                                  | https://github.com/numpy/numpy                                          |
| SciPy                                                                                         | Numeric support for ImageHash                  | BSD-3-Clause, with bundled components under their own licenses                                                                      | SciPy package metadata                                                                                  | https://github.com/scipy/scipy                                          |
| PyWavelets                                                                                    | Numeric support for ImageHash                  | MIT                                                                                                                                 | PyWavelets package metadata                                                                             | https://github.com/PyWavelets/pywt                                      |
| packaging                                                                                     | Version checks in pillow-jxl-plugin            | Apache-2.0 or BSD-2-Clause                                                                                                          | packaging package metadata                                                                              | https://github.com/pypa/packaging                                       |
| [ExifTool](https://exiftool.org/), including the Perl runtime in the Windows ExifTool package | Photo metadata reading                         | Same terms as Perl: Artistic License or GPL                                                                                         | `third_party_licenses/ExifTool.txt`                                                                     | https://github.com/exiftool/exiftool                                    |

## 2. License Texts

Packaged apps include these license files in their data folder
(`EasyLoupe.app/Contents/Resources` on macOS, `EasyLoupe/_internal` on
Windows):

- `LICENSE`: EasyLoupe's license, the full GPL-3.0 text.
- `THIRD_PARTY_NOTICES.md`: this file.
- `third_party_licenses/`: license texts for the components above whose Python
  package metadata does not include them. Each file starts with the component
  it covers and where its text came from.
- `<package>-<version>.dist-info/`: each bundled Python package's metadata
  folder, which contains the license files the package ships with.

The build scripts check the built app for these files and fail if any are
missing.

## 3. Source Code

EasyLoupe's complete source code is available at
[github.com/jsh9/easy-loupe](https://github.com/jsh9/easy-loupe). Source code
for each component above is available from its source link. The exact component
versions used for a release are recorded in `uv.lock` at that release's tag.
