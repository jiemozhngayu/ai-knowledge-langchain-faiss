"""把仓库自带的虚构示例复制到本机资料目录，不覆盖已有文件。"""
from pathlib import Path
import argparse

PROJECT_DIR = Path(__file__).resolve().parent.parent

def prepare_demo() -> tuple[int, int]:
    source_dir = PROJECT_DIR / "examples" / "knowledge"
    destination_dir = PROJECT_DIR / "documents"
    copied = skipped = 0
    for source in sorted(source_dir.rglob("*.txt")):
        target = destination_dir / source.relative_to(source_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as file:
                file.write(source.read_bytes())
            copied += 1
        except FileExistsError:
            skipped += 1
    return copied, skipped

def main() -> None:
    parser = argparse.ArgumentParser(description="准备虚构知识库示例，保留已有资料")
    parser.parse_args()
    copied, skipped = prepare_demo()
    print(f"虚构示例已准备：新建 {copied} 份，跳过已有文件 {skipped} 份。")

if __name__ == "__main__":
    main()
