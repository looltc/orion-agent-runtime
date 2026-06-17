from pathlib import Path

# 知识加载器，负责从本地文件系统加载知识文档。

DOC_DIR = Path(__file__).resolve().parent / "documents"


def load_documents():

    docs = []

    for file in DOC_DIR.glob("*.txt"):

        docs.append({
            "name": file.name,
            "content": file.read_text(
                encoding="utf-8"
            )
        })

    return docs