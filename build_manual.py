"""Build the manual and save a PDF named with its document version."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def main():
    source = Path(sys.argv[1] if len(sys.argv) > 1 else
                  Path(__file__).with_name("マニュアル.tex")).resolve()
    if source.suffix != ".tex":
        source = source.with_suffix(".tex")
    output = (Path(sys.argv[2]).resolve() if len(sys.argv) > 2
              else source.parent / "build")
    match = re.search(r"\\newcommand\{\\documentversion\}\{([0-9]+(?:\.[0-9]+)*)\}",
                      source.read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit("documentversion に版番号を指定してください。")
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "latexmk", "-lualatex", "-synctex=1", "-interaction=nonstopmode",
        "-halt-on-error", "-file-line-error", f"-outdir={output}", str(source),
    ], cwd=source.parent, env={**os.environ, "LC_ALL": "C"}, check=True)
    destination = source.with_name(f"{source.stem}_v{match[1]}.pdf")
    shutil.copy2(output / f"{source.stem}.pdf", destination)
    print(f"保存しました: {destination}")


if __name__ == "__main__":
    main()
