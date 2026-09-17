# Maintainer notes: publishing UsageSniffer

## PyPI (Track 4)

One-time setup:

```bash
pip install build twine
python -m build            # dist/usagesniffer-1.1.0.tar.gz + .whl
twine upload dist/*        # needs a PyPI token with `pypi` scope
```

After that users install with:

```bash
pipx install usagesniffer
usagesniffer scan --top 10
```

Bump `version` in `pyproject.toml` + `usagesniffer/__init__.py` per release,
then tag `vX.Y.Z` — CI builds, release notes ship from the tag.

## Homebrew (formula template)

Save as `Formula/usagesniffer.rb` in a tap (e.g. `Sleepy-Studio/homebrew-tap`):

```ruby
class Usagesniffer < Formula
  include Language::Python::Virtualenv
  desc "Visualize AI-agent token usage across coding CLIs"
  homepage "https://github.com/Sleepy-Studio/UsageSniffer"
  url "https://github.com/Sleepy-Studio/UsageSniffer/archive/refs/tags/v1.1.0.tar.gz"
  sha256 "<fill from release tarball>"
  license "MIT"
  depends_on "python@3.12"
  def install
    virtualenv_install_with_resources
  end
  test do
    system bin/"usagesniffer", "scan", "--top", "1"
  end
end
```

## AUR (PKGBUILD template)

Save as `PKGBUILD` in an `usagesniffer` AUR package:

```bash
pkgname=usagesniffer
pkgver=1.1.0
pkgrel=1
pkgdesc="Visualize AI-agent token usage across coding CLIs"
arch=('any')
url="https://github.com/Sleepy-Studio/UsageSniffer"
license=('MIT')
depends=('python')
makedepends=('python-build' 'python-installer')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('<fill from release tarball>')
build() { cd "UsageSniffer-$pkgver"; python -m build --wheel --no-isolation; }
package() { cd "UsageSniffer-$pkgver"; python -m installer --destdir="$pkgdir" dist/*.whl; }
```
