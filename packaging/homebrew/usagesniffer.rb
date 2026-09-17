class Usagesniffer < Formula
  include Language::Python::Virtualenv
  desc "Visualize AI-agent token usage across coding CLIs"
  homepage "https://github.com/Sleepy-Studio/UsageSniffer"
  url "https://github.com/Sleepy-Studio/UsageSniffer/archive/refs/tags/v1.3.0.tar.gz"
  sha256 "FILLME"
  license "MIT"
  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    system bin/"usagesniffer", "scan", "--top", "1"
  end
end
