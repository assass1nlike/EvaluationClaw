"""Goal text detection for agent benchmark planning."""

from __future__ import annotations

import re


def _goal_mentions_code(goal: str) -> bool:
    text = goal.lower()
    return any(
        keyword in text
        for keyword in (
            "code",
            "repo",
            "repository",
            "debug",
            "repair",
            "test",
            "python",
            "program",
        )
    )


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _mentioned_industrial_apps(full_text: str) -> list[str]:
    app_keywords = (
        ("kicad", "KiCad"),
        ("freecad", "FreeCAD"),
        ("blender", "Blender"),
        ("autocad", "AutoCAD"),
        ("solidworks", "SolidWorks"),
        ("fusion 360", "Fusion 360"),
        ("inventor", "Inventor"),
        ("catia", "CATIA"),
        ("nx", "NX"),
        ("rhino", "Rhino"),
        ("revit", "Revit"),
        ("ltspice", "LTspice"),
        ("ansys", "Ansys"),
        ("moldex3d", "Moldex3D"),
        ("powermill", "PowerMill"),
    )
    found: list[str] = []
    for needle, label in app_keywords:
        if needle in full_text:
            found.append(label)
    return list(dict.fromkeys(found))


def _goal_mentions_multi_industrial_workflow(full_text: str) -> bool:
    base_text = full_text.lower()
    normalized_text = re.sub(r"[-_/]+", " ", base_text)
    search_text = f"{base_text} {normalized_text}"
    multi_markers = (
        "multi software",
        "multi-software",
        "multi industrial",
        "multi industrial software",
        "multiple software",
        "multiple industrial",
        "cross-application",
        "cross application",
        "cross-tool",
        "toolchain",
        "interoperability",
        "handoff",
        "\u591a\u8f6f\u4ef6",
        "\u591a\u4e2a\u8f6f\u4ef6",
        "\u534f\u540c",
        "\u5171\u540c\u53c2\u4e0e",
    )
    industrial_markers = (
        "industrial software",
        "engineering software",
        "cad",
        "eda",
        "cae",
        "cam",
        "pcb",
        "mechanical",
        "manufacturing",
        "enclosure",
        "render",
        "3d model",
        "kicad",
        "freecad",
        "blender",
        "autocad",
        "solidworks",
        "\u5de5\u4e1a\u8f6f\u4ef6",
        "\u5de5\u4e1a",
        "\u5de5\u7a0b",
        "\u673a\u68b0",
        "\u5236\u9020",
        "\u7535\u8def\u677f",
        "\u5e38\u7528\u5de5\u4e1a\u8f6f\u4ef6",
    )
    mentioned_apps = _mentioned_industrial_apps(search_text)
    return len(mentioned_apps) >= 2 or (
        _contains_any(search_text, multi_markers) and _contains_any(search_text, industrial_markers)
    )


def _goal_mentions_osworld_style(full_text: str) -> bool:
    normalized_text = re.sub(r"[-_/]+", " ", full_text)
    search_text = f"{full_text} {normalized_text}"
    explicit_markers = (
        "osworld",
        "os world",
        "computer-control",
        "computer control",
        "general computer",
        "desktop gui applications",
        "desktop application benchmark",
        "desktop software benchmark",
        "desktop software operation",
        "everyday desktop software",
        "local desktop applications",
        "desktop applications",
        "gui applications",
        "desktop app",
        "desktop apps",
        "real desktop gui",
    )
    app_markers = (
        "spreadsheet",
        "document",
        "browser",
        "image editor",
        "photo editor",
        "media player",
        "email client",
        "ide",
        "vs code",
        "vscode",
        "libreoffice",
        "gimp",
        "vlc",
        "thunderbird",
    )
    broad_desktop_benchmark = (
        _goal_mentions_gui_desktop(search_text)
        and _contains_any(
            search_text, ("benchmark", "evaluation", "evaluate", "test whether", "measure whether")
        )
        and _contains_any(
            search_text,
            ("save", "saved", "output file", "artifact", "state change", "hidden check"),
        )
    )
    return (
        _contains_any(search_text, explicit_markers)
        or broad_desktop_benchmark
        or (
            _goal_mentions_gui_desktop(search_text)
            and sum(1 for marker in app_markers if marker in search_text) >= 3
        )
    )


def _goal_mentions_ale_style(full_text: str) -> bool:
    normalized_text = re.sub(r"[-_/]+", " ", full_text)
    search_text = f"{full_text} {normalized_text}"
    ale_markers = (
        "ale-style",
        "ale style",
        "agents last exam",
        "agent's last exam",
        "agents' last exam",
        "economically valuable",
        "professional work",
        "professional workflow",
        "long-horizon professional",
        "hidden reference",
        "hidden references",
        "artifact grader",
        "deterministic grader",
    )
    domain_markers = (
        "engineering",
        "life sciences",
        "bioinformatics",
        "finance",
        "health",
        "visual media",
        "computing",
        "vm",
        "docker",
        "sandbox",
    )
    return _contains_any(search_text, ale_markers) and _contains_any(search_text, domain_markers)


def _goal_mentions_professional_executable_benchmark(full_text: str) -> bool:
    normalized_text = re.sub(r"[-_/]+", " ", full_text)
    search_text = f"{full_text} {normalized_text}"
    professional_markers = (
        "professional",
        "engineering",
        "life science",
        "life sciences",
        "scientific",
        "domain",
        "workflow",
    )
    benchmark_markers = (
        "benchmark",
        "evaluation",
        "evaluate",
        "test whether",
        "measure whether",
        "agent benchmark",
    )
    executable_markers = (
        "isolated environment",
        "private deterministic checks",
        "hidden reference",
        "hidden reference outputs",
        "deterministic checks",
        "structured result",
        "structured output",
        "output contract",
        "validation evidence",
        "provenance",
        "executable artifact",
        "staged data",
        "staged data tables",
        "structured metadata",
        "private checks",
    )
    return (
        _contains_any(search_text, professional_markers)
        and _contains_any(search_text, benchmark_markers)
        and _contains_any(search_text, executable_markers)
    )


def _goal_mentions_professional_life_science_analysis(full_text: str) -> bool:
    normalized_text = re.sub(r"[-_/]+", " ", full_text)
    search_text = f"{full_text} {normalized_text}"
    return _contains_any(
        search_text, ("life science", "life sciences", "biomedical", "biology", "omics")
    ) and _contains_any(
        search_text,
        (
            "data analysis",
            "data tables",
            "metadata",
            "analysis contract",
            "structured result",
            "result tables",
            "hidden reference outputs",
            "private deterministic checks",
        ),
    )


def _goal_mentions_professional_engineering_artifact(full_text: str) -> bool:
    normalized_text = re.sub(r"[-_/]+", " ", full_text)
    search_text = f"{full_text} {normalized_text}"
    return _contains_any(
        search_text, ("engineering", "mechanical", "robot", "robotics", "design asset")
    ) and _contains_any(
        search_text,
        (
            "assets",
            "structured metadata",
            "relationships",
            "constraints",
            "executable artifact",
            "validation evidence",
            "private deterministic checks",
            "isolated environment",
        ),
    )


def _mentions_app_state_workflow(text: str) -> bool:
    return (
        _contains_any(
            text,
            (
                "browser",
                "email",
                "mail",
                "thunderbird",
                "vscode",
                "vs code",
                "extension",
                "state management",
            ),
        )
        or re.search(r"\bide\b", text) is not None
    )


def _goal_mentions_gui_desktop(full_text: str) -> bool:
    gui_keywords = (
        "gui",
        "desktop",
        "cua",
        "computer use",
        "mouse",
        "keyboard",
        "cursor",
        "screenshot",
        "click",
        "drag",
        "scroll",
        "window",
        "ui interaction",
        "graphical interface",
        "remote desktop",
        "vnc",
        "rdp",
        "\u56fe\u5f62\u754c\u9762",
        "\u684c\u9762",
        "\u8f6f\u4ef6\u64cd\u4f5c",
    )
    return _contains_any(full_text, gui_keywords)


def _goal_mentions_browser_gui(full_text: str) -> bool:
    browser_keywords = (
        "browser gui",
        "browser automation",
        "browser ui",
        "web app",
        "website ui",
        "browser-based",
        "browser based",
        "page interaction",
        "click through",
    )
    return _contains_any(full_text, browser_keywords) or (
        "browser" in full_text
        and any(
            keyword in full_text
            for keyword in ("click", "scroll", "screenshot", "form", "page", "ui")
        )
    )


def _goal_mentions_desktop_software(full_text: str) -> bool:
    software_keywords = (
        "blender",
        "freecad",
        "kicad",
        "autocad",
        "solidworks",
        "fusion 360",
        "inventor",
        "catia",
        "ansys",
        "3d modeling",
        "3d model",
        "3d scene",
        "render",
        "mesh",
        "material",
        "animation",
        "cad",
        "bim",
        "cae",
        "cam",
        "rhino",
        "moldex3d",
        "powermill",
        "ltspice",
        "unreal",
        "davinci",
        "after effects",
        "video compositing",
        "chroma key",
        "spreadsheet",
        "excel",
        "word processor",
        "document editor",
        "presentation",
        "slides",
        "pdf viewer",
        "file manager",
        "photo editor",
        "image editor",
        "desktop software",
        "desktop app",
        "native app",
        "application window",
        "industrial software",
        "engineering software",
        "\u5de5\u4e1a\u8f6f\u4ef6",
        "\u5de5\u7a0b\u8f6f\u4ef6",
        "\u5efa\u6a21\u8f6f\u4ef6",
        "\u7535\u8def\u677f",
        "\u673a\u68b0\u8bbe\u8ba1",
    )
    return _contains_any(full_text, software_keywords)


def _goal_mentions_blender(full_text: str) -> bool:
    blender_keywords = (
        "blender",
        "3d modeling",
        "3d model",
        "3d scene",
        "mesh",
        "material",
        "rendered image",
        "render image",
        "cycles render",
        "eevee",
    )
    return _contains_any(full_text, blender_keywords)


def _goal_mentions_runtime_pipeline(full_text: str) -> bool:
    runtime_keywords = (
        "scientific computing",
        "simulation",
        "numerical",
        "pipeline",
        "dataset",
        "notebook",
        "zarr",
        "netcdf",
        "climate",
        "genomics",
        "variant calling",
        "bioinformatics",
        "clinical",
        "cell tracking",
        "financial statement",
        "sec filing",
        "10-k",
        "kubernetes",
        "k8s",
        "sre",
        "root cause",
        "incident",
        "pcap",
        "wireshark",
        "ghidra",
        "malware",
        "cloud cost",
        "environment repair",
        "runtime repair",
        "runtime environment",
        "service repair",
        "service environment",
        "service startup",
        "service health",
        "startup configuration",
        "offline dependency",
        "offline dependencies",
        "runtime dependency",
        "runtime dependencies",
        "dependency management",
        "healthcheck",
        "health check",
        "nginx",
        "chemistry",
        "materials",
        "phonon",
        "vqe",
    )
    return _contains_any(full_text, runtime_keywords)
