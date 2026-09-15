from __future__ import annotations

import io
import json
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from evalclaw.construction import research as builder
from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall
from evalclaw.research import documents
from evalclaw.types import BenchmarkConfig, ResearchBrief, ResearchSourceMaterial


def _call(root, name, *, config=None, budget=1000, **args):
    return builder._execute_task_builder_tool(
        ToolCall(id="resource", name=name, arguments=args), config or BenchmarkConfig(),
        work_dir=root, max_chars=budget,
    )


def _pages(root, name, **args):
    offset = 0
    contents = []
    while True:
        result = _call(root, name, offset=offset, **args)
        assert result.error is None, result.content
        assert len(result.content) <= 1000
        page = json.loads(result.content)
        contents.append(page["content"])
        if page["next_offset"] is None:
            return "".join(contents)
        assert page["next_offset"] > offset
        offset = page["next_offset"]


@pytest.mark.parametrize("source", ["local", "planner", "web"])
def test_long_escaped_text_is_fully_reachable(tmp_path, monkeypatch, source):
    content = '\\"\n模型 café ' * 1000 + "last page"
    if source == "local":
        (tmp_path / "long.txt").write_text(content, encoding="utf-8-sig")
        actual = _pages(tmp_path, "read_document", path="long.txt")
    elif source == "planner":
        config = BenchmarkConfig(research_brief=ResearchBrief(source_materials=[
            ResearchSourceMaterial(title="Source", url="https://example.com", content=content),
        ]))
        actual = _pages(tmp_path, "read_research_source", url="https://example.com", config=config)
    else:
        monkeypatch.setattr(builder, "fetch_url_text", lambda url, max_chars: content[:max_chars])
        actual = _pages(tmp_path, "fetch_url", url="https://example.com")
    assert actual == content


@pytest.mark.parametrize("kind", ["zip", "tar.gz"])
def test_archive_listing_reading_extraction_and_docker_context(tmp_path, kind):
    path = tmp_path / f"source.{kind}"
    data = {"pkg/readme.txt": "说明文件".encode(), "pkg/run.sh": b"#!/bin/sh\nexit 0\n", "data.bin": b"\x00\xff\x01"}
    if kind == "zip":
        with zipfile.ZipFile(path, "w") as archive:
            for name, value in data.items():
                info = zipfile.ZipInfo(name)
                info.external_attr = (stat.S_IFREG | 0o755) << 16
                archive.writestr(info, value)
    else:
        with tarfile.open(path, "w:gz") as archive:
            for name, value in data.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(value), 0o755
                archive.addfile(info, io.BytesIO(value))
    names, offset = [], 0
    while True:
        result = _call(tmp_path, "list_archive", path=str(path), offset=offset, limit=1)
        assert result.error is None
        listing = json.loads(result.content)
        names.extend(member["name"] for member in listing["members"])
        offset = listing["next_offset"]
        if offset is None:
            break
    assert names == list(data)
    assert _pages(tmp_path, "read_document", path=str(path), member=names[0]) == "说明文件"
    result = _call(tmp_path, "extract_archive", path=str(path), members=["pkg/run.sh", "data.bin"])
    assert result.error is None, result.content
    extracted = json.loads(result.content)
    directory = Path(extracted["directory"])
    assert not (directory / "pkg/readme.txt").exists()
    assert (directory / "data.bin").read_bytes() == data["data.bin"]
    assert (directory / "pkg/run.sh").stat().st_mode & stat.S_IXUSR
    manifest = json.loads(Path(extracted["manifest_path"]).read_text())
    (tmp_path / "Dockerfile").write_text("FROM scratch\nCOPY . /app\n")
    context, _ = builder._prepare_image_context(
        tmp_path, build_number=1, dockerfile_path="Dockerfile",
        context_files=[{"source_path": file["path"], "target_path": file["member"]} for file in manifest["files"]],
    )
    assert (context / "pkg/run.sh").read_bytes() == data["pkg/run.sh"]
    assert (context / "pkg/run.sh").stat().st_mode & stat.S_IXUSR
    assert (context / "data.bin").read_bytes() == data["data.bin"]


@pytest.mark.parametrize("names", [["../escape"], ["/absolute"], ["C:/file"], ["."], ["a", "a/b"], ["a", "a"], ["a", "./a"]])
def test_unsafe_archive_paths_never_extract(tmp_path, names):
    path = tmp_path / "unsafe.tar"
    with tarfile.open(path, "w") as archive:
        for name in names:
            info = tarfile.TarInfo(name)
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))
    result = _call(tmp_path, "extract_archive", path=str(path))
    assert result.error is not None
    assert not (tmp_path / "resources").exists()


@pytest.mark.parametrize("kind", ["zip_symlink", "tar_symlink", "tar_hardlink"])
def test_archive_links_are_not_read_or_extracted(tmp_path, kind):
    path = tmp_path / "links.archive"
    if kind == "zip_symlink":
        with zipfile.ZipFile(path, "w") as archive:
            info = zipfile.ZipInfo("link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/etc/passwd")
    else:
        with tarfile.open(path, "w") as archive:
            info = tarfile.TarInfo("link")
            info.type = tarfile.SYMTYPE if kind == "tar_symlink" else tarfile.LNKTYPE
            info.linkname = "/etc/passwd"
            archive.addfile(info)
    for name, args in [("extract_archive", {}), ("read_document", {"member": "link"})]:
        assert _call(tmp_path, name, path=str(path), **args).error is not None


def test_extraction_limits_and_complete_manifest(tmp_path, monkeypatch):
    path = tmp_path / "files.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for i in range(65):
            archive.writestr(f"{i}.txt", "contents")
    assert _call(tmp_path, "extract_archive", path=str(path)).error is not None
    result = _call(tmp_path, "extract_archive", path=str(path), members=[f"{i}.txt" for i in range(64)])
    assert result.error is None
    assert len(result.content) <= 1000
    payload = json.loads(result.content)
    assert payload["file_count"] == 64
    manifest = json.loads(_pages(tmp_path, "read_document", path=payload["manifest_path"]))
    assert len(manifest["files"]) == 64
    assert all(Path(file["path"]).read_text() == "contents" for file in manifest["files"])
    monkeypatch.setattr(documents, "MAX_RESOURCE_BYTES", 7)
    assert _call(tmp_path, "extract_archive", path=str(path), members=["0.txt"]).error is not None


def test_local_paths_cannot_escape_builder_directory(tmp_path):
    work = tmp_path / "builder"
    work.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("outside")
    (work / "link.txt").symlink_to(external)
    for path in [str(external), "../external.txt", "link.txt"]:
        assert _call(work, "read_document", path=path).error is not None


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="pdftotext not installed")
def test_pdf_inside_archive_is_readable_and_cached(tmp_path, monkeypatch):
    line = "Readable original document. " * 4
    stream = b"BT /F1 8 Tf 10 29000 Td 15 TL\n"
    stream += (f"({line}) Tj T*\n".encode() * 1200) + b"ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1000 30000] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
    ]
    pdf, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 6\n0000000000 65535 f \n"
    pdf += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    pdf += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    path = tmp_path / "papers.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("paper.pdf", pdf)
    result = _call(tmp_path, "read_document", path=str(path), member="paper.pdf")
    assert result.error is None, result.content
    assert "Readable original document." in json.loads(result.content)["content"]
    def unexpected_conversion(*args):
        pytest.fail("PDF should be converted once across pages")
    monkeypatch.setattr(documents, "pdf_to_text", unexpected_conversion)
    extracted = _pages(tmp_path, "read_document", path=str(path), member="paper.pdf")
    assert len(extracted) > 100_000
    assert " ".join(extracted.split()) == " ".join((line * 1200).split())


def test_local_document_tools_are_available_without_web_tools(tmp_path, monkeypatch):
    captured = []
    def respond(messages, **kwargs):
        captured.extend(tool.name for tool in kwargs["tools"])
        return TargetToolModelResponse(adapter="openai", content='{"tasks": []}', tool_calls=[],
                                       assistant_message={"role": "assistant", "content": '{"tasks": []}'}, raw_response={})
    monkeypatch.setattr(builder, "call_orchestrator_with_tools", respond)
    builder.run_task_builder_tools({}, system_prompt="Build", include_source_tools=False,
                                   config=BenchmarkConfig(task_builder_model="test", task_builder_api_key="test", output_dir=str(tmp_path)))
    assert {"read_document", "list_archive", "extract_archive"} <= set(captured)
    assert not {"search_web", "fetch_url", "download_files"} & set(captured)
