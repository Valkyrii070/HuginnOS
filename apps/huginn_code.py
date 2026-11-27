"""Code: Huginn's code editor. A folder is the project: its files down the left, open files as tabs, a terminal
underneath, Git built in, search across the project, and language servers (the same ones VS Code uses) for
completions, live problems and go-to-definition.

Opening a file when Code is already running hands it to the open window (one Code at a time)."""
import itertools
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import subprocess
import threading
import time
from pathlib import Path

from PySide6.QtCore import (Property, QFileSystemWatcher, QKeyCombination, QObject, QProcess, QStandardPaths, Qt, QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import QColor, QFont, QImage, QKeySequence, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtQuick import QQuickImageProvider

import huginn_build as hb
import huginn_code_more as more
import huginn_container as hc
import huginn_debug as hd
import huginn_emmet as emmet
import huginn_extensions as hx
import huginn_notebook as nbk
import huginn_remote as hr
import huginn_vscode as vsc

STATE = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "code.json"
TEXT_LIMIT = 8 * 1024 * 1024
HEAVY = {".git", "node_modules", "__pycache__", ".venv", "venv", "target", "build", "dist", ".mypy_cache", ".pytest_cache", ".tox", ".cache", ".idea", ".gradle",
         # what game engines make and keep: Godot's imports, Unreal's builds and caches
         ".godot", ".import", "build-release", "Intermediate", "Binaries", "DerivedDataCache", "Saved", "Packaged"}
LIST_LIMIT = 30000

# name: (suffixes or file names, line comment, block comment, key words, LSP language id, servers to try)
LANGS = {
    "Python": ((".py", ".pyw", ".pyi"), "#", None, "and as assert async await break class continue def del elif else except finally for from global if import in is lambda match case nonlocal not or pass raise return try while with yield None True False self cls",
               "python", [["pylsp"], ["pyright-langserver", "--stdio"], ["jedi-language-server"]]),
    "C": ((".c", ".h"), "//", ("/*", "*/"), "auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while bool true false NULL",
          "c", [["clangd"]]),
    "C++": ((".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".inl", ".ipp", ".tpp"), "//", ("/*", "*/"), "alignas auto bool break case catch char class const constexpr continue default delete do double else enum explicit export extern false float for friend if inline int long mutable namespace new noexcept nullptr operator override private protected public return short signed sizeof static struct switch template this throw true try typedef typename union unsigned using virtual void volatile while co_await co_return",
            "cpp", [["clangd"]]),
    "Rust": ((".rs",), "//", ("/*", "*/"), "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while",
             "rust", [["rust-analyzer"]]),
    "Go": ((".go",), "//", ("/*", "*/"), "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var true false nil",
           "go", [["gopls"]]),
    "JavaScript": ((".js", ".mjs", ".cjs", ".jsx"), "//", ("/*", "*/"), "async await break case catch class const continue debugger default delete do else export extends finally for function if import in instanceof let new of return static super switch this throw try typeof var void while yield true false null undefined",
                   "javascript", [["typescript-language-server", "--stdio"]]),
    "TypeScript": ((".ts", ".tsx", ".mts"), "//", ("/*", "*/"), "abstract as async await break case catch class const continue declare default delete do else enum export extends finally for from function if implements import in instanceof interface let namespace new of private protected public readonly return static super switch this throw try type typeof var void while yield true false null undefined",
                   "typescript", [["typescript-language-server", "--stdio"]]),
    "QML": ((".qml",), "//", ("/*", "*/"), "import property signal readonly required alias function var let const if else for while return true false null undefined id component default",
            "qml", [["qmlls"], ["qmlls6"]]),
    "Java": ((".java",), "//", ("/*", "*/"), "abstract boolean break byte case catch char class const continue default do double else enum extends final finally float for if implements import instanceof int interface long new package private protected public return short static super switch this throw throws try void volatile while true false null var record",
             "java", [["jdtls"]]),
    "C#": ((".cs",), "//", ("/*", "*/"), "abstract as base bool break case catch class const continue decimal default do double else enum event false finally float for foreach if in int interface internal is namespace new null object out override private protected public readonly ref return sealed static string struct switch this throw true try using var virtual void while async await",
           "csharp", [["omnisharp", "-lsp"]]),
    "Shell": ((".sh", ".bash", ".zsh", ".bashrc", ".profile", ".zshrc"), "#", None, "if then else elif fi for while until do done case esac in function return exit export local readonly set unset echo cd source shift",
              "shellscript", [["bash-language-server", "start"]]),
    "JSON": ((".json", ".jsonc", ".hsheet", ".hslides", ".code-workspace", ".uproject", ".uplugin", ".ipynb"), "", None, "true false null", "json", [["vscode-json-languageserver", "--stdio"]]),
    "YAML": ((".yml", ".yaml"), "#", None, "true false null yes no on off", "yaml", [["yaml-language-server", "--stdio"]]),
    "TOML": ((".toml",), "#", None, "true false", "toml", [["taplo", "lsp", "stdio"]]),
    "Settings": ((".conf", ".ini", ".cfg", ".desktop", ".service", ".list", ".env", ".properties", ".gitignore", ".gitattributes", ".editorconfig"), "#", None, "true false yes no on off", "ini", []),
    "Markdown": ((".md", ".markdown"), "", None, "", "markdown", []),
    "HTML": ((".html", ".htm", ".xml", ".svg", ".ui", ".xhtml"), "", ("<!--", "-->"), "", "html", [["vscode-html-language-server", "--stdio"]]),
    "CSS": ((".css", ".scss", ".less"), "", ("/*", "*/"), "important", "css", [["vscode-css-language-server", "--stdio"]]),
    "SQL": ((".sql",), "--", ("/*", "*/"), "select from where insert into values update set delete create table drop alter join left right inner outer on group by order having limit as and or not null primary key", "sql", []),
    # Game engines. GDScript's helper is the Godot editor itself (it answers on a port while the project is open in it:
    # huginn_lsp_tcp.py carries the conversation there); Unreal's C++ goes to clangd like any other.
    "GDScript": ((".gd",), "#", None, "and as assert await break breakpoint class class_name const continue elif else enum extends for func if in is match not or pass preload load return self "
                 "signal static super var void when while yield true false null PI TAU INF NAN export onready tool master puppet remote",
                 "gdscript", [["python3", str(Path(__file__).resolve().with_name("huginn_lsp_tcp.py")), "127.0.0.1", "6005"]]),
    "Godot Resource": ((".tscn", ".tres", ".godot", ".import", ".gdextension", ".escn", ".remap"), ";", None, "true false null", "godot-resource", []),
    "Godot Shader": ((".gdshader", ".gdshaderinc"), "//", ("/*", "*/"), "shader_type render_mode uniform varying const in out inout struct void return if else for while do switch case default break continue discard "
                     "instance global group_uniforms lowp mediump highp flat smooth true false source_color hint_range hint_normal hint_default_white hint_default_black hint_screen_texture "
                     "hint_depth_texture filter_nearest filter_linear repeat_enable repeat_disable spatial canvas_item particles sky fog", "gdshader", []),
    "GLSL": ((".glsl", ".vert", ".frag", ".geom", ".comp", ".tesc", ".tese", ".vsh", ".fsh", ".rgen", ".rchit", ".rmiss"), "//", ("/*", "*/"),
             "attribute const uniform varying buffer shared coherent volatile restrict readonly writeonly layout centroid flat smooth noperspective patch sample break continue do for while "
             "switch case default if else subroutine in out inout true false invariant precise discard return struct precision lowp mediump highp void", "glsl", [["glsl_analyzer"], ["glslls", "--stdin"]]),
    "HLSL": ((".hlsl", ".hlsli", ".fx", ".fxh", ".usf", ".ush", ".cginc", ".compute", ".shader"), "//", ("/*", "*/"),
             "break case cbuffer tbuffer class const continue default discard do else export extern false for if in inline inout interface namespace nointerpolation noperspective out packoffset "
             "precise register return row_major column_major sample shared static struct switch technique pass true typedef uniform volatile while linear centroid groupshared void", "hlsl", []),
    "Lua": ((".lua",), "--", ("--[[", "]]"), "and break do else elseif end false for function if in local nil not or repeat return then true until while", "lua", [["lua-language-server"]]),
    "Make": (("Makefile", "makefile", "GNUmakefile", ".mk"), "#", None, "ifeq ifneq ifdef ifndef else endif include define endef export", "makefile", []),
    "CMake": (("CMakeLists.txt", ".cmake"), "#", None, "if else elseif endif foreach endforeach function endfunction macro endmacro set project add_executable add_library target_link_libraries find_package include", "cmake", []),
    "Docker": (("Dockerfile", "Containerfile"), "#", None, "FROM RUN CMD LABEL EXPOSE ENV ADD COPY ENTRYPOINT VOLUME USER WORKDIR ARG ONBUILD STOPSIGNAL HEALTHCHECK SHELL AS", "dockerfile", []),
    "Diff": ((".diff", ".patch"), "", None, "", "diff", []),
    "Text": ((".txt", ".text", ".log", ".csv", ".tsv", ".rst", ".tex", ".srt"), "", None, "", "plaintext", []),
}
_VEC = [f"{p}{k}{n}" for p in ("", "i", "u", "b", "d") for k in ("vec",) for n in "234"]
TYPES = {
    "GLSL": set("float double int uint bool mat2 mat3 mat4 mat2x3 mat2x4 mat3x2 mat3x4 mat4x2 mat4x3 sampler1D sampler2D sampler3D samplerCube sampler2DArray sampler2DShadow samplerCubeShadow "
                "isampler2D usampler2D image2D atomic_uint".split() + _VEC),
    "Godot Shader": set("float int uint bool mat2 mat3 mat4 sampler2D isampler2D usampler2D sampler2DArray sampler3D samplerCube samplerCubeArray".split() + _VEC),
    "HLSL": set("bool int uint dword half float double min16float min10float min16int min12int min16uint string vector matrix Texture1D Texture2D Texture3D TextureCube Texture2DArray "
                "SamplerState SamplerComparisonState sampler sampler2D samplerCUBE RWTexture2D Buffer RWBuffer StructuredBuffer RWStructuredBuffer ByteAddressBuffer".split()
                + [f"{t}{n}" for t in ("float", "int", "uint", "bool", "half", "double") for n in ("2", "3", "4", "2x2", "3x3", "4x4", "3x4", "4x3")]),
    "GDScript": set("bool int float".split()),
    "C": set("size_t ssize_t int8_t int16_t int32_t int64_t uint8_t uint16_t uint32_t uint64_t intptr_t uintptr_t ptrdiff_t wchar_t".split()),
    "C++": set("size_t ssize_t int8_t int16_t int32_t int64_t uint8_t uint16_t uint32_t uint64_t intptr_t uintptr_t ptrdiff_t wchar_t char8_t char16_t char32_t "
               "int8 int16 int32 int64 uint8 uint16 uint32 uint64".split()),                # (the last eight are Unreal's)
}
HASH_LINES = ("C", "C++", "GLSL", "HLSL", "Godot Shader", "C#")          # a line starting with # is the preprocessor's
SERVER_SETTINGS = {"pylsp": {"plugins": {"pycodestyle": {"enabled": False}, "mccabe": {"enabled": False}, "pyflakes": {"enabled": True}}}}
SHEBANG = {"python": "Python", "bash": "Shell", "sh": "Shell", "zsh": "Shell", "node": "JavaScript", "godot": "GDScript"}
RUNNERS = {"Python": 'python3 "{f}"', "Shell": 'bash "{f}"', "JavaScript": 'node "{f}"', "TypeScript": 'npx tsx "{f}"', "Go": 'go run "{f}"',
           "C": 'cc "{f}" -o /tmp/huginn-run && /tmp/huginn-run', "C++": 'c++ "{f}" -o /tmp/huginn-run && /tmp/huginn-run', "Lua": 'lua "{f}"', "GLSL": 'glslangValidator "{f}"', "Rust": 'rustc "{f}" -o /tmp/huginn-run && /tmp/huginn-run'}


# Adding a language: what it takes, from Ubuntu's archive (apt, through the system's password prompt) and, for the
# helpers Ubuntu doesn't package, from npm into the user's own folder (no password). "tools" are what Run and the
# terminal use (a compiler, an interpreter); a language is ready when its helper (language server) is there.
UNSAVED = STATE.with_name("code-unsaved")                 # work you hadn't saved, kept through a quit or a crash: one file per document
STASH_LIMIT = 4 * 1024 * 1024
TOOLS_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "huginn" / "code-tools"
EXTRA_BIN = [str(TOOLS_HOME / "bin"), "/usr/lib/qt6/bin", "/usr/lib/go/bin"]
LANG_PACKS = {
    "Python": {"apt": ["python3-pylsp", "python3-pyflakes", "python3-autopep8"], "tools": ["python3"]},
    "C": {"apt": ["clangd", "build-essential", "gdb"], "tools": ["cc"]},
    "C++": {"apt": ["clangd", "build-essential", "gdb"], "tools": ["c++"]},
    "Rust": {"apt": ["rustc", "cargo", "rust-src", "gdb"], "tools": ["cargo"]},
    "Go": {"apt": ["golang-go", "gopls"], "tools": ["go"]},
    "JavaScript": {"apt": ["nodejs", "npm"], "npm": ["typescript", "typescript-language-server"], "tools": ["node"]},
    "TypeScript": {"apt": ["nodejs", "npm"], "npm": ["typescript", "typescript-language-server", "tsx"], "tools": ["node"]},
    "Java": {"apt": ["default-jdk"], "tools": ["javac"]},
    "Shell": {"apt": ["shellcheck", "nodejs", "npm"], "npm": ["bash-language-server"], "tools": ["bash"]},
    "HTML": {"apt": ["nodejs", "npm"], "npm": ["vscode-langservers-extracted"], "tools": []},
    "CSS": {"apt": ["nodejs", "npm"], "npm": ["vscode-langservers-extracted"], "tools": []},
    "JSON": {"apt": ["nodejs", "npm"], "npm": ["vscode-langservers-extracted"], "tools": []},
    "YAML": {"apt": ["nodejs", "npm"], "npm": ["yaml-language-server"], "tools": []},
    "QML": {"apt": ["qt6-declarative-dev-tools", "qt6-qmlls-plugins"], "tools": ["qml"]},
    "Lua": {"apt": ["lua5.4"], "tools": ["lua5.4"]},
    "SQL": {"apt": ["sqlite3"], "tools": ["sqlite3"]},
    "CMake": {"apt": ["cmake", "ninja-build", "build-essential"], "tools": ["cmake"]},
    "C#": {"apt": ["dotnet-sdk-10.0"], "tools": ["dotnet"]},
    "GDScript": {"flatpak": ["org.godotengine.Godot"], "tools": []},       # (its helper and its runner are the Godot editor)
    "GLSL": {"apt": ["glslang-tools"], "tools": ["glslangValidator"]},
}
# What a new file in each language starts with (the cursor goes where the first line of real work goes).
TEMPLATES = {
    "Python": 'def main():\n    print("Hello")\n\n\nif __name__ == "__main__":\n    main()\n',
    "C": '#include <stdio.h>\n\nint main(void)\n{\n    printf("Hello\\n");\n    return 0;\n}\n',
    "C++": '#include <iostream>\n\nint main()\n{\n    std::cout << "Hello" << std::endl;\n    return 0;\n}\n',
    "Rust": 'fn main() {\n    println!("Hello");\n}\n',
    "Go": 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hello")\n}\n',
    "JavaScript": 'console.log("Hello");\n', "TypeScript": 'const greeting: string = "Hello";\nconsole.log(greeting);\n',
    "Java": 'public class Main {\n    public static void main(String[] args) {\n        System.out.println("Hello");\n    }\n}\n',
    "Shell": '#!/usr/bin/env bash\nset -euo pipefail\n\necho "Hello"\n',
    "HTML": '<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n  <title>Hello</title>\n</head>\n<body>\n  <h1>Hello</h1>\n</body>\n</html>\n',
    "CSS": 'body {\n  font-family: system-ui, sans-serif;\n  margin: 2rem;\n}\n', "JSON": '{\n  \n}\n',
    "QML": 'import QtQuick\n\nRectangle {\n    width: 400; height: 300\n    Text { anchors.centerIn: parent; text: "Hello" }\n}\n',
    "GDScript": 'extends Node\n\n\nfunc _ready() -> void:\n\tprint("Hello")\n',
    "Godot Shader": "shader_type canvas_item;\n\nvoid fragment() {\n\tCOLOR = texture(TEXTURE, UV);\n}\n",
    "GLSL": "#version 450\n\nlayout(location = 0) in vec2 uv;\nlayout(location = 0) out vec4 colour;\n\nvoid main() {\n    colour = vec4(uv, 0.0, 1.0);\n}\n",
    "HLSL": "float4 PS(float2 uv : TEXCOORD0) : SV_Target\n{\n    return float4(uv, 0, 1);\n}\n",
    "Lua": 'print("Hello")\n', "SQL": "SELECT 'Hello';\n", "Markdown": "# Title\n\n", "YAML": "", "TOML": "", "Text": "",
}
# the first-named file for languages whose files are known by name, not by an ending
NEW_NAMES = {"Make": "Makefile", "CMake": "CMakeLists.txt", "Docker": "Dockerfile", "Java": "Main.java"}


def which(program: str):
    """A program on the PATH, or in Code's own tools folder and the places Ubuntu puts some helpers (qmlls, gopls)."""
    return shutil.which(program) or shutil.which(program, path=os.pathsep.join(EXTRA_BIN))


ASSOCIATIONS = []          # [(glob, language)] from the open project's files.associations (.vscode/settings.json)


def language_of(path: str, head: str = "") -> str:
    return (vsc.associated(path, ASSOCIATIONS) if ASSOCIATIONS else "") or _language_of(path, head)


def _language_of(path: str, head: str = "") -> str:
    name = Path(path).name
    suffix = Path(path).suffix.lower()
    for lang, (ends, *_rest) in LANGS.items():
        if name in ends or (suffix and suffix in ends) or (name.startswith(".") and name in ends):
            return "C++" if lang == "C" and suffix == ".h" and cpp_header(path, head) else lang
    if head.startswith("#!"):
        first = head.split("\n", 1)[0]
        for word, lang in SHEBANG.items():
            if re.search(rf"\b{word}[0-9.]*\b", first):
                return lang
    return "Text"


CPP_MARKS = re.compile(r"^\s*(class|namespace|template)\b|\b(UCLASS|USTRUCT|UENUM|UINTERFACE|GENERATED_BODY|constexpr|nullptr|public:|private:|protected:)|#include\s*<[a-z_]+>|std::|::", re.M)


def cpp_header(path: str, head: str = "") -> bool:
    """A .h file is C until it shows otherwise: C++ words in what's read of it, or a .cpp of the same name beside it
    (or in the Private/ folder Unreal keeps its sources in)."""
    if head and CPP_MARKS.search(head):
        return True
    p = Path(path)
    try:
        beside = [p.parent, p.parent.parent / "Private", p.parent.parent / "src", p.parent.parent / "Source"]
        return any((d / (p.stem + ext)).is_file() for d in beside for ext in (".cpp", ".cc", ".cxx"))
    except OSError:
        return False


def fuzzy(query: str, text: str) -> int:
    """A score for `query` as a subsequence of `text` (higher is better), or -1 when it isn't one."""
    q, t = query.lower(), text.lower()
    if not q:
        return 0
    base = t.rsplit("/", 1)[-1]
    score, at, last = 0, 0, -2
    for ch in q:
        found = t.find(ch, at)
        if found < 0:
            return -1
        score += 6 if found == last + 1 else 1
        if found == 0 or t[found - 1] in "/_-. ":
            score += 4
        last, at = found, found + 1
    if q in base:
        score += 25 + (15 if base.startswith(q) else 0)
    return score - len(t) // 12


# ============================================================================================ colouring
class CodeStyler(QSyntaxHighlighter):
    """Comments (line and block), strings (including Python's triple quotes), numbers, key words, types, function
    names, decorators and preprocessor lines, carried across lines with the block state."""
    WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    NUMBER = re.compile(r"0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*(\.\d+)?([eE][+-]?\d+)?")

    def __init__(self, document, language: str, colours: dict):
        super().__init__(document)
        _, self.line, self.block, words, *_ = LANGS.get(language, LANGS["Text"])
        self.words = set(words.split())
        self.types = TYPES.get(language, frozenset())
        self.lang = language
        self.fmt = {}
        for name in ("key", "comment", "string", "number", "type", "func", "deco", "head"):
            f = QTextCharFormat()
            f.setForeground(QColor(colours.get(name) or colours.get("key", "#888888")))
            self.fmt[name] = f
        self.fmt["key"].setFontWeight(QFont.Weight.DemiBold)
        self.fmt["head"].setFontWeight(QFont.Weight.Bold)
        self.fmt["comment"].setFontItalic(True)

    def highlightBlock(self, text: str) -> None:
        lang = self.lang
        if lang == "Text":
            return
        if lang == "Markdown":
            if text.startswith("#"):
                self.setFormat(0, len(text), self.fmt["head"])
            elif text.startswith("```"):
                self.setFormat(0, len(text), self.fmt["comment"])
            elif text.lstrip().startswith(("- ", "* ", "> ", "1. ")):
                self.setFormat(0, len(text) - len(text.lstrip()) + 1, self.fmt["key"])
            return
        if lang == "Diff":
            if text.startswith("+"):
                self.setFormat(0, len(text), self.fmt["string"])
            elif text.startswith("-"):
                self.setFormat(0, len(text), self.fmt["deco"])
            elif text.startswith("@@"):
                self.setFormat(0, len(text), self.fmt["type"])
            return
        i, n = 0, len(text)
        self.setCurrentBlockState(0)
        state = self.previousBlockState()
        if state == 1 and self.block:                        # inside a block comment
            end = text.find(self.block[1])
            if end < 0:
                self.setFormat(0, n, self.fmt["comment"])
                self.setCurrentBlockState(1)
                return
            self.setFormat(0, end + len(self.block[1]), self.fmt["comment"])
            i = end + len(self.block[1])
        elif state in (2, 3):                                # inside a Python triple-quoted string
            quote = '"""' if state == 2 else "'''"
            end = text.find(quote)
            if end < 0:
                self.setFormat(0, n, self.fmt["string"])
                self.setCurrentBlockState(state)
                return
            self.setFormat(0, end + 3, self.fmt["string"])
            i = end + 3
        if lang in HASH_LINES and text.lstrip().startswith("#"):
            self.setFormat(0, n, self.fmt["deco"])
            return
        if lang in ("Settings", "Godot Resource"):
            lead = text.lstrip()
            if lang == "Settings" and lead.startswith(";"):            # (Windows-style .ini files, Unreal's among them)
                self.setFormat(0, n, self.fmt["comment"])
                return
            if lead.startswith("[") and (lang == "Settings" or state != 1):
                end = text.find(" ") if lang == "Godot Resource" and " " in text else n
                self.setFormat(0, end, self.fmt["head"])               # [Section], or [node …] with its attributes after
                i = end
        while i < n:
            ch = text[i]
            if self.block and text.startswith(self.block[0], i):
                end = text.find(self.block[1], i + len(self.block[0]))
                if end < 0:
                    self.setFormat(i, n - i, self.fmt["comment"])
                    self.setCurrentBlockState(1)
                    return
                self.setFormat(i, end + len(self.block[1]) - i, self.fmt["comment"])
                i = end + len(self.block[1])
                continue
            if self.line and text.startswith(self.line, i) and (self.line != "#" or lang not in ("C", "C++")):
                if self.line == "#" and lang == "Shell" and i > 0 and text[i - 1] not in " \t;":
                    i += 1
                    continue
                self.setFormat(i, n - i, self.fmt["comment"])
                return
            if lang in ("Python", "GDScript") and text.startswith(('"""', "'''"), i):
                quote = text[i:i + 3]
                end = text.find(quote, i + 3)
                if end < 0:
                    self.setFormat(i, n - i, self.fmt["string"])
                    self.setCurrentBlockState(2 if quote == '"""' else 3)
                    return
                self.setFormat(i, end + 3 - i, self.fmt["string"])
                i = end + 3
                continue
            if ch in "\"'`":
                j = i + 1
                while j < n and text[j] != ch:
                    j += 2 if text[j] == "\\" else 1
                self.setFormat(i, min(j + 1, n) - i, self.fmt["string"])
                i = j + 1
                continue
            if ch in "$%" and lang == "GDScript" and i + 1 < n and (text[i + 1].isalpha() or text[i + 1] in '_"'):
                j = i + 1                                              # $Node/Path and %UniqueName: a node in the scene
                if text[j] == '"':
                    j = text.find('"', j + 1)
                    j = n if j < 0 else j + 1
                else:
                    while j < n and (text[j].isalnum() or text[j] in "_/"):
                        j += 1
                self.setFormat(i, j - i, self.fmt["deco"])
                i = j
                continue
            if ch == "@" and lang in ("Python", "Java", "TypeScript", "C#", "GDScript"):
                m = self.WORD.match(text, i + 1)
                if m:
                    self.setFormat(i, m.end() - i, self.fmt["deco"])
                    i = m.end()
                    continue
            if ch.isdigit() and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
                m = self.NUMBER.match(text, i)
                if m:
                    self.setFormat(i, m.end() - i, self.fmt["number"])
                    i = m.end()
                    continue
            m = self.WORD.match(text, i)
            if m:
                word = m.group()
                if word in self.words:
                    self.setFormat(i, len(word), self.fmt["key"])
                elif word in self.types:
                    self.setFormat(i, len(word), self.fmt["type"])
                elif m.end() < n and text[m.end()] == "(":
                    self.setFormat(i, len(word), self.fmt["func"])
                elif word[0].isupper() and len(word) > 1 and lang not in ("Shell", "SQL", "Docker"):
                    self.setFormat(i, len(word), self.fmt["type"])
                elif lang == "JSON" and m.end() < n and text[m.end():].lstrip().startswith(":"):
                    self.setFormat(i, len(word), self.fmt["type"])
                i = m.end()
                continue
            i += 1


# ============================================================================================ language servers
class LspClient(QObject):
    """One language server for one project: speaks JSON-RPC over the server's standard input and output."""
    diagnostics = Signal(str, list)          # file uri, [{line, col, endLine, endCol, severity, message, source}]
    applyEdit = Signal(dict)                 # a WorkspaceEdit the server wants made (after a command)
    ready = Signal()
    failed = Signal(str)

    def __init__(self, argv: list, root: Path, lang_id: str, parent=None):
        super().__init__(parent)
        self.argv, self.root, self.lang_id = argv, root, lang_id
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(str(root))
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.errorOccurred.connect(lambda e: self.failed.emit(f"{argv[0]} didn't start") if e == QProcess.FailedToStart else None)
        self.proc.finished.connect(lambda *_: self._gone())
        self._buf, self._next, self._waiting, self._queue = b"", 1, {}, []
        self.up, self.caps, self.alive = False, {}, True
        self.proc.start(argv[0], argv[1:])
        self._request("initialize", {
            "processId": os.getpid(), "rootUri": root.as_uri(), "rootPath": str(root), "clientInfo": {"name": "Huginn Code"},
            "workspaceFolders": [{"uri": root.as_uri(), "name": root.name}],
            "capabilities": {"textDocument": {
                "synchronization": {"didSave": True, "dynamicRegistration": False},
                "completion": {"completionItem": {"snippetSupport": True, "documentationFormat": ["plaintext", "markdown"]}, "contextSupport": True},
                "signatureHelp": {"signatureInformation": {"documentationFormat": ["plaintext", "markdown"], "parameterInformation": {"labelOffsetSupport": True},
                                                           "activeParameterSupport": True}},
                "codeAction": {"codeActionLiteralSupport": {"codeActionKind": {"valueSet": ["", "quickfix", "refactor", "source", "source.organizeImports"]}}},
                "hover": {"contentFormat": ["plaintext", "markdown"]}, "definition": {}, "references": {}, "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                "rename": {"prepareSupport": False},
                "publishDiagnostics": {"relatedInformation": False}, "formatting": {}, "inlayHint": {}},
                "workspace": {"workspaceFolders": True, "configuration": True, "workspaceEdit": {"documentChanges": True}, "applyEdit": True, "executeCommand": {}}}},
            self._started, early=True)

    def _gone(self) -> None:
        self.alive, self.up = False, False

    def _started(self, result, error) -> None:
        if error:
            self.failed.emit(str(error.get("message", error)))
            return
        self.caps = (result or {}).get("capabilities", {})
        self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        self._send({"jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": {"settings": SERVER_SETTINGS}})
        self.up = True
        for msg in self._queue:
            self._send(msg)
        self._queue = []
        self.ready.emit()

    def _send(self, msg: dict) -> None:
        body = json.dumps(msg).encode("utf-8")
        self.proc.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)

    def _post(self, msg: dict, early: bool = False) -> None:
        if self.up or early:
            self._send(msg)
        else:
            self._queue.append(msg)

    def _request(self, method: str, params: dict, then=None, early: bool = False) -> int:
        rid = self._next
        self._next += 1
        if then:
            self._waiting[rid] = then
        self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}, early)
        return rid

    def notify(self, method: str, params: dict) -> None:
        self._post({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict, then) -> int:
        return self._request(method, params, then)

    def _read(self) -> None:
        self._buf += bytes(self.proc.readAllStandardOutput())
        while True:
            head_end = self._buf.find(b"\r\n\r\n")
            if head_end < 0:
                return
            m = re.search(rb"Content-Length:\s*(\d+)", self._buf[:head_end], re.I)
            if not m:
                self._buf = self._buf[head_end + 4:]
                continue
            size = int(m.group(1))
            if len(self._buf) < head_end + 4 + size:
                return
            body, self._buf = self._buf[head_end + 4:head_end + 4 + size], self._buf[head_end + 4 + size:]
            try:
                self._handle(json.loads(body))
            except (ValueError, KeyError, TypeError):
                continue

    def _handle(self, msg: dict) -> None:
        if "id" in msg and ("result" in msg or "error" in msg) and "method" not in msg:
            then = self._waiting.pop(msg["id"], None)
            if then:
                then(msg.get("result"), msg.get("error"))
            return
        method = msg.get("method", "")
        if method == "textDocument/publishDiagnostics":
            p = msg.get("params", {})
            out = []
            for d in p.get("diagnostics", []):
                r = d.get("range", {})
                out.append({"line": r.get("start", {}).get("line", 0), "col": r.get("start", {}).get("character", 0),
                            "endLine": r.get("end", {}).get("line", 0), "endCol": r.get("end", {}).get("character", 0),
                            "severity": d.get("severity", 1), "message": d.get("message", ""), "source": d.get("source", "")})
            self.diagnostics.emit(p.get("uri", ""), out)
        elif "id" in msg:                                     # a request from the server: answer politely
            result = None
            if method == "workspace/configuration":
                result = [SERVER_SETTINGS.get((it.get("section") or "").split(".")[0]) for it in msg.get("params", {}).get("items", [])]
            elif method == "workspace/workspaceFolders":
                result = [{"uri": self.root.as_uri(), "name": self.root.name}]
            elif method == "workspace/applyEdit":
                self.applyEdit.emit(msg.get("params", {}).get("edit") or {})
                result = {"applied": True}
            self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    def stop(self) -> None:
        if self.alive and self.proc.state() != QProcess.NotRunning:
            if self.up:
                self._send({"jsonrpc": "2.0", "id": self._next, "method": "shutdown", "params": None})
                self._send({"jsonrpc": "2.0", "method": "exit", "params": None})
                self.proc.waitForFinished(800)
            if self.proc.state() != QProcess.NotRunning:
                self.proc.kill()
                self.proc.waitForFinished(500)


# ============================================================================================ one open file
class Doc:
    def __init__(self, path: str):
        self.path, self.text, self.saved = path, "", ""
        self.encoding, self.bom, self.crlf, self.mtime = "utf-8", False, False, 0.0
        self.read_only, self.why, self.lang, self.version = False, "", "Text", 1
        self.problems, self.marks, self.binary = [], {}, False
        self.wide = b""                                       # a UTF-16 file's byte-order mark
        self.head = None                                      # its text at the last commit (None: not committed, or not asked yet)
        self.stashed = None                                   # the unsaved text last put by in UNSAVED
        self.found = (None, [])                               # what differs from `head`, for the text it was worked out from

    @property
    def dirty(self) -> bool:
        return self.text != self.saved

    @property
    def uri(self) -> str:
        return Path(self.path).as_uri()

    def load(self) -> None:
        p = Path(self.path)
        import stat as _stat
        if not _stat.S_ISREG(p.stat().st_mode):               # a pipe, a device, a socket: reading one can wait for ever, or never end
            self.binary, self.why, self.read_only = True, "This isn't an ordinary file, so Code can't open it.", True
            return
        with open(p, "rb") as f:
            data = f.read(TEXT_LIMIT + 1)                     # (never more than this, whatever the file says its size is)
        if len(data) > TEXT_LIMIT:
            self.binary, self.why, self.read_only = True, "This file is too large to edit here (over 8 MB).", True
            return
        self.wide = data[:2] if data[:2] in (b"\xff\xfe", b"\xfe\xff") and len(data) % 2 == 0 else b""    # UTF-16, as Windows writes it
        if self.wide:
            try:
                text, self.encoding = data[2:].decode("utf-16-le" if self.wide == b"\xff\xfe" else "utf-16-be"), ("utf-16-le" if self.wide == b"\xff\xfe" else "utf-16-be")
            except UnicodeDecodeError:
                self.wide = b""
        if not self.wide and b"\0" in data[:8192]:
            self.binary, self.why, self.read_only = True, "This file isn't text, so Code can't show it.", True
            return
        self.bom = data.startswith(b"\xef\xbb\xbf")
        if not self.wide:
            try:
                text = data[3 if self.bom else 0:].decode("utf-8")
                self.encoding = "utf-8"
            except UnicodeDecodeError:
                text, self.encoding = data.decode("latin-1"), "latin-1"
        pairs = text.count("\r\n")
        self.crlf = pairs > 0 and pairs >= text.count("\n") - pairs     # the file's own line endings: what most of its lines have
        alone = text.count("\r") - pairs                               # a bare carriage return: the editor shows it as a line end too
        self.mixed = (pairs > 0 and pairs != text.count("\n")) or alone > 0   # (some of each: left as they are until something is changed)
        self.text = self.saved = text.replace("\r\n", "\n").replace("\r", "\n") if (pairs or alone) else text
        self.mtime = p.stat().st_mtime
        self.lang = language_of(self.path, text[:200])
        if not os.access(p, os.W_OK):
            self.read_only, self.why = True, "You don't have permission to change this file."

    def save(self, force: bool = False) -> str:
        target = Path(os.path.realpath(self.path))
        if not force and target.exists() and self.mtime and abs(target.stat().st_mtime - self.mtime) > 0.001:
            return "changed"
        if (self.text == self.saved and getattr(self, "mixed", False) and target.exists()
                and self.mtime and abs(target.stat().st_mtime - self.mtime) <= 0.001):
            return ""                                         # nothing was changed: its mixed line endings stay exactly as they were
        self.mixed = False
        text = self.text.replace("\n", "\r\n") if self.crlf else self.text
        try:
            data = (self.wide or (b"\xef\xbb\xbf" if self.bom else b"")) + text.encode(self.encoding)
        except UnicodeEncodeError:
            self.encoding, self.wide = "utf-8", b""
            data = text.encode("utf-8")
        tmp = target.with_name(f".{target.name}.saving")
        try:
            tmp.write_bytes(data)
            if target.exists():
                shutil.copymode(target, tmp)
            os.replace(tmp, target)
        except PermissionError:
            tmp.unlink(missing_ok=True)
            with open(target, "wb") as f:
                f.write(data)
        self.saved, self.mtime = self.text, target.stat().st_mtime
        return ""


def indent_of(text: str) -> str:
    """The file's own indentation: a tab, or 2 or 4 (or 8) spaces."""
    counts = {}
    for line in text.split("\n")[:2000]:
        if line.startswith("\t"):
            counts["\t"] = counts.get("\t", 0) + 1
        else:
            m = re.match(r"^( +)\S", line)
            if m:
                n = len(m.group(1))
                for size in (2, 4, 8):
                    if n % size == 0:
                        counts[size] = counts.get(size, 0) + (1 if size == 4 else 0.9 if size == 2 else 0.5)
    if not counts:
        return "    "
    best = max(counts, key=counts.get)
    return "\t" if best == "\t" else " " * best


def git(root: Path, *args, timeout: int = 20, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", **(env or {})))


def parse_status(out: str) -> tuple:
    """`git status --porcelain=v1 -b -z` -> (branch line, [{path, x, y, kind}])."""
    parts, branch, changes, i = out.split("\0"), "", [], 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if not entry:
            continue
        if entry.startswith("## "):
            branch = entry[3:]
            continue
        x, y, path = entry[0], entry[1], entry[3:]
        if x in "RC":
            i += 1                                            # the old name follows
        kind = "new" if (x, y) == ("?", "?") else "added" if x == "A" else "deleted" if "D" in (x, y) else "renamed" if x == "R" else "conflict" if "U" in (x, y) or (x, y) in (("A", "A"), ("D", "D")) else "changed"
        changes.append({"path": path, "x": x, "y": y, "kind": kind, "staged": x not in " ?", "unstaged": y != " "})
    return branch, changes


def parse_hunks(diff: str) -> dict:
    """`git diff -U0` -> {line (0-based): "add" | "mod" | "del"} for the gutter."""
    marks = {}
    for m in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", diff, re.M):
        old_n = int(m.group(2)) if m.group(2) is not None else 1
        start, new_n = int(m.group(3)), int(m.group(4)) if m.group(4) is not None else 1
        if new_n == 0:
            marks[max(0, start - 1)] = "del"
        else:
            for k in range(new_n):
                marks[start - 1 + k] = "add" if old_n == 0 else "mod"
    return marks


def diff_rows(diff: str) -> list:
    """A unified diff as rows for the window: {text, kind: add/del/hunk/head/same, old, new}."""
    rows, old, new = [], 0, 0
    for line in diff.split("\n"):
        if line.startswith(("diff --git", "index ", "--- ", "+++ ", "new file", "deleted file", "similarity", "rename ")):
            continue
        m = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)", line)
        if m:
            old, new = int(m.group(1)), int(m.group(2))
            rows.append({"text": m.group(3).strip() or "…", "kind": "hunk", "old": "", "new": ""})
        elif line.startswith("+"):
            rows.append({"text": line[1:], "kind": "add", "old": "", "new": str(new)})
            new += 1
        elif line.startswith("-"):
            rows.append({"text": line[1:], "kind": "del", "old": str(old), "new": ""})
            old += 1
        elif line.startswith(" "):
            rows.append({"text": line[1:], "kind": "same", "old": str(old), "new": str(new)})
            old += 1
            new += 1
    return rows


# ------------------------------------------------------------------------------------------- who wrote what, and when
def ago(ts: float, now: float = None) -> str:
    d = max(0, (now or time.time()) - ts)
    for size, unit in ((31536000, "year"), (2592000, "month"), (604800, "week"), (86400, "day"), (3600, "hour"), (60, "minute")):
        if d >= size:
            n = int(d // size)
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def parse_blame(porcelain: str) -> list:
    """`git blame --porcelain` -> one entry a line: {sha, author, time, summary}."""
    commits, lines, cur = {}, [], None
    for raw in porcelain.split("\n"):
        if not raw:
            continue
        if raw.startswith("\t"):
            if cur:
                lines.append(cur)
            continue
        parts = raw.split(" ")
        if len(parts[0]) == 40 and all(c in "0123456789abcdef" for c in parts[0]) and len(parts) >= 3:
            sha = parts[0]
            info = commits.setdefault(sha, {"sha": sha, "author": "", "time": 0, "summary": ""})
            cur = info
        elif cur is not None:
            key, _, val = raw.partition(" ")
            if key == "author":
                cur["author"] = val
            elif key == "author-time":
                cur["time"] = int(val)
            elif key == "summary":
                cur["summary"] = val
    return lines


def lane_graph(commits: list) -> list:
    """Lanes for a commit graph (newest first): each commit gets its lane and the lines to draw to the next row."""
    lanes = []
    out = []
    for c in commits:
        sha, parents = c["sha"], c.get("parents") or []
        if sha in lanes:
            lane = lanes.index(sha)
        else:
            lanes.append(sha)
            lane = len(lanes) - 1
        before = list(lanes)
        lanes[lane] = parents[0] if parents else None
        for p in parents[1:]:
            if p not in lanes:
                lanes.append(p)
        # two lanes waiting for the same commit join
        seen = {}
        for k, x in enumerate(lanes):
            if x is None:
                continue
            if x in seen:
                lanes[k] = None
            else:
                seen[x] = k
        while lanes and lanes[-1] is None:
            lanes.pop()
        down = []                                              # from this row's lanes to the next row's
        for k, x in enumerate(before):
            if x is None:
                continue
            if k == lane:
                for p in parents:
                    if p in lanes:
                        down.append([k, lanes.index(p)])
            elif x in lanes:
                down.append([k, lanes.index(x)])
        out.append(dict(c, lane=lane, width=max(len(before), len(lanes), 1), down=down))
    return out


def parse_log(out: str) -> list:
    commits = []
    for line in out.split("\n"):
        f = line.split("\x1f")
        if len(f) >= 7:
            commits.append({"sha": f[0], "short": f[1], "author": f[2], "time": int(f[3] or 0), "subject": f[4], "parents": f[5].split(), "refs": f[6].strip()})
    return commits


def show_rows(text: str) -> list:
    """`git show` of a commit: a heading row for each file, then its changes."""
    rows = []
    for chunk in re.split(r"^(?=diff --git )", text, flags=re.M):
        m = re.match(r"diff --git a/(.+?) b/(.+)", chunk)
        if not m:
            continue
        rows.append({"text": m.group(2), "kind": "file", "old": "", "new": ""})
        rows += diff_rows(chunk)
    return rows


# ------------------------------------------------------------------------------------------- tests
def test_framework(root: Path) -> str:
    if root is None:
        return ""
    if (root / "Cargo.toml").exists() and shutil.which("cargo"):
        return "cargo"
    if (root / "go.mod").exists() and shutil.which("go"):
        return "go"
    py_tests = any(root.glob("test_*.py")) or any(root.glob("tests/**/test_*.py")) or any(root.glob("**/*_test.py"))
    if py_tests or (root / "pytest.ini").exists() or "[tool.pytest" in _read(root / "pyproject.toml"):
        return "pytest"
    return ""


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def test_line(root: Path, file: str, name: str) -> int:
    base = name.split("[")[0].split("::")[-1]
    text = _read(root / file)
    m = re.search(rf"^[ \t]*(?:async[ \t]+)?(?:def|fn|func)[ \t]+{re.escape(base)}\b", text, re.M)
    return text[:m.start()].count("\n") if m else 0


def parse_pytest_collect(out: str, root: Path) -> list:
    tests = []
    for line in out.splitlines():
        line = line.strip()
        if "::" not in line or line.startswith(("=", "<")) or " " in line.split("::")[0]:
            continue
        file = line.split("::")[0]
        name = line.split("::", 1)[1]
        tests.append({"id": line, "name": name.replace("::", " › "), "file": file, "line": test_line(root, file, name), "group": file})
    return tests


def parse_junit(xml: str) -> dict:
    """pytest's JUnit XML -> {test id: {status, message, seconds}}."""
    import xml.etree.ElementTree as ET
    out = {}
    try:
        tree = ET.fromstring(xml)
    except ET.ParseError:
        return out
    for case in tree.iter("testcase"):
        cls, name = case.get("classname", ""), case.get("name", "")
        status, msg = "passed", ""
        for child in case:
            if child.tag in ("failure", "error"):
                status, msg = "failed", (child.get("message") or "") + "\n" + (child.text or "")
            elif child.tag == "skipped":
                status, msg = "skipped", child.get("message") or ""
        out[(cls, name)] = {"status": status, "message": msg.strip()[:4000], "seconds": float(case.get("time") or 0)}
    return out


def junit_for(results: dict, test_id: str) -> dict:
    """Find a pytest id (path/to/test_x.py::Class::test_y) among JUnit results keyed (classname, name)."""
    file, _, rest = test_id.partition("::")
    mod = file[:-3].replace("/", ".") if file.endswith(".py") else file
    parts = rest.split("::")
    name = parts[-1]
    cls = ".".join([mod] + parts[:-1])
    return results.get((cls, name)) or next((v for (c, n), v in results.items() if n == name and c.endswith(".".join(parts[:-1]) if parts[:-1] else mod.split(".")[-1])), None)


def parse_cargo(out: str) -> dict:
    res = {}
    for m in re.finditer(r"^test (\S+) \.\.\. (ok|FAILED|ignored)", out, re.M):
        res[m.group(1)] = {"status": {"ok": "passed", "FAILED": "failed", "ignored": "skipped"}[m.group(2)], "message": "", "seconds": 0.0}
    for m in re.finditer(r"^---- (\S+) stdout ----\n(.*?)(?=^---- |\Z|^failures:)", out, re.M | re.S):
        if m.group(1) in res:
            res[m.group(1)]["message"] = m.group(2).strip()[:4000]
    return res


def parse_go(out: str) -> dict:
    res = {}
    last = {}
    for line in out.splitlines():
        m = re.match(r"\s*--- (PASS|FAIL|SKIP): (\S+) \(([\d.]+)s\)", line)
        if m:
            res[m.group(2)] = {"status": {"PASS": "passed", "FAIL": "failed", "SKIP": "skipped"}[m.group(1)], "message": "\n".join(last.get(m.group(2), []))[:4000], "seconds": float(m.group(3))}
            continue
        m = re.match(r"=== RUN\s+(\S+)", line)
        if m:
            cur = m.group(1)
            last[cur] = []
        elif last:
            last[list(last)[-1]].append(line.strip())
    return res


def run_command(root: Path, doc_path: str, lang: str) -> str:
    """What Run does: the project's own way if it has one, otherwise run the file in front."""
    if root:
        if (root / ".huginn-run").is_file():
            return (root / ".huginn-run").read_text(encoding="utf-8").strip()
        if (root / "project.godot").is_file() and hb.godot_command(root):
            return f"{hb.godot_command(root)} --path ."
        if hb.uproject_of(root) and hb.unreal_root(hb.uproject_of(root)):
            return f"{shlex.quote(hb.unreal_root(hb.uproject_of(root)) + '/Engine/Binaries/Linux/UnrealEditor')} {shlex.quote(str(hb.uproject_of(root)))}"
        if (root / "Cargo.toml").is_file():
            return "cargo run"
        if (root / "go.mod").is_file():
            return "go run ."
        pkg = root / "package.json"
        if pkg.is_file():
            try:
                scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
            except (OSError, ValueError):
                scripts = {}
            for name in ("dev", "start"):
                if name in scripts:
                    return f"npm run {name}"
        if (root / "CMakeLists.txt").is_file():
            return "cmake -S . -B build && cmake --build build"
        if (root / "Makefile").is_file() or (root / "makefile").is_file():
            return "make"
        if (root / "manage.py").is_file():
            return "python3 manage.py runserver"
    if doc_path and lang in RUNNERS:
        return RUNNERS[lang].format(f=doc_path)
    return ""


def list_files(root: Path) -> list:
    """Every file in the project, relative paths: Git's own list (which honours .gitignore) when it's a repository."""
    if (root / ".git").exists() and shutil.which("git"):
        try:
            out = git(root, "ls-files", "-co", "--exclude-standard", "-z", timeout=20)
            if out.returncode == 0:                         # a file in conflict is listed once for each side: once is enough
                return list(dict.fromkeys(p for p in out.stdout.split("\0") if p))[:LIST_LIMIT]
        except (OSError, subprocess.SubprocessError):
            pass
    found = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in HEAVY)
        rel = os.path.relpath(dirpath, root)
        for f in sorted(files):
            found.append(f if rel == "." else f"{rel}/{f}")
            if len(found) >= LIST_LIMIT:
                return found
    return found


def search_files(root: Path, query: str, case: bool, regex: bool, word: bool, cap: int = 2000) -> list:
    """Every line in the project matching `query`: [{path, line, col, length, text}]. Uses ripgrep when it's there."""
    if not query:
        return []
    hits = []
    if shutil.which("rg"):
        args = ["rg", "--json", "--max-columns", "400", "--max-columns-preview", "--max-filesize", "4M"]
        args += ["-s" if case else "-i"]
        if not regex:
            args.append("-F")
        if word:
            args.append("-w")
        args += ["-g", "!.git", "--", query, "."]
        try:
            proc = subprocess.Popen(args, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
            for raw in proc.stdout:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if msg.get("type") != "match":
                    continue
                data = msg["data"]
                text = data["lines"].get("text", "").rstrip("\n")
                for sub in data.get("submatches", [])[:20]:
                    col = len(data["lines"].get("text", "").encode("utf-8")[:sub["start"]].decode("utf-8", "ignore"))
                    length = len(sub["match"].get("text", ""))
                    hits.append({"path": data["path"]["text"].removeprefix("./"), "line": data["line_number"] - 1, "col": col, "length": length, "text": text})
                if len(hits) >= cap:
                    proc.kill()
                    break
            proc.wait(timeout=5)
            return hits[:cap]
        except (OSError, subprocess.SubprocessError):
            hits = []
    flags = 0 if case else re.I
    try:
        pattern = re.compile(query if regex else re.escape(query), flags)
    except re.error:
        return []
    for rel in list_files(root):
        p = root / rel
        try:
            if p.stat().st_size > 4 * 1024 * 1024:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        for n, line in enumerate(data.decode("utf-8", "replace").split("\n")):
            for m in pattern.finditer(line):
                if word and ((m.start() > 0 and (line[m.start() - 1].isalnum() or line[m.start() - 1] == "_")) or (m.end() < len(line) and (line[m.end()].isalnum() or line[m.end()] == "_"))):
                    continue
                hits.append({"path": rel, "line": n, "col": m.start(), "length": m.end() - m.start(), "text": line[:400]})
                if len(hits) >= cap:
                    return hits
    return hits


# ============================================================================================ the app
class Code(QObject):
    changed = Signal()            # tabs, status, problems, git
    treeChanged = Signal()
    textLoaded = Signal(int)      # the editor for tab n must take the file's text again
    jump = Signal(int, int, int)  # tab, line, column: move the cursor there
    completions = Signal(int, "QVariantList")   # tab, items
    hoverText = Signal(int, str)
    searchDone = Signal()
    said = Signal(str, bool)
    shown = Signal()
    _back = Signal(object)
    signature = Signal(int, str, int, int, str)   # tab, the call's label, the argument being typed (from, to), its notes
    fixesFound = Signal(int, "QVariantList")      # tab, [{title}]

    def __init__(self, demo: bool = False, target: str = "", shell_class=None, settings=None, trash=None):
        super().__init__()
        self._back.connect(lambda fn: fn())
        self._lang_done.connect(self._language_added)
        self._tools_done.connect(self._tools_added)
        self._demo, self._shell_class, self._settings, self._trash = demo, shell_class, settings, trash
        self._root, self._docs, self._at = None, [], -1
        self._open_dirs, self._tree, self._files_cache = set(), [], None
        self._recent, self._size, self._wrap = [], 14, False
        self._user, self._proj, self._hide, self._launch_list, self._theme = {}, {}, [], [], {}
        self._places, self._closed = {}, []                      # where the cursor was in each file; the tabs closed, latest last
        self._results, self._searching, self._query = [], False, ""
        self._branch, self._changes, self._git = "", [], False
        self._servers, self._server_note = {}, {}
        self._term, self._busy = None, ""
        self._results_title = ""
        self._remote_poll = QTimer(self, interval=1000)
        self._remote_poll.timeout.connect(self._remote_check)
        self._box, self._box_cfg, self._box_tries, self._home_there = None, None, 0, {}
        self._roots, self._shut_roots, self._space_file = [], set(), ""      # a workspace's folders (the first is where it is remembered), the ones folded shut, its .code-workspace file
        self._kernels = {}                                           # {a notebook's path: the Python running its cells}
        self._nb_later = QTimer(self, interval=400, singleShot=True)
        self._nb_later.timeout.connect(self._nb_flush_all)
        self._nb_tell = QTimer(self, interval=60, singleShot=True)   # (a cell printing fast doesn't redraw the window per line)
        self._nb_tell.timeout.connect(self._nb_told)
        self._nb_dirty_tabs = set()
        self._box_poll = QTimer(self, interval=1500)
        self._box_poll.timeout.connect(self._box_check)
        self._auto_save = QTimer(self, interval=1000, singleShot=True)
        self._auto_save.timeout.connect(lambda: self.autoSave("delay"))
        self._build = hb.Builder(self, save_all=lambda: self.saveAll(), env_path=EXTRA_BIN, known=lambda: self._vs_vars(), remote=lambda: self._place())
        self._build.goTo.connect(lambda path, line, col: self.openFile(path, True, line, col))
        self._build.said.connect(self.said.emit)
        self._build.finished.connect(self._built)
        self._build.wantsTools.connect(self._tools_wanted)
        self._dbg = hd.Debugger(self)
        self._dbg.landed.connect(self._landed)
        self._dbg.said.connect(self.said.emit)
        self._dbg.changed.connect(self._dbg_changed)
        self._watch = QFileSystemWatcher(self)
        self._watch.directoryChanged.connect(lambda _p: self._soon.start())
        self._watch.fileChanged.connect(lambda _p: self._soon.start())         # an open file changed on disk
        self._soon = QTimer(self, singleShot=True, interval=400)
        self._soon.timeout.connect(self._refresh)
        self._lint = QTimer(self, singleShot=True, interval=500)
        self._lint.timeout.connect(self._push_changes)
        self._live = QTimer(self, singleShot=True, interval=600)      # the gutter's change marks follow your typing
        self._live.timeout.connect(self._live_marks)
        self._stash = QTimer(self, singleShot=True, interval=2000)    # and unsaved work is put by, a moment after each change
        self._stash.timeout.connect(self._stash_now)
        self._brought = []
        self._tell = QTimer(self, singleShot=True, interval=1500)
        self._tell.timeout.connect(self._tell_brought)
        from PySide6.QtCore import QCoreApplication
        if QCoreApplication.instance():
            QCoreApplication.instance().aboutToQuit.connect(self._nb_quit)
            QCoreApplication.instance().aboutToQuit.connect(self._stash_now)
            QCoreApplication.instance().aboutToQuit.connect(self._keep)        # (where the cursor was in each file goes with it)
        self._load_state()
        if demo:
            self._demo_fill()
        elif target:
            t = Path(target).expanduser()
            if t.is_dir():
                self.openFolder(str(t))
            elif t.exists():
                self._restore_last(keep_docs=False)
                self.openFile(str(t))
        else:
            self._restore_last()
        self._bring_back()

    # ---------------------------------------------------------------- remembering
    def _load_state(self) -> None:
        try:
            data = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self._state = data if isinstance(data, dict) else {}
        self._recent = [r for r in self._state.get("recent", []) if isinstance(r, str)][:10]
        self._user = vsc.load_user()
        if not vsc.SETTINGS_FILE.exists():                         # what Code kept in its state before it had settings
            old = {"editor.formatOnSave": "formatOnSave", "files.trimTrailingWhitespace": "trimOnSave", "files.insertFinalNewline": "trimOnSave",
                   "editor.guides.indentation": "guides", "editor.occurrencesHighlight": "occurrences", "editor.minimap.enabled": "minimap", "editor.fontSize": "size"}
            self._user.update({k: self._state[v] for k, v in old.items() if v in self._state and vsc.clean(k, self._state[v]) is not None})
            if "wrap" in self._state:
                self._user["editor.wordWrap"] = "on" if self._state["wrap"] else "off"
        self._theme = self._state.get("theme") if isinstance(self._state.get("theme"), dict) else {}
        self._apply_settings()

    # ---------------------------------------------------------------- settings (VS Code's names; the project's lie over the user's)
    def setting(self, key: str, d=None):
        return vsc.value(key, self._user, self._proj, vsc.vs_ids_for(d.lang, LANGS) if d is not None and d.lang else ())

    def _apply_settings(self) -> None:
        """What a few settings are also kept as, for the window's own properties."""
        self._size = self.setting("editor.fontSize")
        self._wrap = self.setting("editor.wordWrap") == "on"
        self._minimap = bool(self.setting("editor.minimap.enabled"))
        self._hide = [k for k, v in self.setting("files.exclude").items() if v] + [p for p in vsc.excluded(self._proj) if p not in self.setting("files.exclude")]
        ASSOCIATIONS[:] = vsc.associations(dict(self._user, **self._proj), LANGS) + list(self._ext_data()["types"])      # (your own come first)

    def _set_user(self, key: str, value) -> None:
        value = vsc.clean(key, value)
        if value is None:
            return
        if value == vsc.DEFAULTS.get(key):
            self._user.pop(key, None)                               # (the file holds only what differs from the defaults)
        else:
            self._user[key] = value
        if not self._demo:
            vsc.save_user(self._user)
        self._apply_settings()

    @Slot(str, "QVariant")
    def setSetting(self, key: str, value) -> None:
        """Change one of Code's own settings (the Settings page, and the commands that toggle one)."""
        if hasattr(value, "toVariant"):
            value = value.toVariant()
        if key not in vsc.KINDS:
            return
        if vsc.KINDS[key] == "numbers" and isinstance(value, str):
            value = [int(n) for n in re.findall(r"\d+", value)]
        if vsc.KINDS[key] == "globs" and isinstance(value, str):
            value = {line.strip(): True for line in value.splitlines() if line.strip()}
        if vsc.KINDS[key] == "int" and isinstance(value, str) and value.strip().lstrip("-").isdigit():
            value = int(value)
        self._set_user(key, value)
        self._files_cache = None
        if key == "files.exclude":
            self._soon.start()
        if key == "huginn.keymap":
            self.keysChanged.emit()
        self.changed.emit()

    @Slot(str)
    def resetSetting(self, key: str) -> None:
        if key in vsc.DEFAULTS:
            self.setSetting(key, vsc.DEFAULTS[key])

    def _get_settings(self) -> list:
        rows = []
        for key, group, kind, default, title, about, choices in vsc.SCHEMA:
            now = vsc.value(key, self._user, self._proj)
            shown = ", ".join(str(n) for n in now) if kind == "numbers" else "\n".join(k for k, v in now.items() if v) if kind == "globs" else now
            rows.append({"key": key, "group": group, "kind": kind, "title": title, "about": about, "value": shown, "choices": list(choices) if kind == "choice" else [],
                         "low": choices[0] if kind == "int" else 0, "high": choices[1] if kind == "int" else 0, "where": vsc.where_set(key, self._user, self._proj),
                         "changed": key in self._user})
        return rows
    settingsList = Property("QVariantList", _get_settings, notify=changed)

    # ---------------------------------------------------------------- a VS Code colour theme, and what VS Code kept in the home
    theme = Property("QVariantMap", lambda self: self._theme or {}, notify=changed)

    @Slot(str, result=str)
    def importTheme(self, path: str) -> str:
        """Use a VS Code colour theme file (.json). Returns "" when it's in use, else why not."""
        path = path.replace("file://", "").strip()
        data = vsc.load_jsonc(path)
        if data is None:
            return "That file isn't there, or isn't a theme Code can read (a VS Code colour theme is a .json file)."
        got = vsc.theme(data, Path(path).stem)
        if not got:
            return "That file has no editor colours in it, so it isn't a colour theme."
        self._theme = got
        self._set_user("workbench.colorTheme", got["name"])
        self._keep()
        self.changed.emit()
        return ""

    @Slot()
    def clearTheme(self) -> None:
        self._theme = {}
        self._set_user("workbench.colorTheme", "")
        self._keep()
        self.changed.emit()

    # ---------------------------------------------------------------- extensions (huginn_extensions.py says what they can be)
    def _ext_data(self) -> dict:
        if getattr(self, "_ext", None) is None:
            self._ext = hx.gather(LANGS)
        return self._ext

    def _ext_changed(self) -> None:
        self._ext = None
        self._apply_settings()
        self._read_project()
        self.keysChanged.emit()
        self.changed.emit()

    extensions = Property("QVariantList", lambda self: [{k: v for k, v in row.items() if k != "manifest"} for row in hx.installed()], notify=changed)
    extensionThemes = Property("QVariantList", lambda self: list(self._ext_data()["themes"]), notify=changed)
    extensionCommands = Property("QVariantList", lambda self: list(self._ext_data()["commands"]), notify=changed)
    extensionsFound = Signal("QVariantList", str)            # what the registry answered, or why it didn't

    @Slot(str, result=str)
    def installExtension(self, path: str) -> str:
        """Install a .vsix file (or an extension's folder). Returns what happened, in words; "" for nothing typed."""
        if not path.strip():
            return ""
        try:
            row = hx.install(path)
        except ValueError as err:
            return str(err)
        self._ext_changed()
        return f"Installed “{row['name']}”: {row['takes']}." + (f" Left out: {row['leaves']}." if row["leaves"] else "")

    @Slot(str)
    def removeExtension(self, ident: str) -> None:
        if hx.remove(ident):
            if self._theme.get("ext") == ident:
                self.clearTheme()
            self._ext_changed()

    @Slot(str, bool)
    def setExtensionOn(self, ident: str, on: bool) -> None:
        if any(row["id"] == ident for row in hx.installed()):
            hx.set_on(ident, on)
            self._ext_changed()

    @Slot(str, str, result=str)
    def useExtensionTheme(self, ident: str, label: str) -> str:
        row = next((t for t in self._ext_data()["themes"] if t["ext"] == ident and t["label"] == label), None)
        if row is None:
            return "That theme isn't installed any more."
        why = self.importTheme(row["path"])
        if not why:
            self._theme = dict(self._theme, name=label, ext=ident)
            self._set_user("workbench.colorTheme", label)
            self._keep()
            self.changed.emit()
        return why

    @Slot(int)
    def runExtensionCommand(self, index: int) -> None:
        """An extension's own command: its line, with ${file} and the rest filled in, typed into the terminal."""
        rows = self._ext_data()["commands"]
        if 0 <= index < len(rows):
            missing = []
            known = {k: shlex.quote(str(v)) for k, v in self._vs_vars().items()}       # (a file's name is one word to the shell, whatever is in it)
            line = vsc.substitute(rows[index]["run"], known, None, missing)
            if missing:
                self.said.emit(f"“{rows[index]['title']}” asks for {missing[0]}, which Code can't answer.", True)
                return
            self.run(line)

    @Slot(str)
    def searchExtensions(self, query: str) -> None:
        """Ask the Open VSX registry; the answer comes back as extensionsFound."""
        if self._demo:
            self.extensionsFound.emit([], "")
            return

        def go():
            try:
                rows, why = hx.search(query), ""
            except ValueError as err:
                rows, why = [], str(err)
            self._back.emit(lambda: self.extensionsFound.emit(rows, why))
        threading.Thread(target=go, daemon=True).start()

    @Slot(str, str)
    def fetchExtension(self, namespace: str, name: str) -> None:
        """Fetch an extension from Open VSX and install its data part."""
        if self._demo:
            self.said.emit(f"Would fetch {namespace}.{name} from Open VSX.", False)
            return
        self.said.emit(f"Fetching {namespace}.{name}…", False)

        def go():
            try:
                row = hx.fetch(namespace, name)
                text, bad = f"Installed “{row['name']}”: {row['takes']}." + (f" Left out: {row['leaves']}." if row["leaves"] else ""), False
            except ValueError as err:
                text, bad = str(err), True
            self._back.emit(lambda: (None if bad else self._ext_changed(), self.said.emit(text, bad)))
        threading.Thread(target=go, daemon=True).start()

    vscodeFolder = Property(str, lambda self: str(vsc.user_dir() or ""), notify=changed)

    @Slot(result=str)
    def importFromVSCode(self) -> str:
        """Bring the user's snippets, editor settings and key bindings over from VS Code's own folder. Returns what
        came, in words."""
        got = vsc.user_import(LANGS)
        if not got["found"]:
            return "VS Code's settings weren't found on this computer (they live in ~/.config/Code/User)."
        cfg = vsc.load_jsonc(Path(got["found"]) / "settings.json")
        took = 0
        for key in vsc.KINDS:
            if isinstance(cfg, dict) and key in cfg and key not in ("workbench.colorTheme", "huginn.keymap") and vsc.clean(key, cfg[key]) is not None:
                self._user[key] = vsc.clean(key, cfg[key])
                took += 1
        for block, rows in (cfg.items() if isinstance(cfg, dict) else ()):
            if block.startswith("[") and isinstance(rows, dict):
                keep = {k: v for k, v in rows.items() if k in vsc.KINDS and vsc.clean(k, v) is not None}
                if keep:
                    self._user[block] = keep
        if got["keys"]:
            self._user["huginn.keys"] = dict(self._user.get("huginn.keys") or {}, **got["keys"])
        if not self._demo:
            vsc.save_user(self._user)
        self._state["snippets"] = {lang: {k: list(v) for k, v in rows.items()} for lang, rows in got["snippets"].items()}
        count = sum(len(rows) for rows in got["snippets"].values())
        self._apply_settings()
        self._read_project()
        self._keep()
        self.keysChanged.emit()
        self.changed.emit()
        parts = [f"{took} setting{'' if took == 1 else 's'}", f"{count} snippet{'' if count == 1 else 's'}", f"{len(got['keys'])} key binding{'' if len(got['keys']) == 1 else 's'}"]
        note = f" Its colour theme, {got['theme']}, lives inside an extension: import the theme's .json file to use it." if got["theme"] else ""
        return "Brought from VS Code: " + ", ".join(parts) + "." + note
    settingsPath = Property(str, lambda self: str(vsc.SETTINGS_FILE), constant=True)
    keysChanged = Signal()

    # ---------------------------------------------------------------- keyboard shortcuts you choose
    def _get_keys(self) -> dict:
        """{command name: key sequence} for the commands whose shortcut isn't Code's own: VS Code's, when that keymap is
        chosen, and over those the ones you set yourself ("" takes a command's shortcut away)."""
        preset = dict(vsc.VSCODE_KEYMAP) if self.setting("huginn.keymap") == "VS Code" else {}
        preset.update(self._ext_data()["keys"])                    # (an extension's key bindings; your own lie over them)
        own = self._user.get("huginn.keys")
        preset.update({str(k): str(v) for k, v in own.items() if isinstance(v, str)} if isinstance(own, dict) else {})
        return preset
    keys = Property("QVariantMap", _get_keys, notify=keysChanged)
    ownKeys = Property("QVariantMap", lambda self: dict(self._user.get("huginn.keys") or {}) if isinstance(self._user.get("huginn.keys"), dict) else {}, notify=keysChanged)

    @Slot(str, str)
    def setKey(self, command: str, sequence: str) -> None:
        """Give a command a shortcut of your own ("" for none)."""
        command, sequence = command.strip()[:120], sequence.strip()[:60]
        if not command:
            return
        if sequence and QKeySequence(sequence).isEmpty():
            return
        own = dict(self._user.get("huginn.keys") or {}) if isinstance(self._user.get("huginn.keys"), dict) else {}
        own[command] = QKeySequence(sequence).toString() if sequence else ""
        self._user["huginn.keys"] = own
        if not self._demo:
            vsc.save_user(self._user)
        self.keysChanged.emit()

    @Slot(str)
    def resetKey(self, command: str) -> None:
        own = dict(self._user.get("huginn.keys") or {}) if isinstance(self._user.get("huginn.keys"), dict) else {}
        if own.pop(command, None) is not None:
            if own:
                self._user["huginn.keys"] = own
            else:
                self._user.pop("huginn.keys", None)
            if not self._demo:
                vsc.save_user(self._user)
            self.keysChanged.emit()

    @Slot()
    def resetKeys(self) -> None:
        if self._user.pop("huginn.keys", None) is not None and not self._demo:
            vsc.save_user(self._user)
        self.keysChanged.emit()

    @Slot(int, int, result=str)
    def keyName(self, key: int, modifiers: int) -> str:
        """What a key press is called ("Ctrl+Shift+K"); "" for a modifier on its own."""
        idle = (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr, Qt.Key.Key_unknown, Qt.Key.Key_Super_L, Qt.Key.Key_Super_R)
        if key <= 0 or key in tuple(k.value for k in idle):
            return ""
        all_mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
        try:
            return QKeySequence(QKeyCombination(Qt.KeyboardModifier(modifiers & all_mods.value), Qt.Key(key))).toString()
        except (ValueError, TypeError):
            return ""

    @Slot()
    def openSettingsFile(self) -> None:
        """Code's own settings.json, to edit by hand (made with what's set now if it isn't there yet)."""
        if not vsc.SETTINGS_FILE.exists() and not self._demo:
            vsc.save_user(self._user)
        self.openFile(str(vsc.SETTINGS_FILE), True)

    def _keep(self) -> None:
        if self._demo:
            return
        first = self._roots[0] if self._roots else self._root       # (a workspace is remembered under its first folder)
        if first:
            inside = tuple(str(r) for r in (self._roots or [first]))
            self._state.setdefault("projects", {})[str(first)] = {"open": [d.path for d in self._docs], "at": self._at, "dirs": sorted(self._open_dirs)[:200],
                                                                 "places": {p: a for p, a in self._places.items() if p.startswith(inside)},
                                                                 "breakpoints": {k: v for k, v in self._dbg.all_breakpoints().items() if k.startswith(inside)}}
            spaces = self._state.setdefault("spaces", {}) if isinstance(self._state.get("spaces", {}), dict) else {}
            if len(self._roots) > 1:
                spaces[str(first)] = [str(r) for r in self._roots[1:]]
            else:
                spaces.pop(str(first), None)
        self._state.update(recent=self._recent, size=self._size, wrap=self._wrap, minimap=self._minimap, last=(self._space_file if self._space_file and Path(self._space_file).is_file() else str(first)) if first else "", theme=self._theme)
        try:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE.with_suffix(".saving")
            tmp.write_text(json.dumps(self._state), encoding="utf-8")
            os.replace(tmp, STATE)
        except OSError:
            pass

    def _restore_last(self, keep_docs: bool = True) -> None:
        last = self._state.get("last")
        if last and (Path(last).is_dir() or (last.endswith(".code-workspace") and Path(last).is_file())):
            self.openFolder(last, restore=keep_docs)

    def _demo_fill(self) -> None:
        demo = Path(QStandardPaths.writableLocation(QStandardPaths.TempLocation)) / "huginn-code-demo" / "aurora-watch"
        shutil.rmtree(demo, ignore_errors=True)
        (demo / "aurora").mkdir(parents=True)
        (demo / "tests").mkdir()
        (demo / "README.md").write_text("# Aurora Watch\n\nTells you when the northern lights are worth going out for.\n\n```\npython3 -m aurora --city Tromsø\n```\n", encoding="utf-8")
        (demo / "aurora" / "__init__.py").write_text('"""Aurora Watch."""\n__version__ = "0.3.0"\n', encoding="utf-8")
        (demo / "aurora" / "forecast.py").write_text('''"""Is tonight worth it? A score from the Kp index, the clouds and how dark it is."""
from dataclasses import dataclass

DARK_HOURS = range(20, 24)


@dataclass
class Sky:
    kp: float          # geomagnetic activity, 0 to 9
    clouds: int        # percent
    hour: int


def score(sky: Sky) -> int:
    """0 to 100: how likely you'll see it."""
    if sky.hour not in DARK_HOURS:
        return 0
    base = min(sky.kp / 6, 1.0) * 100
    return round(base * (1 - sky.clouds / 100))


def advice(sky: Sky) -> str:
    s = score(sky)
    if s > 60:
        return f"Go now: {s}% chance"
    return "Stay in tonight" if s < 20 else f"Maybe later ({s}%)"
''', encoding="utf-8")
        (demo / "tests" / "test_forecast.py").write_text("from aurora.forecast import Sky, score\n\n\ndef test_cloudy():\n    assert score(Sky(kp=5, clouds=100, hour=22)) == 0\n", encoding="utf-8")
        (demo / "pyproject.toml").write_text('[project]\nname = "aurora-watch"\nversion = "0.3.0"\n', encoding="utf-8")
        self.openFolder(str(demo), restore=False)
        self._open_dirs.update({str(demo / "aurora"), str(demo / "tests")})
        self._build_tree()
        self.openFile(str(demo / "aurora" / "forecast.py"))
        self.openFile(str(demo / "README.md"))
        self.select(0)
        self._branch, self._git = "main", True
        self._changes = [{"path": "aurora/forecast.py", "x": " ", "y": "M", "kind": "changed", "staged": False, "unstaged": True},
                         {"path": "tests/test_forecast.py", "x": "?", "y": "?", "kind": "new", "staged": False, "unstaged": True}]
        d = self._docs[0]
        d.marks = {14: "mod", 15: "mod", 22: "add", 23: "add"}
        d.problems = [{"line": 17, "col": 11, "endLine": 17, "endCol": 15, "severity": 2, "message": "'base' could be negative when kp is below zero", "source": "demo"}]
        d.text = d.text.replace("    s = score(sky)", "    s = score(sky)  # one number for the window")
        self.changed.emit()

    # ---------------------------------------------------------------- the project
    @Slot(str)
    def openFolder(self, path: str, restore: bool = True) -> None:
        try:                                                       # read before opening: opening saves the state again
            saved = ((self._state.get("projects") or {}).get(str(Path(path.replace("file://", "")).expanduser().resolve())) or {}).get("breakpoints") or {}
        except (OSError, RuntimeError):
            saved = {}
        self._open_folder(path, restore)
        if self._root:                                             # the project's breakpoints come back with it
            self._dbg.set_all(saved)
            self._keep()
            self.changed.emit()

    def _open_folder(self, path: str, restore: bool = True) -> None:
        if not path.strip():                                  # (no path isn't "the folder Code happened to start in")
            return
        root = Path(path.replace("file://", "")).expanduser().resolve()
        space = {}
        if root.is_file() and root.suffix == ".code-workspace":     # VS Code's workspace file: its (first) folder, with its settings
            folders, space = vsc.workspace_settings(root)
            if not folders:
                self.said.emit("That workspace file names no folder.", True)
                return
            there = [f for f in folders if Path(f).is_dir()]
            if not there:
                self.said.emit("None of that workspace's folders are there any more.", True)
                return
            if len(there) < len(folders):
                self.said.emit(f"{len(folders) - len(there)} of that workspace's folders {'is' if len(folders) - len(there) == 1 else 'are'}n't there any more, and left out.", False)
            extra, space_file = [Path(f) for f in there[1:]], str(root)
            root = Path(there[0])
        else:
            extra, space_file = None, ""
        if not root.is_dir():
            self.said.emit("That folder isn't there any more.", True)
            return
        if extra is None and root in self._roots and len(self._roots) > 1:      # one of the open workspace's own folders: work in it
            self._set_active(root)
            return
        if extra is None:                                          # a folder that was a workspace when it was last open is one again
            kept = (self._state.get("spaces") or {}).get(str(root)) if isinstance(self._state.get("spaces"), dict) else None
            extra = [Path(f) for f in (kept if isinstance(kept, list) and restore else []) if isinstance(f, str) and Path(f).is_dir() and Path(f) != root][:15]
        if self._root and root != self._root:
            if any(d.dirty for d in self._docs):
                self.said.emit("Save or close your changed files first.", True)
                return
            self._keep()                                           # (the folder being left: its tabs and where the cursor was in each)
            self._close_all()
        self._root = root
        self._roots = [root] + [f for f in dict.fromkeys(extra) if f != root]
        self._shut_roots, self._space_file = set(), space_file
        self._space = space
        self._read_project()
        self._box_found()
        self._recent = [str(root)] + [r for r in self._recent if r != str(root)]
        del self._recent[10:]
        saved = self._state.get("projects", {}).get(str(root), {}) if restore else {}
        places = saved.get("places") if isinstance(saved.get("places"), dict) else {}
        self._places = {p: a for p, a in list(places.items())[-400:] if isinstance(p, str) and isinstance(a, int) and a >= 0}
        self._closed = []
        self._open_dirs = {d for d in saved.get("dirs", []) if Path(d).is_dir()}
        self._files_cache = None
        self._build_tree()
        for p in saved.get("open", []):
            if Path(p).is_file():
                self.openFile(p, focus=False)
        if restore:
            self._bring_back()
        if self._docs:
            self.select(max(0, min(saved.get("at", 0), len(self._docs) - 1)))
        self.refreshGit()
        self._build.set_root(root)
        self._keep()
        self.changed.emit()

    def _close_all(self) -> None:
        self._nb_flush_all()
        self._stash_now()
        for d in self._docs:
            self._lsp_close(d)
            self._nb_end(d.path)
        self._docs, self._at = [], -1
        for s in self._servers.values():
            if s:                                             # (None: a language whose server wouldn't start)
                s.stop()
        self._servers = {}

    @Slot()
    def closeFolder(self) -> None:
        if any(d.dirty for d in self._docs):
            self.said.emit("Save or close your changed files first.", True)
            return
        self._close_all()
        self._root, self._tree, self._branch, self._changes, self._git = None, [], "", [], False
        self._roots, self._shut_roots, self._space_file = [], set(), ""
        self._box = None
        self._space = {}
        self._read_project()
        self._build.set_root(None)
        self._keep()
        self.treeChanged.emit()
        self.changed.emit()

    def _build_tree(self) -> None:
        rows = []
        if self._root:
            status = {}
            for c in self._changes:
                status[c["path"]] = c["kind"]
                parts = c["path"].split("/")
                for k in range(1, len(parts)):
                    status.setdefault("/".join(parts[:k]) + "/", "inside")

            def walk(folder: Path, depth: int, top: Path) -> None:
                try:
                    entries = sorted(os.scandir(folder), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
                except OSError:
                    return
                mine = top == self._root                      # (Git's marks are the working folder's)
                for e in entries:
                    if e.name == ".git" or (self._hide and vsc.is_excluded(os.path.relpath(e.path, top), self._hide)):
                        continue
                    try:
                        is_dir = e.is_dir()
                    except OSError:                           # a link that leads nowhere sensible (through a file, round in a ring)
                        is_dir = False
                    rel = os.path.relpath(e.path, top)
                    open_ = is_dir and e.path in self._open_dirs
                    rows.append({"path": e.path, "name": e.name, "depth": depth, "dir": is_dir, "open": open_, "rel": rel,
                                 "git": status.get(rel + "/" if is_dir else rel, "") if mine else "", "dim": e.name.startswith(".") or e.name in HEAVY,
                                 "lang": "" if is_dir else language_of(e.name)})
                    if open_:
                        walk(Path(e.path), depth + 1, top)
            many = len(self._roots) > 1
            names = self._root_names()
            for top in (self._roots if many else [self._root]):
                if many:                                          # a workspace: each folder under its own heading
                    shut = str(top) in self._shut_roots
                    rows.append({"path": str(top), "name": next((n for n, r in names.items() if r == top), top.name), "depth": 0, "dir": True, "open": not shut, "rel": "", "git": "",
                                 "dim": False, "lang": "", "root": True, "active": top == self._root})
                    if shut:
                        continue
                walk(top, 1 if many else 0, top)
            tops = [str(r) for r in (self._roots if many else [self._root])]
            dirs = tops + sorted(d for d in self._open_dirs if d.startswith(tuple(tops)))
            old = set(self._watch.directories()) | set(self._watch.files())
            if old:
                self._watch.removePaths(list(old))
            self._watch.addPaths([d for d in dirs if Path(d).is_dir()][:300] + [d.path for d in self._docs if Path(d.path).is_file()][:200])
        self._tree = rows
        self.treeChanged.emit()

    def _refresh(self) -> None:
        self._files_cache = None
        if self._root:
            self._build_tree()
        else:
            missing = [d.path for d in self._docs if d.path not in self._watch.files() and Path(d.path).is_file()]
            if missing:
                self._watch.addPaths(missing)
        self.refreshGit()
        for i, d in enumerate(self._docs):                   # a file changed by something else, with nothing typed here: take it
            try:
                m = Path(d.path).stat().st_mtime
            except OSError:
                continue
            if d.mtime and abs(m - d.mtime) > 0.001 and not d.dirty:
                d.load()
                self.textLoaded.emit(i)

    @Slot(str)
    def toggle(self, path: str) -> None:
        if len(self._roots) > 1 and any(str(r) == path for r in self._roots):      # a workspace folder's heading folds it
            self._shut_roots ^= {path}
            self._build_tree()
            return
        if path in self._open_dirs:
            self._open_dirs = {d for d in self._open_dirs if not (d == path or d.startswith(path + os.sep))}
        else:
            self._open_dirs.add(path)
        self._build_tree()
        self._keep()

    @Slot(str, result="QVariantList")
    def browse(self, path: str) -> list:
        """Folders inside `path`, for picking a project."""
        base = Path(path or Path.home()).expanduser()
        try:
            return [{"name": e.name, "path": e.path, "git": os.path.isdir(os.path.join(e.path, ".git"))}
                    for e in sorted(os.scandir(base), key=lambda e: e.name.lower()) if e.is_dir() and not e.name.startswith(".")][:400]
        except OSError:
            return []

    @Slot(str, str, bool, result=str)
    def create(self, folder: str, name: str, is_dir: bool) -> str:
        name = name.strip()
        if not name:
            return "Type a name."
        if name in (".", "..") or "\0" in name or ".." in name.split("/") or any(len(part.encode("utf-8", "replace")) > 255 for part in name.split("/")):
            return "That name can't be used."
        base = Path(folder or self._root or Path.home())
        target = (base / name).resolve()
        if self._root and not (str(target) + os.sep).startswith(str(self._root) + os.sep):
            return "That would be outside the project."
        if target.exists():
            return "Something with that name is already there."
        try:
            if is_dir:
                target.mkdir(parents=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("", encoding="utf-8")
        except OSError as e:
            return f"Couldn't make it: {e.strerror or e}"
        self._open_dirs.add(str(target.parent))
        self._files_cache = None
        self._build_tree()
        if not is_dir:
            self.openFile(str(target))
        return ""

    def _not_ours(self, path: str) -> str:
        """Why Code won't rename or remove `path` ("" if it may): only what's inside the open folder (or, with none open,
        a file open in a tab), never the folder itself, your home folder or anything above them."""
        if not path or not os.path.lexists(path):
            return "That isn't there any more."
        here = os.path.abspath(path)
        if here in (os.path.abspath(os.sep), str(Path.home())) or (self._root and here == str(self._root)):
            return "That can't be renamed or removed from here."
        if self._root:
            if not here.startswith(str(self._root) + os.sep):
                return "That's outside this project."
        elif not any(d.path == here for d in self._docs):
            return "That's outside what's open here."
        return ""

    @Slot(str, str, result=str)
    def rename(self, path: str, name: str) -> str:
        name = name.strip()
        if not name or "/" in name or name in (".", ".."):
            return "Type a new name (without slashes)."
        if "\0" in name or len(name.encode("utf-8", "replace")) > 255:
            return "That name can't be used."
        why = self._not_ours(path)
        if why:
            return why
        src = Path(path)
        dst = src.with_name(name)
        if dst.exists() or dst.is_symlink():
            return "Something with that name is already there."
        try:
            src.rename(dst)
        except OSError as e:
            return f"Couldn't rename it: {e.strerror or e}"
        for i, d in enumerate(self._docs):
            if d.path == str(src) or d.path.startswith(str(src) + os.sep):
                self._lsp_close(d)
                d.path = str(dst) + d.path[len(str(src)):]
                d.lang = language_of(d.path, d.text[:200])
                self._lsp_open(d)
        self._open_dirs = {str(dst) + p[len(str(src)):] if p == str(src) or p.startswith(str(src) + os.sep) else p for p in self._open_dirs}
        self._files_cache = None
        self._build_tree()
        self.changed.emit()
        return ""

    @Slot(str, result=str)
    def remove(self, path: str) -> str:
        """To the Trash, never deleted outright."""
        why = self._not_ours(path)
        if why:
            return why
        if any(d.dirty and (d.path == path or d.path.startswith(path + os.sep)) for d in self._docs):
            return "It has unsaved changes open; save or close them first."
        try:
            if self._trash:
                self._trash(path)
            else:
                subprocess.run(["gio", "trash", path], check=True, capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as e:
            return f"Couldn't move it to the Trash: {e}"
        for i in reversed(range(len(self._docs))):
            d = self._docs[i]
            if d.path == path or d.path.startswith(path + os.sep):
                self._lsp_close(d)
                del self._docs[i]
        self._at = min(self._at, len(self._docs) - 1)
        self._files_cache = None
        self._build_tree()
        self.refreshGit()
        self.changed.emit()
        return ""

    @Slot(str)
    def reveal(self, path: str) -> None:
        import sys
        QProcess.startDetached(sys.executable, [str(Path(__file__).with_name("huginn_app.py")), "files", str(Path(path).parent if Path(path).is_file() else path)])

    # ---------------------------------------------------------------- open files
    @Slot(str)
    def openFile(self, path: str, focus: bool = True, line: int = -1, col: int = 0) -> None:
        path = str(Path(path.replace("file://", "")).expanduser().resolve())
        for i, d in enumerate(self._docs):
            if d.path == path:
                if focus:
                    self.select(i)
                if line >= 0:
                    self.jump.emit(i, line, col)
                return
        d = Doc(path)
        try:
            d.load()
        except OSError as e:
            self.said.emit(f"Couldn't open {Path(path).name}: {e.strerror or e}", True)
            return
        if not d.text and not d.binary:                        # an empty file has no line endings of its own yet: the project's
            eol = self._config(d).get("end_of_line")
            if eol in ("crlf", "lf"):
                d.crlf = eol == "crlf"
        self._stash_apply(d)
        self._docs.append(d)
        idx = len(self._docs) - 1
        if d.path not in self._watch.files():
            self._watch.addPath(d.path)
        self._marks(d)
        self._lsp_open(d)
        self._lint_python(d)
        if focus:
            self._at = idx
            self._follow(d.path)
        elif self._at < 0:
            self._at = 0
        self.changed.emit()
        self.textLoaded.emit(idx)
        if line >= 0:
            self.jump.emit(idx, line, col)
        self._keep()

    @Slot(int)
    def select(self, i: int) -> None:
        if 0 <= i < len(self._docs):
            self._at = i
            self._follow(self._docs[i].path)
            self.changed.emit()
            self._keep()

    @Slot(int, bool, result=str)
    def close(self, i: int, force: bool = False) -> str:
        """"" when closed, "dirty" when it has unsaved changes (ask, then call again with force)."""
        if not 0 <= i < len(self._docs):
            return ""
        d = self._docs[i]
        self._nb_flush(d)
        if d.dirty and not force:
            return "dirty"
        self._nb_end(d.path)
        self._lsp_close(d)
        self._stash_drop(d)                                   # closed without saving: you said to let it go
        if not d.path.startswith("untitled:"):
            self._closed = [p for p in self._closed if p != d.path][-19:] + [d.path]
        del self._docs[i]
        if not self._docs:
            self._at = -1
        elif self._at > i:
            self._at -= 1
        elif self._at == i:
            self._at = min(i, len(self._docs) - 1)
        self.changed.emit()
        self._keep()
        return ""

    canReopen = Property(bool, lambda self: bool(self._closed), notify=changed)

    @Slot(str, result=bool)
    def fileThere(self, path: str) -> bool:
        try:
            return any(d.path == path for d in self._docs) or Path(path).is_file()
        except (OSError, ValueError):
            return False

    @Slot()
    def reopenClosed(self) -> None:
        """Open the tab closed last again (and the one before it, asked again), where the cursor was."""
        while self._closed:
            p = self._closed.pop()
            if Path(p).is_file() and not any(d.path == p for d in self._docs):
                self.openFile(p)
                return
        self.said.emit("No closed file to open again.", False)
        self.changed.emit()

    @Slot(int, result=int)
    def placeOf(self, i: int) -> int:
        """Where the cursor was in this file the last time it was open (0: never, or not known)."""
        if not 0 <= i < len(self._docs):
            return 0
        at = self._places.get(self._docs[i].path, 0)
        return at if isinstance(at, int) and 0 <= at <= len(self._docs[i].text) else 0

    @Slot(int, int)
    def setPlace(self, i: int, at: int) -> None:
        if 0 <= i < len(self._docs) and isinstance(at, int) and 0 <= at <= 50_000_000 and not self._docs[i].path.startswith("untitled:"):
            self._places.pop(self._docs[i].path, None)         # (the latest goes to the end: the oldest are the ones dropped)
            self._places[self._docs[i].path] = at
            while len(self._places) > 400:
                self._places.pop(next(iter(self._places)))

    @Slot(int, int)
    def move(self, i: int, to: int) -> None:
        if 0 <= i < len(self._docs) and 0 <= to < len(self._docs) and i != to:
            d = self._docs.pop(i)
            self._docs.insert(to, d)
            self._at = to
            self.changed.emit()

    @Slot(int, str)
    def edit(self, i: int, text: str) -> None:
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]
        if "\r" in text:                                      # (the editor never holds one; text from elsewhere might)
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        if text == d.text:                                    # colouring touches the document too: nothing was typed
            return
        if self.setting("files.autoSave") == "afterDelay":
            self._auto_save.start()
        delta = text.count("\n") - d.text.count("\n")
        if delta and self._dbg.lines_for(d.path):            # breakpoints below an added or removed line move with their code
            old, new = d.text.split("\n"), text.split("\n")
            first = next((k for k, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
            self._dbg.shift(d.path, first, delta)
        was = d.dirty
        d.text = text
        d.version += 1
        self._pending = getattr(self, "_pending", set()) | {i}
        self._lint.start()
        self._live.start()
        self._stash.start()
        if d.dirty != was:
            self.changed.emit()

    @Slot(int, result=str)
    def textOf(self, i: int) -> str:
        return self._docs[i].text if 0 <= i < len(self._docs) else ""

    @Slot(int, bool, result=str)
    def save(self, i: int, force: bool = False) -> str:
        """"" saved, "changed" (the file changed on disk since: ask, then force), "failed"."""
        if not 0 <= i < len(self._docs):
            return "failed"
        d = self._docs[i]
        self._nb_flush(d)
        if d.read_only:
            self.said.emit(d.why or "This file is read only.", True)
            return "failed"
        if self._config(d).get("format_on_save") == "true" and not getattr(self, "_formatting", False):
            c = self._client_for(d, start=False)
            if c and c.up and c.caps.get("documentFormattingProvider"):   # formatted first, then saved (when the formatter answers)
                self._formatting = True

                def after():
                    try:
                        if d in self._docs and self.save(self._docs.index(d), force) == "changed":
                            self.said.emit(f"{Path(d.path).name} changed on disk: save again to replace it.", True)
                    finally:
                        self._formatting = False
                self.format(i, then=after)
                return ""
        self._tidy_before_save(i)
        keep = self.setting("huginn.localHistory") and not self._demo and not d.path.startswith("untitled:")
        if keep and d.saved and d.saved != d.text and not more.history_list(d.path):
            more.history_keep(d.path, d.saved, time.time() - 1)     # (what the file held before Code first changed it)
        try:
            got = d.save(force)
        except OSError as e:
            self.said.emit(f"Couldn't save: {e.strerror or e}", True)
            return "failed"
        if got:
            return got
        client = self._client_for(d, start=False)
        if client:
            client.notify("textDocument/didSave", {"textDocument": {"uri": d.uri}, "text": d.text})
        self._marks(d)
        self._saved_file(d)
        self.refreshGit()
        self.changed.emit()
        return ""

    def _saved_file(self, d: Doc) -> None:
        """A file has just been saved: a copy for its history, and the project's own rules read again if it is one."""
        p = Path(d.path)
        if self.setting("huginn.localHistory") and not self._demo:
            more.history_keep(d.path, d.text)
        if self._root and (p.parent.name == ".vscode" or p.name in (".editorconfig", ".huginn-tasks.json") or p.suffix == ".code-workspace"):
            self._read_project()
            self._build.refresh()
        if p == vsc.SETTINGS_FILE:
            self._user = vsc.load_user()
            self._apply_settings()
            self.keysChanged.emit()

    @Slot(str)
    def autoSave(self, why: str) -> None:
        """Save what's changed, when the setting says to: "delay" (a second after typing stops) or "focus" (on going
        to another tab or app). A file with no name yet, or one that changed on disk meanwhile, is left for you."""
        mode = self.setting("files.autoSave")
        if self._demo or not ((why == "delay" and mode == "afterDelay") or (why == "focus" and mode in ("onFocusChange", "afterDelay"))):
            return
        for i, d in enumerate(self._docs):
            if d.dirty and not d.read_only and not d.path.startswith("untitled:"):
                try:
                    if Path(d.path).is_file() and abs(Path(d.path).stat().st_mtime - (d.mtime or 0)) > 0.001:
                        continue                                    # changed on disk: that question is asked when you save
                except OSError:
                    continue
                self.save(i, False)

    @Slot(result=int)
    def saveAll(self) -> int:
        n = 0
        for i, d in enumerate(self._docs):
            if d.dirty and self.save(i, False) == "":
                n += 1
        return n

    @Slot(int)
    def reload(self, i: int) -> None:
        if 0 <= i < len(self._docs):
            d = self._docs[i]
            d.nb_stale = False                                     # (a notebook's cells are read again from what is on disk)
            try:
                d.load()
            except OSError:
                return
            self._marks(d)
            self.textLoaded.emit(i)
            self.changed.emit()

    @Slot(str)
    def newFileIn(self, lang: str) -> None:
        """A new file in a language: named for it, started with a few lines of it (TEMPLATES), in the open folder
        (or Documents), and opened."""
        info = LANGS.get(lang)
        if not info:
            self.newUntitled()
            return
        folder = self._root or Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or Path.home())
        first = NEW_NAMES.get(lang) or ("untitled" + next((e for e in info[0] if e.startswith(".")), ".txt"))
        stem, ext = (first, "") if "." not in first else (first.rsplit(".", 1)[0], "." + first.rsplit(".", 1)[1])
        n, path = 1, folder / first
        while path.exists():
            n += 1
            path = folder / f"{stem}-{n}{ext}"
        try:
            path.write_text(TEMPLATES.get(lang, ""), encoding="utf-8")
        except OSError as e:
            self.said.emit(f"Couldn't make a file: {e.strerror or e}", True)
            return
        self._files_cache = None
        self._build_tree()
        self.openFile(str(path))

    def _get_languages(self) -> list:
        out = []
        for name, info in LANGS.items():
            if name in ("Diff", "Settings"):
                continue
            pack = LANG_PACKS.get(name, {})
            helper = next((a[0] for a in info[5] if which(a[0])), "") if info[5] else ""
            tools = all(which(t) for t in pack.get("tools", [])) if pack else True
            if name == "GDScript":                                     # Godot is both: there, or not
                helper = "Godot" if hb.godot_command() else ""
                tools = bool(helper)
            out.append({"name": name, "ext": next((e for e in info[0] if e.startswith(".")), info[0][0] if info[0] else ""),
                        "helper": helper, "hasHelper": bool(info[5]), "tools": tools, "canAdd": bool(pack) and (not tools or (bool(info[5]) and not helper)),
                        "adding": name in getattr(self, "_adding", set())})
        return out
    languages = Property("QVariantList", lambda self: self._get_languages(), notify=changed)

    @Slot(str)
    def addLanguage(self, lang: str) -> None:
        """Put in what a language needs (LANG_PACKS): Ubuntu's packages through the system's password prompt, then
        npm's helpers into Code's own tools folder. Its helper starts on the next file opened in it."""
        pack = LANG_PACKS.get(lang)
        if not pack or self._demo or lang in getattr(self, "_adding", set()):
            return
        self._adding = getattr(self, "_adding", set()) | {lang}
        self.changed.emit()
        self.said.emit(f"Adding {lang}…" + (" The system may ask for your password." if pack.get("apt") else " This comes from Flathub and can take a few minutes."), False)

        def work():
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).resolve().parent))
            why = hb.install_pack(pack, self._installed)
            if not why and pack.get("npm"):
                npm = shutil.which("npm")
                if not npm:
                    why = "npm isn't there, so the helper couldn't be fetched."
                else:
                    try:
                        TOOLS_HOME.mkdir(parents=True, exist_ok=True)
                        done = subprocess.run([npm, "install", "-g", "--prefix", str(TOOLS_HOME)] + pack["npm"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
                        if done.returncode != 0:
                            tail = (done.stderr or done.stdout).strip().splitlines()
                            why = "The helper wasn't fetched" + (f" ({tail[-1][:120]})" if tail else "") + "."
                    except (OSError, subprocess.TimeoutExpired) as e:
                        why = f"The helper wasn't fetched ({e})."
            self._lang_done.emit(lang, why)
        threading.Thread(target=work, daemon=True).start()

    _lang_done = Signal(str, str)

    def _language_added(self, lang: str, why: str) -> None:
        self._adding = getattr(self, "_adding", set()) - {lang}
        self._servers.pop(lang, None)                  # look for its helper again
        for alias in ("JavaScript", "TypeScript") if lang in ("JavaScript", "TypeScript") else ("HTML", "CSS", "JSON") if lang in ("HTML", "CSS", "JSON") else ():
            self._servers.pop(alias, None)
        self.changed.emit()
        self.said.emit(why or f"{lang} is ready: suggestions, problems and go-to-definition work in its files now.", bool(why))
        if not why:
            for d in self._docs:
                if d.lang == lang:
                    self._lsp_open(d)

    @staticmethod
    def _installed(package: str) -> bool:
        try:
            done = subprocess.run(["dpkg-query", "-W", "-f=${Status}", package], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
            return "install ok installed" in done.stdout
        except (OSError, subprocess.TimeoutExpired):
            return False

    @Slot()
    def newUntitled(self) -> None:
        folder = self._root or Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or Path.home())
        n, path = 1, folder / "untitled.txt"
        while path.exists():
            n += 1
            path = folder / f"untitled-{n}.txt"
        try:
            path.write_text("", encoding="utf-8")
        except OSError as e:
            self.said.emit(f"Couldn't make a file: {e.strerror or e}", True)
            return
        self._files_cache = None
        self._build_tree()
        self.openFile(str(path))

    # ---------------------------------------------------------------- what QML sees
    def _tab(self, d: Doc) -> dict:
        return {"path": d.path, "name": Path(d.path).name, "dirty": d.dirty, "lang": d.lang, "readOnly": d.read_only, "why": d.why,
                "rel": os.path.relpath(d.path, self._root) if self._root and d.path.startswith(str(self._root)) else d.path,
                "errors": sum(1 for p in d.problems if p["severity"] == 1), "binary": d.binary, "notebook": d.path.lower().endswith(".ipynb") and not d.binary}

    def _get_status(self) -> dict:
        d = self._docs[self._at] if 0 <= self._at < len(self._docs) else None
        if not d:
            return {}
        ind, cfg = self._unit(d), self._config(d)
        server = self._server_note.get(d.lang, "")
        return {"lang": d.lang, "encoding": ("UTF-8" if d.encoding == "utf-8" else "UTF-16" if d.encoding.startswith("utf-16") else "Latin-1") + (" with BOM" if d.bom else ""),
                "eol": "CRLF" if d.crlf else "LF", "indent": "Tab" if ind == "\t" else f"Spaces: {len(ind)}", "indentText": ind,
                "tabWidth": self._tab_width(d), "config": bool(cfg.get("_file")),
                "server": server, "comment": LANGS.get(d.lang, LANGS["Text"])[1], "block": list(LANGS.get(d.lang, LANGS["Text"])[2] or [])}

    def _get_problems(self) -> list:
        out = []
        for i, d in enumerate(self._docs):
            for p in d.problems:
                out.append(dict(p, tab=i, name=Path(d.path).name, path=d.path))
        return sorted(out, key=lambda p: (p["severity"], p["name"], p["line"]))

    tabs = Property("QVariantList", lambda self: [self._tab(d) for d in self._docs], notify=changed)
    current = Property(int, lambda self: self._at, notify=changed)
    tree = Property("QVariantList", lambda self: self._tree, notify=treeChanged)
    root = Property(str, lambda self: str(self._root) if self._root else "", notify=changed)
    rootName = Property(str, lambda self: self._root.name if self._root else "", notify=changed)
    recent = Property("QVariantList", lambda self: [{"path": r, "name": Path(r).name, "where": str(Path(r).parent).replace(str(Path.home()), "~")} for r in self._recent if Path(r).is_dir()], notify=changed)
    status = Property("QVariantMap", _get_status, notify=changed)
    problems = Property("QVariantList", _get_problems, notify=changed)
    branch = Property(str, lambda self: self._branch, notify=changed)
    isGit = Property(bool, lambda self: self._git, notify=changed)
    changes = Property("QVariantList", lambda self: self._changes, notify=changed)
    results = Property("QVariantList", lambda self: self._results, notify=searchDone)
    searching = Property(bool, lambda self: self._searching, notify=searchDone)
    size = Property(int, lambda self: self._size, notify=changed)
    wrap = Property(bool, lambda self: self._wrap, notify=changed)
    busy = Property(str, lambda self: self._busy, notify=changed)
    home = Property(str, lambda self: str(Path.home()), constant=True)
    debug = Property(QObject, lambda self: self._dbg, constant=True)
    build = Property(QObject, lambda self: self._build, constant=True)

    # ---------------------------------------------------------------- build tasks and the tools they need
    askUnreal = Signal()                     # a task needs to know where Unreal Engine is: the window asks for its folder
    _tools_done = Signal(str, str)

    def _built(self, tid: str, code: int) -> None:
        """A task finished: what it made may be new files, and a fresh compile_commands.json is what clangd reads."""
        self._files_cache = None
        self._soon.start()
        waiting, self._after_build = getattr(self, "_after_build", None), None
        if waiting and waiting[0] == tid:
            if code == 0:
                self._launch(waiting[1])
            else:
                self.said.emit("The task before debugging failed, so the debugger wasn't started.", True)
        if code == 0 and tid in ("ue:clangd", "cmake:configure", "cmake:build") and self._root:
            made = next((p for p in (self._root / "compile_commands.json", self._root / "build" / "compile_commands.json") if p.is_file()), None)
            link = self._root / "compile_commands.json"
            if made and made != link and not link.exists():
                try:
                    link.symlink_to(made.relative_to(self._root))        # (clangd looks beside the sources)
                except OSError:
                    pass
            for lang in ("C", "C++"):
                c = self._servers.pop(lang, None)                        # start clangd again so it reads the new list
                if c and c.alive:
                    c.proc.kill()
            for d in self._docs:
                if d.lang in ("C", "C++"):
                    self._lsp_open(d)

    def _tools_wanted(self, what: str) -> None:
        if what == "unreal":
            self.askUnreal.emit()
        else:
            self.addTools(what)

    @Slot(str)
    def addTools(self, name: str) -> None:
        """Put in one of the tool packs a game project needs (huginn_build.TOOL_PACKS)."""
        pack = hb.TOOL_PACKS.get(name)
        adding = getattr(self, "_adding", set())
        if not pack or self._demo or name in adding:
            return
        self._adding = adding | {name}
        self.changed.emit()
        self.said.emit(f"Adding {name}…" + (" The system may ask for your password." if pack.get("apt") else " This comes from Flathub and can take a few minutes."), False)

        def work():
            self._tools_done.emit(name, hb.install_pack(pack, self._installed))
        threading.Thread(target=work, daemon=True).start()

    def _tools_added(self, name: str, why: str) -> None:
        self._adding = getattr(self, "_adding", set()) - {name}
        self._servers = {k: v for k, v in self._servers.items() if v is not None}        # helpers that weren't there may be now
        self._build.refresh()
        self.changed.emit()
        self.said.emit(why or f"{name} is ready.", bool(why))

    addingTools = Property("QVariantList", lambda self: sorted(getattr(self, "_adding", set())), notify=changed)
    minimap = Property(bool, lambda self: self._minimap, notify=changed)
    resultsTitle = Property(str, lambda self: self._results_title, notify=searchDone)

    @Slot(int, result="QVariantMap")
    def marksOf(self, i: int) -> dict:
        if not 0 <= i < len(self._docs):
            return {}
        return {str(k): v for k, v in self._docs[i].marks.items()}

    @Slot(int, result="QVariantList")
    def problemsOf(self, i: int) -> list:
        return self._docs[i].problems if 0 <= i < len(self._docs) else []

    @Slot(int)
    def setSize(self, n: int) -> None:
        self._set_user("editor.fontSize", max(9, min(32, n)))
        self._keep()
        self.changed.emit()

    @Slot(bool)
    def setWrap(self, on: bool) -> None:
        self._set_user("editor.wordWrap", "on" if on else "off")
        self._keep()
        self.changed.emit()

    @Slot(int, "QVariantMap")
    def style(self, i: int, payload) -> None:
        """Called by tab i's editor: colour its text as its language, in the theme's colours."""
        payload = dict(payload)
        doc_obj, colours = payload.get("doc"), dict(payload.get("colours") or {})
        if not 0 <= i < len(self._docs) or doc_obj is None:
            return
        d = self._docs[i]
        old = getattr(d, "styler", None)
        if old is not None:
            old.setDocument(None)
        d.styler = CodeStyler(doc_obj.textDocument(), d.lang, colours)

    @Slot("QVariantMap")
    def styleCell(self, payload) -> None:
        """Colour a notebook cell's text (its own small document) as a language."""
        payload = dict(payload)
        doc_obj, colours, lang = payload.get("doc"), dict(payload.get("colours") or {}), str(payload.get("lang") or "Python")
        if doc_obj is None or lang not in LANGS:
            return
        td = doc_obj.textDocument()
        key = id(td)
        stylers = self.__dict__.setdefault("_cell_stylers", {})
        old = stylers.pop(key, None)
        if old is not None:
            try:
                old.setDocument(None)
            except RuntimeError:
                pass
        stylers[key] = CodeStyler(td, lang, colours)
        td.destroyed.connect(lambda *_a, k=key: stylers.pop(k, None))

    # ---------------------------------------------------------------- finding things
    def _files_of(self, root) -> list:
        found = list_files(root) if root else []
        return [f for f in found if not vsc.is_excluded(f, self._hide)] if self._hide else found

    def _active_files(self) -> list:
        """The working folder's files, each named from the folder."""
        if self._files_cache is None:
            self._files_cache = self._files_of(self._root)
        return self._files_cache

    def _all_files(self) -> list:
        """Every file quick open and search can name: the folder's, or in a workspace each folder's under its name
        ("engine/src/a.c")."""
        if len(self._roots) < 2:
            return self._active_files()
        if getattr(self, "_space_cache", None) is None or self._files_cache is None:
            self._space_cache = [f"{name}/{f}" for name, root in self._root_names().items() for f in (self._active_files() if root == self._root else self._files_of(root))]
        return self._space_cache

    # ---------------------------------------------------------------- a workspace: several folders open at once
    # One of them is the working folder: Git, Build, Run, the debugger, tasks and the project's settings are its.
    # It follows the file you are in. The Files list shows them all; quick open and search look in them all.
    def _root_names(self) -> dict:
        """{the name a folder goes by: the folder}; two folders of one name get their parent's name too."""
        out = {}
        for r in self._roots:
            name = r.name or str(r)
            if name in out or sum(1 for x in self._roots if x.name == r.name) > 1:
                name = f"{r.parent.name}-{r.name}" if r.parent.name else name
            while name in out:
                name += "-"
            out[name] = r
        return out

    def _abs(self, rel: str) -> Path:
        """A file as quick open and search name it, as a full path."""
        if len(self._roots) > 1:
            head, _, rest = rel.partition("/")
            root = self._root_names().get(head)
            if root is not None:
                return root / rest
        return self._root / rel

    def _name_of(self, path: str) -> str:
        """A full path as quick open and search name it."""
        if len(self._roots) > 1:
            for name, root in self._root_names().items():
                if path.startswith(str(root) + os.sep):
                    return f"{name}/{os.path.relpath(path, root)}"
        return os.path.relpath(path, self._root) if self._root else path

    def _follow(self, path: str) -> None:
        """Make the workspace folder a file lives in the working folder (the deepest one, if they nest)."""
        if len(self._roots) > 1:
            inside = [r for r in self._roots if path.startswith(str(r) + os.sep)]
            if inside:
                self._set_active(max(inside, key=lambda r: len(str(r))))

    def _set_active(self, root: Path) -> None:
        if root == self._root or root not in self._roots:
            return
        if self._dbg.active or self._build.running:                # (what is running belongs to the folder it was started in)
            return
        self._root = root
        self._files_cache = None
        self._read_project()
        self._box_found()
        self._build_tree()
        self.refreshGit()
        self._build.set_root(root)
        self.changed.emit()

    def _get_folders(self) -> list:
        names = self._root_names()
        return [{"path": str(r), "name": n, "active": r == self._root} for n, r in names.items()] if len(self._roots) > 1 else []
    folders = Property("QVariantList", _get_folders, notify=changed)
    workspaceFile = Property(str, lambda self: self._space_file, notify=changed)

    @Slot(str, result=str)
    def addFolder(self, path: str) -> str:
        """Add a folder beside the open one: the two (or more) are a workspace. "" when added, else why not."""
        if not path.strip():
            return ""
        folder = Path(path.replace("file://", "").strip()).expanduser()
        try:
            folder = folder.resolve()
        except (OSError, RuntimeError):
            return "That folder isn't there."
        if not folder.is_dir():
            return "That folder isn't there."
        if not self._root:
            self.openFolder(str(folder))
            return ""
        if self._remote_of()[0] or self._remote_of(folder)[0]:
            return "A folder on another computer is opened on its own."
        if folder in self._roots:
            return "That folder is already in the workspace."
        if len(self._roots) >= 16:
            return "A workspace holds up to 16 folders."
        self._roots = (self._roots or [self._root]) + [folder]
        self._space_cache = None
        self._build_tree()
        self._keep()
        self.changed.emit()
        return ""

    @Slot(str, result=str)
    def removeFolder(self, path: str) -> str:
        """Take a folder out of the workspace (its files stay where they are). "" when done, else why not."""
        folder = next((r for r in self._roots if str(r) == path), None)
        if folder is None or len(self._roots) < 2:
            return "That folder isn't one of the workspace's."
        others = [r for r in self._roots if r != folder]
        own = lambda d: d.path.startswith(str(folder) + os.sep) and not any(d.path.startswith(str(o) + os.sep) and len(str(o)) > len(str(folder)) for o in others)      # noqa: E731
        if any(d.dirty for d in self._docs if own(d)):
            return "Save or close its changed files first."
        if (self._dbg.active or self._build.running) and folder == self._root:
            return "Something is running in that folder. Stop it first."
        was_first = folder == self._roots[0]
        for i in reversed([i for i, d in enumerate(self._docs) if own(d)]):
            self.close(i, True)
        if was_first and isinstance(self._state.get("spaces"), dict):
            self._state["spaces"].pop(str(folder), None)
        self._roots = others
        self._shut_roots.discard(path)
        self._space_cache = None
        if folder == self._root:
            self._set_active(others[0])
        self._build_tree()
        self._keep()
        self.changed.emit()
        return ""

    @Slot(str, result=str)
    def saveWorkspace(self, path: str) -> str:
        """Write the workspace as a .code-workspace file (VS Code's own), folders named from where the file is when
        they are beside or under it. "" when written, else why not."""
        if len(self._roots) < 2:
            return "One folder isn't a workspace: add another first."
        target = Path(path.replace("file://", "").strip()).expanduser()
        if not path.strip():
            return ""
        if target.is_dir():
            target = target / (self._roots[0].name + ".code-workspace")
        if target.suffix != ".code-workspace":
            target = target.with_name(target.name + ".code-workspace")
        rows = []
        for r in self._roots:
            try:
                rel = os.path.relpath(r, target.parent)
            except ValueError:
                rel = str(r)
            rows.append({"path": rel if not rel.startswith(".." + os.sep + "..") else str(r)})
        old = vsc.load_jsonc(target) if target.is_file() else None
        data = dict(old if isinstance(old, dict) else {}, folders=rows)
        data.setdefault("settings", dict(self._space) if self._space else {})
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        except OSError as err:
            return f"Couldn't write {target.name}: {err.strerror or err}"
        self._space_file = str(target)
        self.changed.emit()
        return ""

    # ---------------------------------------------------------------- another computer, over SSH
    def _remote_of(self, root=None) -> tuple:
        """(the remote, its mount) when this folder is one mounted from another computer, else (None, None)."""
        root = root if root is not None else self._root
        known = self._state.get("remotes") if isinstance(self._state.get("remotes"), dict) else {}
        if root:
            for mount, remote in known.items():
                if isinstance(remote, dict) and (str(root) == mount or str(root).startswith(mount + "/")):
                    return remote, mount
        return None, None

    def _get_remote(self) -> dict:
        remote, mount = self._remote_of()
        return dict(remote, mount=mount, connected=hr.is_mounted(mount)) if remote else {}
    remote = Property("QVariantMap", _get_remote, notify=changed)

    def _get_remote_hosts(self) -> list:
        known = self._state.get("remotes") if isinstance(self._state.get("remotes"), dict) else {}
        recent = [r["label"] for r in known.values() if isinstance(r, dict) and r.get("label")]
        return recent[-8:][::-1] + [h for h in hr.config_hosts() if h not in recent]
    remoteHosts = Property("QVariantList", _get_remote_hosts, notify=changed)

    @Slot(str, result=str)
    def remoteConnect(self, target: str) -> str:
        """Open a folder on another computer. Returns "" when it's under way (or already open), else why not. The
        mount line is typed into the terminal, where ssh asks for whatever it needs; Code opens the folder when it
        appears."""
        try:
            remote = hr.parse_target(target)
        except ValueError as err:
            return str(err)
        missing = hr.tools_missing()
        if missing:
            return f"This needs {' and '.join(missing)} (the {'openssh-client and sshfs' if len(missing) > 1 else 'sshfs' if missing == ['sshfs'] else 'openssh-client'} package)."
        if any(d.dirty for d in self._docs):
            return "Save or close your changed files first."
        mount = hr.mount_point(remote)
        self._state.setdefault("remotes", {})[str(mount)] = remote
        self._keep()
        if hr.is_mounted(mount):
            self.openFolder(str(mount))
            return ""
        if self._demo:
            self.said.emit(f"Would connect to {remote['label']}.", False)
            return ""
        term = self._get_term()
        if term is None:
            return "The terminal couldn't be opened, and that is where the connection is made."
        getattr(term, "type_when_ready", term._send)((hr.mount_command(remote, mount) + "\r").encode())
        self._remote_wait, self._remote_tries = str(mount), 0
        self._remote_poll.start()
        self.said.emit(f"Connecting to {remote['spec']}… Answer in the terminal if it asks for a password.", False)
        return ""

    def _remote_check(self) -> None:
        mount = getattr(self, "_remote_wait", "")
        self._remote_tries = getattr(self, "_remote_tries", 0) + 1
        if mount and hr.is_mounted(mount):
            self._remote_poll.stop()
            self._remote_wait = ""
            self.openFolder(mount)
            self.said.emit("Connected. Run and Build happen on that computer; the terminal here is still this one.", False)
        elif not mount or self._remote_tries > 180:
            self._remote_poll.stop()
            if mount:
                self.said.emit("The connection wasn't made. The terminal shows what ssh said.", True)

    @Slot()
    def remoteDisconnect(self) -> None:
        remote, mount = self._remote_of()
        if not remote:
            return
        if any(d.dirty for d in self._docs):
            self.said.emit("Save or close your changed files first.", True)
            return
        self.closeFolder()
        try:
            done = subprocess.run(hr.unmount_command(mount), capture_output=True, text=True, timeout=20)
            self.said.emit(f"Disconnected from {remote['spec']}." if done.returncode == 0 else f"Couldn't disconnect: {(done.stderr or '').strip()[:160]}", done.returncode != 0)
        except (OSError, subprocess.SubprocessError) as err:
            self.said.emit(f"Couldn't disconnect: {err}", True)

    @Slot()
    def remoteShell(self) -> None:
        """A shell on the other computer, in the project's folder, in the terminal below."""
        remote, _ = self._remote_of()
        term = self._get_term() if remote else None
        if term is not None:
            getattr(term, "type_when_ready", term._send)((hr.shell_command(remote) + "\r").encode())

    # ---------------------------------------------------------------- notebooks (.ipynb): cells over the file's own text
    # The file's text stays what is saved, undone-to and compared; the cells are a way to see and change it. A change
    # to a cell is kept in the cells first and written into the text a moment later (and always before a save).
    nbChanged = Signal(int)

    def _nb(self, i: int) -> tuple:
        """(the document, its cells) for a notebook tab; the cells are None when the text isn't a notebook."""
        if not 0 <= i < len(self._docs) or not self._docs[i].path.lower().endswith(".ipynb"):
            return None, None
        d = self._docs[i]
        if getattr(d, "nb_stale", False) or (getattr(d, "nb", None) is not None and getattr(d, "nb_text", None) == d.text):
            return d, d.nb
        try:
            d.nb, d.nb_why = nbk.parse(d.text), ""
        except ValueError as err:
            d.nb, d.nb_why = None, str(err)
        d.nb_text, d.nb_stale = d.text, False
        return d, d.nb

    def _nb_flush(self, d) -> None:
        """Write the cells into the document's text, if they have changed since."""
        if getattr(d, "nb_stale", False) and getattr(d, "nb", None) is not None and d in self._docs:
            d.nb_stale = False
            text = nbk.dump(d.nb)
            d.nb_text = text
            self.edit(self._docs.index(d), text)
            d.nb_text = d.text

    def _nb_flush_all(self) -> None:
        for d in list(self._docs):
            self._nb_flush(d)

    def _nb_touch(self, d, tell: bool = True) -> None:
        d.nb_stale = True
        self._nb_later.start()
        if tell:
            self._nb_dirty_tabs.add(d.path)
            self._nb_tell.start()

    def _nb_told(self) -> None:
        paths, self._nb_dirty_tabs = self._nb_dirty_tabs, set()
        for i, d in enumerate(self._docs):
            if d.path in paths:
                self.nbChanged.emit(i)

    def _nb_end(self, path: str) -> None:
        k = self._kernels.pop(path, None)
        if k is not None:
            k.stop()
            k.deleteLater()

    def _nb_quit(self) -> None:
        self._nb_flush_all()
        for path in list(self._kernels):
            self._nb_end(path)

    def _nb_cell(self, d, cell_id: str):
        return next((c for c in d.nb["cells"] if c["id"] == cell_id), None) if getattr(d, "nb", None) else None

    @Slot(int, result="QVariantMap")
    def notebook(self, i: int) -> dict:
        """What the window draws for a notebook tab."""
        d, nb = self._nb(i)
        if d is None:
            return {"ok": False, "why": "", "cells": []}
        if nb is None:
            return {"ok": False, "why": d.nb_why, "cells": []}
        k = self._kernels.get(d.path)
        running, queued = (k.running, k.queued) if k else ("", [])
        return {"ok": True, "why": "", "busy": bool(running), "alive": bool(k and k.alive), "python": (k.about.get("python", "") if k else ""),
                "cells": [{"id": c["id"], "kind": c["kind"], "source": c["source"], "count": c["count"] or 0, "outputs": nbk.shown(c["outputs"]),
                           "state": "running" if c["id"] == running else "queued" if c["id"] in queued else ""} for c in nb["cells"]]}

    @Slot(int)
    def nbFlush(self, i: int) -> None:
        if 0 <= i < len(self._docs):
            self._nb_flush(self._docs[i])

    @Slot(int, str, str)
    def nbSetSource(self, i: int, cell_id: str, text: str) -> None:
        d, nb = self._nb(i)
        c = self._nb_cell(d, cell_id) if nb else None
        if c is not None and c["source"] != text:
            c["source"] = text.replace("\r\n", "\n").replace("\r", "\n")
            self._nb_touch(d, tell=False)                          # (the window already shows what was typed)

    @Slot(int, int, str, result=str)
    def nbAdd(self, i: int, at: int, kind: str) -> str:
        """A new cell at a place (past the end: last). Returns its id."""
        d, nb = self._nb(i)
        if not nb or d.read_only:
            return ""
        c = nbk.new_cell(kind)
        nb["cells"].insert(max(0, min(at, len(nb["cells"]))), c)
        self._nb_touch(d)
        return c["id"]

    @Slot(int, str)
    def nbRemove(self, i: int, cell_id: str) -> None:
        d, nb = self._nb(i)
        c = self._nb_cell(d, cell_id) if nb else None
        if c is not None and not d.read_only:
            nb["cells"].remove(c)
            if not nb["cells"]:
                nb["cells"].append(nbk.new_cell())
            self._nb_touch(d)

    @Slot(int, str, int)
    def nbMove(self, i: int, cell_id: str, by: int) -> None:
        d, nb = self._nb(i)
        c = self._nb_cell(d, cell_id) if nb else None
        if c is not None and not d.read_only:
            at = nb["cells"].index(c)
            to = max(0, min(len(nb["cells"]) - 1, at + by))
            if to != at:
                nb["cells"].insert(to, nb["cells"].pop(at))
                self._nb_touch(d)

    @Slot(int, str, str)
    def nbKind(self, i: int, cell_id: str, kind: str) -> None:
        d, nb = self._nb(i)
        c = self._nb_cell(d, cell_id) if nb else None
        if c is not None and kind in nbk.KINDS and c["kind"] != kind and not d.read_only:
            c.update(kind=kind, outputs=[], count=None)
            self._nb_touch(d)

    def _nb_kernel(self, d):
        k = self._kernels.get(d.path)
        if k is None:
            folder = str(Path(d.path).parent) if not d.path.startswith("untitled:") else str(self._root or Path.home())
            k = self._kernels[d.path] = nbk.Kernel(folder, parent=self)
            k.said.connect(lambda msg, path=d.path: self._nb_said(path, msg))
            k.idle.connect(lambda path=d.path: self._nb_dirty_tabs.add(path) or self._nb_tell.start())
            k.gone.connect(lambda why, path=d.path: (self._nb_dirty_tabs.add(path), self._nb_tell.start(), self.said.emit(why, True) if why and "couldn't be started" in why else None))
        return k

    def _nb_said(self, path: str, msg: dict) -> None:
        d = next((x for x in self._docs if x.path == path), None)
        c = self._nb_cell(d, str(msg.get("id", ""))) if d is not None else None
        if c is None:
            return
        if msg.get("type") == "done":
            if msg.get("count"):
                c["count"] = msg["count"]
        else:
            nbk.add_output(c, msg)
        self._nb_touch(d)

    @Slot(int, str)
    def nbRun(self, i: int, cell_id: str) -> None:
        """Run a cell: its old output goes, and what it prints, its last line's value and its figures come under it."""
        d, nb = self._nb(i)
        c = self._nb_cell(d, cell_id) if nb else None
        if c is None or c["kind"] != "code" or self._demo:
            return
        k = self._nb_kernel(d)
        if c["id"] == k.running or c["id"] in k.queued:
            return
        c["outputs"], c["count"] = [], None
        why = nbk.not_python(c["source"])
        if why:
            nbk.add_output(c, {"type": "error", "ename": "NotPython", "evalue": why, "traceback": [why]})
        elif c["source"].strip():
            k.run(c["id"], c["source"])
        self._nb_touch(d)

    @Slot(int)
    def nbRunAll(self, i: int) -> None:
        d, nb = self._nb(i)
        for c in (nb["cells"] if nb else []):
            if c["kind"] == "code":
                self.nbRun(i, c["id"])

    @Slot(int)
    def nbInterrupt(self, i: int) -> None:
        d, _nb = self._nb(i)
        if d is not None and d.path in self._kernels:
            self._kernels[d.path].interrupt()
            self._nb_touch(d)

    @Slot(int)
    def nbRestart(self, i: int) -> None:
        """End the notebook's Python: every name is forgotten; the outputs stay until cells are run again."""
        d, _nb = self._nb(i)
        if d is not None:
            self._nb_end(d.path)
            self._nb_dirty_tabs.add(d.path)
            self._nb_tell.start()

    @Slot(int)
    def nbClear(self, i: int) -> None:
        d, nb = self._nb(i)
        if nb and not d.read_only:
            for c in nb["cells"]:
                c["outputs"], c["count"] = [], None
            self._nb_touch(d)

    # ---------------------------------------------------------------- a dev container (.devcontainer/devcontainer.json)
    def _place(self) -> tuple:
        """(the door, what is behind it, the folder here) when the project runs somewhere else: huginn_remote and a
        computer reached over SSH, or huginn_container and a started dev container. Else (None, None, None)."""
        remote, mount = self._remote_of()
        if remote:
            return hr, remote, mount
        if self._box and self._root and self._box.get("root") == str(self._root):
            return hc, self._box, str(self._root)
        return None, None, None

    def _place_paths(self) -> tuple:
        """Two functions for the debugger: a file's path here as it is there, and back."""
        door, what, mount = self._place()
        if not what:
            return None
        home = ""
        if door is hr and not hr.remote_root(what).startswith("/"):  # the folder there is named from the home folder: ask once where that is
            key = what["spec"]
            if key not in self._home_there:
                code, out = hr.probe(what, "pwd")
                self._home_there[key] = out.splitlines()[-1] if code == 0 and out.startswith("/") else ""
            home = self._home_there[key]

        def there(path: str) -> str:
            p = door.to_remote(what, mount, path)
            if home and p != path and not p.startswith("/"):
                return home if p == "." else f"{home}/{p}"
            return p

        def here(path: str) -> str:
            if home and (path == home or path.startswith(home + "/")):
                return door.to_local(what, mount, path[len(home) + 1:]) if path != home else mount
            return door.to_local(what, mount, path)
        return there, here

    def _get_container(self) -> dict:
        root = self._root
        path = hc.find_config(root) if root and not self._remote_of()[0] else None
        if path is None:
            return {"has": False}
        try:
            stamp = (str(path), path.stat().st_mtime_ns)
        except OSError:
            return {"has": False}
        if getattr(self, "_box_seen", (None,))[0] != stamp:              # (read again only when the file changes: this is asked for often)
            seen = {"has": True, "file": str(path), "engine": hc.engine(), "title": "", "asks": [], "problem": ""}
            try:
                cfg = hc.read(root)
                seen.update(title=cfg["title"], asks=hc.asks(cfg), workspace=cfg["workspace"])
            except ValueError as err:
                seen["problem"] = str(err)
            if not seen["engine"] and not seen["problem"]:
                seen["problem"] = "Containers need Docker or Podman. Podman is the simple one (the podman package, in App Store): it needs no background service."
            self._box_seen = (stamp, seen)
        return dict(self._box_seen[1], running=bool(self._box and self._box.get("root") == str(root)), starting=self._box_poll.isActive())
    container = Property("QVariantMap", _get_container, notify=changed)

    def _box_found(self) -> None:
        """When a folder opens: is its container already running (started earlier, or by another program)?"""
        self._box = None
        root, eng = self._root, hc.engine()
        if not root or not eng or self._demo or hc.find_config(root) is None or self._remote_of()[0]:
            return
        try:
            cfg = hc.read(root)
        except ValueError:
            return
        box = hc.where(eng, cfg)
        if hc.state(box) == "running":
            self._box = box

    @Slot(result=str)
    def containerOpen(self) -> str:
        """Start the project's container (building its image first when it has a Dockerfile) and work inside it.
        The lines are typed into the terminal, where the engine shows what it is doing. "" when under way."""
        root = self._root
        if not root:
            return "Open the project's folder first."
        try:
            cfg = hc.read(root)
        except ValueError as err:
            return str(err)
        eng = hc.engine()
        if not eng:
            return "Containers need Docker or Podman (the podman package is the simple one)."
        if self._demo:
            self.said.emit(f"Would start the container “{cfg['title']}” with {eng}.", False)
            return ""
        box = hc.where(eng, cfg)
        now = hc.state(box)
        if now == "running":
            self._box = box
            self.changed.emit()
            return ""
        term = self._get_term()
        if term is None:
            return "The terminal couldn't be opened, and that is where the container is started."
        send = getattr(term, "type_when_ready", term._send)
        status = hc.status_file(root)
        try:
            status.parent.mkdir(parents=True, exist_ok=True)
            status.unlink(missing_ok=True)
        except OSError:
            status = None
        for line in hc.start_lines(eng, cfg, exists=now == "stopped", status=status):
            send((line + "\r").encode())
        self._box_cfg, self._box_tries, self._box_status = box, 0, status
        self._box_poll.start()
        self.changed.emit()
        return ""

    def _box_check(self) -> None:
        box = self._box_cfg
        self._box_tries += 1
        ended = None
        try:
            status = getattr(self, "_box_status", None)
            ended = int(status.read_text().strip() or "1") if status is not None and status.is_file() else None
        except (OSError, ValueError):
            ended = 1
        if box and ended not in (None, 0):                           # the build or the start failed: say so now, not after a long wait
            self._box_poll.stop()
            self._box_cfg = None
            self.changed.emit()
            self.said.emit("The container didn't start. The terminal shows what the engine said.", True)
            return
        if box and ended is None and self._box_tries % 4:           # (still building: the engine is asked only now and then)
            return
        if box and hc.state(box) == "running":
            self._box_poll.stop()
            self._box, self._box_cfg = box, None
            self.changed.emit()
            self.said.emit(f"Working in the container “{box['label']}”. Run, Build and the debugger happen inside it; the terminal here is still this computer (Container: Open a Shell for one inside).", False)
        elif not box or self._box_tries > 1200:                      # (a first image can take a long while to fetch)
            self._box_poll.stop()
            self._box_cfg = None
            self.changed.emit()

    @Slot(bool)
    def containerStop(self, remove: bool = False) -> None:
        """Stop the container (its files are the project's own and stay). With `remove`, it is thrown away too, so
        the next start builds it afresh."""
        box = self._box or self._box_cfg
        self._box_poll.stop()
        if box is None and self._root and hc.engine():
            try:
                box = hc.where(hc.engine(), hc.read(self._root))
            except ValueError:
                box = None
        self._box = self._box_cfg = None
        self.changed.emit()
        if box is None or self._demo:
            return
        if self._dbg.active:
            self._dbg.stop()
        proc = QProcess(self)
        proc.finished.connect(lambda code, _s, b=box, p=proc: (self.said.emit((f"The container “{b['label']}” was removed." if remove else f"The container “{b['label']}” was stopped.") if code == 0
                                                                                     else "The engine couldn't stop the container.", code != 0), p.deleteLater()))
        proc.errorOccurred.connect(lambda _e, p=proc: p.deleteLater())
        cmd = hc.stop_command(box, remove)
        proc.start(cmd[0], cmd[1:])

    @Slot()
    def containerShell(self) -> None:
        """A shell inside the container, in the terminal below."""
        term = self._get_term() if self._box else None
        if term is not None:
            getattr(term, "type_when_ready", term._send)((hc.shell_command(self._box) + "\r").encode())

    # ---------------------------------------------------------------- what Visual Studio Code left in the project
    def _read_project(self) -> None:
        """.vscode/settings.json (a .code-workspace file's settings under it), the project's snippets and its debug
        configurations. Read when the folder opens and again when one of those files is saved."""
        root = self._root
        self._proj = dict(getattr(self, "_space", None) or {}, **vsc.settings(root)) if root else {}
        self._apply_settings()
        more.EXTRA_SNIPPETS.clear()
        for layer in (self._ext_data()["snippets"], self._state.get("snippets") if isinstance(self._state.get("snippets"), dict) else {}, vsc.project_snippets(root, LANGS) if root else {}):
            for lang, rows in layer.items():
                if isinstance(rows, dict):
                    more.EXTRA_SNIPPETS.setdefault(lang, {}).update({k: tuple(v) for k, v in rows.items() if isinstance(v, (list, tuple)) and len(v) == 2})
        self._launch_list = vsc.launches(root, self._vs_vars()) if root else []
        self._files_cache = None

    def _vs_vars(self) -> dict:
        d = self._docs[self._at] if 0 <= self._at < len(self._docs) else None
        return vsc.variables(self._root or Path.home(), d.path if d else "", 0)

    def _get_launches(self) -> list:
        chosen = (self._state.get("launch") or {}).get(str(self._root), "") if self._root else ""
        first = next((c["name"] for c in self._launch_list if c["name"] == chosen and c["kind"]), "") or next((c["name"] for c in self._launch_list if c["kind"]), "")
        return [{"name": c["name"], "ok": bool(c["kind"]), "why": c["why"], "chosen": c["name"] == first} for c in self._launch_list]
    launches = Property("QVariantList", _get_launches, notify=changed)

    @Slot(str)
    def startLaunch(self, name: str) -> None:
        """Debug with one of the project's .vscode/launch.json configurations (and make it the one F5 uses)."""
        if self._dbg.active or not self._root:
            return
        self._launch_list = vsc.launches(self._root, self._vs_vars())      # ${file} is the file in front now
        cfg = next((c for c in self._launch_list if c["name"] == name), None)
        if cfg is None:
            return
        if not cfg["kind"]:
            self.said.emit(f"“{name}” can't be started here: {cfg['why']}.", True)
            return
        self._state.setdefault("launch", {})[str(self._root)] = name
        self._keep()
        self.saveAll()
        before = cfg["before"] and next((t for t in self._build.tasks if t["name"] == cfg["before"] and t["command"]), None)
        if before and not self._demo:
            self._after_build = (before["id"], cfg)                        # (its preLaunchTask first; debugging follows if it works)
            self._build.run(before["id"])
            self.said.emit(f"Running “{before['name']}” first…", False)
            return
        self._launch(cfg)

    # ---------------------------------------------------------------- attaching to a running program
    askAttach = Signal(str)                              # the window shows the list of running programs (for this launch.json entry, or "")

    @Slot(str, result="QVariantList")
    def runningPrograms(self, like: str) -> list:
        """The user's running programs, the ones matching what was typed (a name, part of the command, a number)."""
        like = like.strip().lower()
        rows = hd.processes()
        return [r for r in rows if not like or like in r["name"].lower() or like in r["command"].lower() or like == str(r["pid"])][:200]

    attachNote = Property(str, lambda self: hd.ptrace_note(), constant=True)

    @Slot(int, str)
    def attachTo(self, pid: int, config: str = "") -> None:
        """Join a running program with the debugger: Python programs with debugpy, the rest with GDB. With a
        launch.json entry's name, that entry's settings (its path mappings, its program) are used."""
        if self._dbg.active:
            return
        row = next((r for r in hd.processes(4000) if r["pid"] == pid), None)
        if row is None:
            self.said.emit("That program isn't running any more.", True)
            return
        cfg = next((c for c in self._launch_list if c["name"] == config), None) if config else None
        kind = {"python-attach": "python", "gdb-attach": "native"}.get(cfg["kind"], row["kind"]) if cfg else row["kind"]
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            exe = ""
        try:
            argv, args, name = hd.attach_for(kind, pid=pid, program=(cfg["launch"]["program"] if cfg else "") or (exe if kind == "native" else ""),
                                             mappings=cfg["launch"]["mappings"] if cfg else ())
        except ValueError as err:
            self.said.emit(str(err), True)
            return
        if self._demo:
            self.said.emit(f"Would attach to {row['name']} ({pid}) with {name}.", False)
            return
        self._dbg.start(argv, args, name, str(self._root or Path.home()), "attach", f"{row['name']} ({pid})")

    def _attach(self, cfg: dict) -> None:
        """A launch.json entry that joins a running program."""
        a = cfg["launch"]
        if a["pick"]:
            self.askAttach.emit(cfg["name"])
            return
        if a["pid"]:
            self.attachTo(a["pid"], cfg["name"])
            return
        try:
            argv, args, name = hd.attach_for("python" if cfg["kind"] == "python-attach" else "native", host=a["host"], port=a["port"], program=a["program"], mappings=a["mappings"])
        except ValueError as err:
            self.said.emit(str(err), True)
            return
        if self._demo:
            self.said.emit(f"Would attach to {a['host'] or '127.0.0.1'}:{a['port']} with {name}.", False)
            return
        self._dbg.start(argv, args, name, str(self._root or Path.home()), "attach", f"{a['host'] or '127.0.0.1'}:{a['port']}")

    def _launch(self, cfg: dict) -> None:
        if cfg["kind"].endswith("-attach"):
            self._attach(cfg)
            return
        launch, root = dict(cfg["launch"]), self._root or Path.home()
        try:
            if cfg["kind"] == "python":
                python = launch.pop("python", "python3")
                if not hd.has_debugpy(python):
                    raise ValueError("Debugging Python needs debugpy (the python3-debugpy package).")
                argv, name = [python, "-m", "debugpy.adapter"], "debugpy"
            else:
                if not hd.gdb_has_dap():
                    raise ValueError("Debugging compiled programs needs GDB 14 or later (the gdb package).")
                if not Path(launch["program"]).is_file():
                    raise ValueError(f"The program {launch['program']} isn't there. Build first.")
                argv, name = ["gdb", "-q", "-i", "dap"], "GDB"
        except ValueError as err:
            self.said.emit(str(err), True)
            return
        if self._demo:
            self.said.emit(f"Would debug “{cfg['name']}” with {name}.", False)
            return
        self._debug_start(argv, launch, name, str(launch.get("cwd") or root))

    @Slot(str, result="QVariantList")
    def quickOpen(self, query: str) -> list:
        files = self._all_files()
        q = query.strip().replace(" ", "")
        if not q:
            recent = [self._name_of(d.path) for d in self._docs if self._root and d.path.startswith(tuple(str(r) for r in (self._roots or [self._root])))]
            rest = [f for f in files if f not in recent]
            return [{"rel": f, "name": Path(f).name, "where": str(Path(f).parent) if str(Path(f).parent) != "." else ""} for f in (recent + rest)[:60]]
        scored = []
        for f in files:
            s = fuzzy(q, f)
            if s >= 0:
                scored.append((s, f))
        scored.sort(key=lambda x: (-x[0], len(x[1])))
        return [{"rel": f, "name": Path(f).name, "where": str(Path(f).parent) if str(Path(f).parent) != "." else ""} for _, f in scored[:60]]

    @Slot(str, int, int)
    def openRel(self, rel: str, line: int = -1, col: int = 0) -> None:
        if Path(rel).is_absolute():
            self.openFile(rel, True, line, col)
        elif self._root:
            self.openFile(str(self._abs(rel)), True, line, col)

    @Slot(str, bool, bool, bool)
    def search(self, query: str, case: bool, regex: bool, word: bool) -> None:
        self._query = query
        self._results_title = ""
        if not self._root or not query.strip():
            self._results, self._searching = [], False
            self.searchDone.emit()
            return
        if regex:
            try:
                re.compile(query)
            except re.error:
                self._results, self._searching = [{"path": "", "line": -1, "col": 0, "length": 0, "text": "That pattern isn't valid."}], False
                self.searchDone.emit()
                return
        self._searching = True
        self.searchDone.emit()
        root, asked = self._root, query
        tops = list(self._root_names().items()) if len(self._roots) > 1 else []

        def go():
            if tops:                                               # a workspace: every folder, each file named under its folder
                hits = []
                for name, top in tops:
                    found = search_files(top, asked, case, regex, word)
                    hits += [dict(h, path=f"{name}/{h['path']}") for h in found if not (self._hide and vsc.is_excluded(h["path"], self._hide))]
            else:
                hits = search_files(root, asked, case, regex, word)
                if self._hide:
                    hits = [h for h in hits if not vsc.is_excluded(h["path"], self._hide)]

            def done():
                if asked != self._query:
                    return
                self._results, self._searching = hits, False
                self.searchDone.emit()
            self._back.emit(done)
        threading.Thread(target=go, daemon=True).start()

    @Slot(str, str, bool, bool, bool, result=int)
    def replaceAll(self, query: str, replacement: str, case: bool, regex: bool, word: bool) -> int:
        """Replace in every file the last search found. Open files change in their tab (and can be undone there);
        files that aren't open are saved straight away. Returns how many places changed."""
        if not self._root or not query:
            return 0
        flags = 0 if case else re.I
        try:
            pat = re.compile((r"\b" if word else "") + (query if regex else re.escape(query)) + (r"\b" if word else ""), flags)
        except re.error:
            return 0
        count, done = 0, set()
        for rel in sorted({h["path"] for h in self._results if h.get("path")}):
            path = str(self._abs(rel).resolve())
            if path in done:                                  # (the same file reached twice, through a link)
                continue
            done.add(path)
            open_at = next((i for i, d in enumerate(self._docs) if d.path == path), -1)
            try:
                d = self._docs[open_at] if open_at >= 0 else Doc(path)
                if open_at < 0:
                    d.load()                                  # in its own encoding and line endings, whatever they are
            except OSError:
                continue
            if d.binary or d.read_only:
                continue
            try:
                new, n = pat.subn(replacement if regex else replacement.replace("\\", "\\\\"), d.text)
            except (re.error, IndexError):
                self.said.emit("That replacement names a group the pattern doesn't have.", True)
                return count
            if not n:
                continue
            count += n
            if open_at >= 0:
                d.text = new
                self.textLoaded.emit(open_at)
            else:
                try:
                    d.text = new
                    d.save(True)
                except OSError:
                    continue
        self.changed.emit()
        self.search(query, case, regex, word)
        return count

    @Slot(int, result="QVariantList")
    def symbols(self, i: int) -> list:
        """Functions, classes and headings in tab i, found by their shape (the language server's list when it has one)."""
        if not 0 <= i < len(self._docs):
            return []
        d, out = self._docs[i], []
        patterns = {"Python": r"^\s*(?:async\s+)?(def|class)\s+(\w+)", "JavaScript": r"^\s*(?:export\s+)?(?:async\s+)?(function|class)\s+(\w+)",
                    "TypeScript": r"^\s*(?:export\s+)?(?:async\s+)?(function|class|interface|type|enum)\s+(\w+)", "Go": r"^(func|type)\s+(?:\([^)]*\)\s*)?(\w+)",
                    "Rust": r"^\s*(?:pub\s+)?(fn|struct|enum|trait|impl|mod)\s+(\w+)", "C": r"^(\w[\w\s\*]*?)\s+\**(\w+)\s*\([^;]*$", "C++": r"^(\w[\w\s\*:<>]*?)\s+\**([\w:~]+)\s*\([^;]*$",
                    "Shell": r"^\s*(function\s+)?(\w+)\s*\(\)", "Markdown": r"^(#{1,6})\s+(.+)", "QML": r"^\s*(function|property\s+\w+|signal)\s+(\w+)", "Java": r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(class|interface|enum|void|\w+)\s+(\w+)\s*[({]"}
        pat = patterns.get(d.lang)
        if not pat:
            return []
        for n, line in enumerate(d.text.split("\n")):
            m = re.match(pat, line)
            if m:
                kind = m.group(1).strip()
                out.append({"name": m.group(2).strip(), "kind": "heading" if d.lang == "Markdown" else kind.split()[0], "line": n, "depth": (len(line) - len(line.lstrip())) // 4 if d.lang != "Markdown" else len(kind) - 1})
        return out[:500]

    # ---------------------------------------------------------------- Git
    @Slot()
    def refreshGit(self) -> None:
        if self._demo:
            return
        if not self._root or not shutil.which("git"):
            self._git, self._branch, self._changes = False, "", []
            return
        try:
            out = git(self._root, "status", "--porcelain=v1", "-b", "-z", "--untracked-files=all", timeout=15)
        except (OSError, subprocess.SubprocessError):
            return
        if out.returncode != 0:
            self._git, self._branch, self._changes = False, "", []
            self.changed.emit()
            return
        branch, changes = parse_status(out.stdout)
        top = git(self._root, "rev-parse", "--show-toplevel", timeout=5).stdout.strip()
        prefix = os.path.relpath(self._root, top) if top else "."
        if prefix != ".":                                     # the project is a folder inside a bigger repository
            changes = [dict(c, path=c["path"][len(prefix) + 1:]) for c in changes if c["path"].startswith(prefix + "/")]
        self._git, self._branch, self._changes = True, branch.split("...")[0].replace("No commits yet on ", ""), changes
        self._ahead = branch
        self._build_tree()
        self.changed.emit()

    def _marks(self, d: Doc) -> None:
        """The gutter's marks for d: what differs from the last commit. From the committed text when Git has it (so they
        follow your typing), from `git diff` for a very long file, all "add" for a file Git doesn't know yet."""
        d.marks, d.head, d.found = {}, None, (None, [])
        if self._demo or not self._root or not shutil.which("git") or not d.path.startswith(str(self._root)) or d.binary:
            return
        folder, name = Path(d.path).parent, Path(d.path).name
        try:
            if not d.wide:
                was = subprocess.run(["git", "-C", str(folder), "show", "HEAD:./" + name], capture_output=True, timeout=10,
                                     env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0"))
                if was.returncode == 0 and len(was.stdout) <= TEXT_LIMIT and b"\0" not in was.stdout[:8192]:
                    raw = was.stdout[3:] if was.stdout.startswith(b"\xef\xbb\xbf") else was.stdout
                    d.head = raw.decode(d.encoding, "replace").replace("\r\n", "\n").replace("\r", "\n")
            if d.head is not None and max(d.head.count("\n"), d.text.count("\n")) < more.CHANGES_LIMIT:
                d.marks = more.change_marks(self._found(d), d.text.count("\n") + 1)
                return
            out = git(folder, "diff", "-U0", "--no-color", "--no-ext-diff", "HEAD", "--", name, timeout=10)
            if out.returncode == 0:
                d.marks = parse_hunks(out.stdout)
            tracked = git(folder, "ls-files", "--error-unmatch", "--", name, timeout=5)
            if tracked.returncode != 0 and git(folder, "rev-parse", timeout=5).returncode == 0:
                d.marks = {n: "add" for n in range(d.text.count("\n") + 1)}
        except (OSError, subprocess.SubprocessError):
            pass

    def _found(self, d: Doc) -> list:
        """What differs between d and its committed text (worked out once per text)."""
        if d.head is None:
            return []
        if d.found[0] is not d.text:
            d.found = (d.text, more.changes(d.head, d.text))
        return d.found[1]

    def _live_marks(self) -> None:
        moved = False
        for d in self._docs:
            if d.head is not None and d.found[0] is not d.text and max(d.head.count("\n"), d.text.count("\n")) < more.CHANGES_LIMIT:
                marks = more.change_marks(self._found(d), d.text.count("\n") + 1)
                moved, d.marks = moved or marks != d.marks, marks
        if moved:
            self.changed.emit()

    @Slot(int, int, int, result=int)
    def changeNear(self, i: int, line: int, way: int) -> int:
        """The line of the next (way 1) or previous (-1) change from `line`, going round at the ends; -1 when there are none."""
        if not 0 <= i < len(self._docs):
            return -1
        d = self._docs[i]
        found = self._found(d)
        starts = sorted({c["a"] for c in found}) if found else sorted(n for n in d.marks if n - 1 not in d.marks)
        if not starts:
            return -1
        here = next((c["a"] for c in found if c["a"] <= line < max(c["b"], c["a"] + 1)), line)
        if way >= 0:
            return next((n for n in starts if n > here), starts[0])
        return next((n for n in reversed(starts) if n < here), starts[-1])

    @Slot(int, int, result="QVariantMap")
    def putBack(self, i: int, line: int) -> dict:
        """The change on `line`, undone: {at, end, text} for the editor to put the committed lines back (so it can be undone
        there); {} when that line hasn't changed."""
        if not 0 <= i < len(self._docs):
            return {}
        d = self._docs[i]
        c = more.change_at(self._found(d), line)
        if not c or d.read_only:
            return {}
        s, e, text = more.put_back(d.text, c)
        return {"at": more.u16(d.text, s), "end": more.u16(d.text, e), "text": text, "line": min(c["a"], d.text.count("\n"))}

    @Slot(int, int, int, str, result="QVariantMap")
    def lineEdit(self, i: int, a: int, b: int, how: str) -> dict:
        """A whole-line command (more.LINE_EDITS) on the selection a..b of tab i, as one replacement for the editor to make:
        {at, end, text, a, b}; {} when there's nothing to do."""
        if not 0 <= i < len(self._docs):
            return {}
        d = self._docs[i]
        if d.read_only or d.binary:
            return {}
        t = d.text
        got = more.line_edit(t, more.from16(t, a), more.from16(t, b), how)
        if not got:
            return {}
        s, e, new, sa, sb = got
        after = t[:s] + new + t[e:]
        return {"at": more.u16(t, s), "end": more.u16(t, e), "text": new, "a": more.u16(after, sa), "b": more.u16(after, sb)}

    # ---------------------------------------------------------------- unsaved work, kept
    @staticmethod
    def _stash_file(path: str) -> Path:
        import hashlib
        return UNSAVED / (hashlib.sha1(path.encode("utf-8", "surrogateescape")).hexdigest()[:24] + ".json")

    def _stash_now(self) -> None:
        """Every changed document's text put by (and a saved one's taken away), so a quit, a crash or a power cut loses nothing."""
        if self._demo:
            return
        import hashlib
        for d in self._docs:
            if d.dirty and not d.binary and not d.read_only and len(d.text) <= STASH_LIMIT:
                if d.stashed is d.text:
                    continue
                try:
                    UNSAVED.mkdir(parents=True, exist_ok=True)
                    os.chmod(UNSAVED, 0o700)
                    f = self._stash_file(d.path)
                    tmp = f.with_suffix(".saving")
                    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8", errors="surrogatepass") as out:
                        json.dump({"path": d.path, "text": d.text, "base": hashlib.sha1(d.saved.encode("utf-8", "surrogatepass")).hexdigest(), "at": time.time()}, out)
                    os.replace(tmp, f)
                    d.stashed = d.text
                except (OSError, ValueError):
                    pass
            elif d.stashed is not None:
                self._stash_drop(d)

    def _stash_drop(self, d: Doc) -> None:
        d.stashed = None
        try:
            self._stash_file(d.path).unlink(missing_ok=True)
        except OSError:
            pass

    def _stash_apply(self, d: Doc) -> None:
        """Opening a file whose unsaved changes were put by: they come back, as unsaved changes."""
        if self._demo:
            return
        f = self._stash_file(d.path)
        try:
            if not f.is_file():
                return
            data = json.loads(f.read_text(encoding="utf-8", errors="surrogatepass"))
            text, base = data["text"], str(data.get("base", ""))
            if data.get("path") != d.path or not isinstance(text, str) or len(text) > STASH_LIMIT:
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            try:
                f.unlink(missing_ok=True)                     # not something Code wrote: it goes
            except OSError:
                pass
            return
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if d.binary or d.read_only:
            return
        if text == d.text:
            self._stash_drop(d)
            return
        import hashlib
        moved = base != hashlib.sha1(d.saved.encode("utf-8", "surrogatepass")).hexdigest()
        d.text = d.stashed = text
        if moved:
            d.mtime = -1.0                                    # the file changed on disk meanwhile: saving asks before replacing it
        self._brought.append((Path(d.path).name, moved))
        self._tell.start()

    def _tell_brought(self) -> None:
        got, self._brought = self._brought, []
        if not got:
            return
        what = f"your unsaved changes to {got[0][0]}" if len(got) == 1 else f"unsaved changes in {len(got)} files"
        also = " It has also changed on disk since: look before you save." if len(got) == 1 and got[0][1] else \
               " Some have also changed on disk since: look before you save." if any(m for _n, m in got) else ""
        self.said.emit(f"Brought back {what}.{also}", False)

    def _bring_back(self) -> None:
        """At the start, or when a folder opens: files with unsaved work put by that aren't open yet open again
        (this folder's, or any when no folder is open). Work put by more than a month ago is let go."""
        if self._demo:
            return
        try:
            files = sorted(UNSAVED.glob("*.json"))[:400]
        except OSError:
            return
        opened = 0
        for f in files:
            try:
                if time.time() - f.stat().st_mtime > 30 * 86400:
                    f.unlink(missing_ok=True)
                    continue
                path = json.loads(f.read_text(encoding="utf-8", errors="surrogatepass")).get("path")
            except (OSError, ValueError, AttributeError):
                continue
            if not isinstance(path, str) or any(d.path == path for d in self._docs) or not os.path.isfile(path):
                continue
            if self._root and not path.startswith(str(self._root) + os.sep):
                continue
            if opened < 12:
                opened += 1
                self.openFile(path, False)

    @Slot(str, bool, result="QVariantList")
    def diff(self, rel: str, staged: bool) -> list:
        if not self._root:
            return []
        try:
            change = next((c for c in self._changes if c["path"] == rel), None)
            mid = ["HEAD"] if change and change["kind"] == "conflict" else (["--cached"] if staged else [])   # in a conflict: against our side
            args = ["diff", "--no-color", "--no-ext-diff", "-U3"] + mid + ["--", rel]
            out = git(self._root, *args, timeout=15).stdout
            if not out.strip():
                change = next((c for c in self._changes if c["path"] == rel), None)
                if change and change["kind"] == "new":
                    text = (self._root / rel).read_text(encoding="utf-8", errors="replace")
                    return [{"text": line, "kind": "add", "old": "", "new": str(n + 1)} for n, line in enumerate(text.split("\n")[:4000])]
        except (OSError, subprocess.SubprocessError):
            return []
        return diff_rows(out)

    def _git_do(self, *args, then_say: str = "") -> str:
        if not self._root:
            return "Open a project first."
        try:
            out = git(self._root, *args, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            return str(e)
        self.refreshGit()
        for d in self._docs:
            self._marks(d)
        self.changed.emit()
        if out.returncode != 0:
            return (out.stderr or out.stdout).strip().split("\n")[-1][:300] or "Git said no."
        if then_say:
            self.said.emit(then_say, False)
        return ""

    @Slot(str, result=str)
    def stage(self, rel: str) -> str:
        return self._git_do("add", "--", rel)

    @Slot(str, result=str)
    def unstage(self, rel: str) -> str:
        return self._git_do("restore", "--staged", "--", rel)

    @Slot(result=str)
    def stageAll(self) -> str:
        return self._git_do("add", "-A")

    @Slot(str, result=str)
    def discard(self, rel: str) -> str:
        """Throw away the changes to a file (the window asks first). A new file goes to the Trash instead."""
        if self._root is None:
            return ""
        change = next((c for c in self._changes if c["path"] == rel), None)
        if change and change["kind"] == "new":
            return self.remove(str(self._root / rel))
        got = self._git_do("restore", "--staged", "--worktree", "--", rel)
        for i, d in enumerate(self._docs):
            if d.path == str((self._root / rel).resolve()):
                self.reload(i)
        return got

    @Slot(str, result=str)
    def commit(self, message: str) -> str:
        if not message.strip():
            return "Write a few words about what changed."
        if not any(c["staged"] for c in self._changes):
            self._git_do("add", "-A")
        return self._git_do("commit", "-m", message.strip(), then_say="Committed")

    # ---- branches: what's there, switch, start a new one, delete one that's merged
    @Slot(result="QVariantList")
    def branches(self) -> list:
        if not self._root or not self._git:
            return []
        if self._demo:
            return [{"name": "main", "current": True, "when": "2 hours ago", "subject": "Kp index from the forecast"},
                    {"name": "clouds-layer", "current": False, "when": "yesterday", "subject": "Cloud cover by the hour"}]
        try:
            out = git(self._root, "for-each-ref", "--sort=-committerdate", "--format=%(HEAD)\t%(refname:short)\t%(committerdate:relative)\t%(subject)",
                      "refs/heads", timeout=10)
        except (OSError, subprocess.SubprocessError):
            return []
        rows = []
        for line in out.stdout.splitlines():
            head, name, when, subject = (line.split("\t") + ["", "", "", ""])[:4]
            if name:
                rows.append({"name": name, "current": head.strip() == "*", "when": when, "subject": subject})
        if not rows and self._branch:                              # a repository with no commits yet
            rows.append({"name": self._branch, "current": True, "when": "", "subject": "No commits yet"})
        return rows

    @Slot(str, result=str)
    def switchBranch(self, name: str) -> str:
        """Switch to a branch. Unsaved files are saved first; git keeps changes that don't clash with the branch."""
        if self._demo:
            self._branch = name
            self.changed.emit()
            return ""
        for i, d in enumerate(self._docs):
            if d.text != d.saved:
                self.save(i, False)
        got = self._git_do("switch", name, then_say=f"On {name} now")
        if not got:
            for i in range(len(self._docs)):
                self.reload(i)
        return self._why_not_switch(got)

    @staticmethod
    def _why_not_switch(got: str) -> str:
        if "overwritten" in got or "would be" in got:
            return "Some of your changes would be lost switching: commit them (or stash them) first."
        if "while merging" in got or "merge" in got and "quit" in got:
            return "A merge is under way here: finish it (resolve and commit) first."
        if "rebase" in got:
            return "A rebase is under way here: finish it first."
        return got

    @Slot(str, result=str)
    def newBranch(self, name: str) -> str:
        name = re.sub(r"\s+", "-", name.strip())
        if not name:
            return "Give it a name."
        if self._demo:
            self._branch = name
            self.changed.emit()
            return ""
        check = git(self._root, "check-ref-format", "--branch", name, timeout=5) if self._root else None
        if check is not None and check.returncode != 0:
            return "That can't be a branch's name (no spaces, no .. or ~ ^ : ? * [)."
        return self._why_not_switch(self._git_do("switch", "-c", name, then_say=f"Started {name}"))

    @Slot(str, result=str)
    def deleteBranch(self, name: str) -> str:
        """Delete a branch that's merged (git refuses one with work that's only there, and says why)."""
        if name == self._branch:
            return "Switch to another branch first."
        if self._demo:
            return ""
        got = self._git_do("branch", "-d", name, then_say=f"Deleted {name}")
        if "not fully merged" in got:
            return f"{name} has work that isn't anywhere else yet, so it's kept."
        return got

    @Slot()
    def initRepo(self) -> None:
        self._git_do("init", then_say="This folder is now a Git repository")

    @Slot(str)
    def sync(self, what: str) -> None:
        """Pull, then push (or just one), off the window's thread. Sign-in prompts can't appear, so they fail with a reason."""
        if not self._root or what not in ("pull", "push", "sync"):
            return
        self._busy = {"pull": "pulling", "push": "pushing", "sync": "syncing"}[what]
        self.changed.emit()
        root = self._root

        def go():
            msgs = []
            for step in (["pull", "--ff-only"], ["push"]) if what == "sync" else ([["pull", "--ff-only"]] if what == "pull" else [["push"]]):
                try:
                    out = git(root, *step, timeout=120)
                except (OSError, subprocess.SubprocessError) as e:
                    msgs.append((str(e), True))
                    break
                if out.returncode != 0:
                    err = (out.stderr or out.stdout).strip()
                    if "could not read Username" in err or "terminal prompts disabled" in err or "Authentication failed" in err:
                        err = "The server wants you to sign in. Run the same command in the terminal below once; Git can remember it after that."
                    msgs.append((err.split("\n")[-1][:300] if "sign in" not in err else err, True))
                    break
                msgs.append(({"pull": "Up to date with the server", "push": "Pushed"}[step[0]], False))

            def done():
                self._busy = ""
                self.refreshGit()
                for d in self._docs:
                    self._marks(d)
                for i, d in enumerate(self._docs):
                    if not d.dirty:
                        try:
                            if abs(Path(d.path).stat().st_mtime - d.mtime) > 0.001:
                                self.reload(i)
                        except OSError:
                            pass
                if msgs:
                    self.said.emit(*msgs[-1])
                self.changed.emit()
            self._back.emit(done)
        threading.Thread(target=go, daemon=True).start()

    # ---------------------------------------------------------------- terminal and Run
    def _get_term(self):
        if self._term is None and self._shell_class is not None and self._settings is not None and not self._demo:
            self._term = self._shell_class(self._settings, self._root)
        return self._term

    terminal = Property(QObject, _get_term, notify=changed)

    @Slot(result=str)
    def runCommand(self) -> str:
        d = self._docs[self._at] if 0 <= self._at < len(self._docs) else None
        return run_command(self._root, d.path if d else "", d.lang if d else "")

    @Slot(str)
    def run(self, command: str) -> None:
        """Save everything, then type the command into the terminal below."""
        command = command.strip() or self.runCommand()
        if not command:
            self.said.emit("Nothing to run here. Put the command in a file called .huginn-run in the project.", True)
            return
        self.saveAll()
        term = self._get_term()
        if term is None:
            self.said.emit(f"Would run: {command}", False)
            return
        send = getattr(term, "type_when_ready", term._send)     # (a terminal just opened isn't listening yet)
        door, remote, mount = self._place()
        if remote:                                              # the project is on another computer or in a container: so is what it runs
            send((door.wrap(remote, command, tty=True, mount=mount) + "\r").encode("utf-8"))
            return
        if self._root:
            send(f"cd {json.dumps(str(self._root))}\r".encode())
        send((command + "\r").encode("utf-8"))

    @Slot(str)
    def terminalAt(self, path: str) -> None:
        """The files list's "Open Terminal Here": the terminal below goes to that folder (a file's own folder)."""
        where = Path(path)
        if where.is_file():
            where = where.parent
        term = self._get_term()
        if term is None:
            self.said.emit(f"Would open a terminal in {where}", False)
            return
        getattr(term, "type_when_ready", term._send)(f"cd {json.dumps(str(where))}\r".encode())

    @Slot(str)
    def copyPath(self, path: str) -> None:
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(path)
        self.said.emit("Path copied.", False)

    @Slot(str)
    def setRun(self, command: str) -> None:
        if self._root:
            try:
                (self._root / ".huginn-run").write_text(command.strip() + "\n", encoding="utf-8")
            except OSError as e:
                self.said.emit(f"Couldn't save it: {e.strerror or e}", True)

    # ---------------------------------------------------------------- language servers
    def _client_for(self, d: Doc, start: bool = True):
        lang = d.lang
        if lang in self._servers:
            c = self._servers[lang]
            return c if c and c.alive else None
        if not start or self._demo:
            return None
        info = LANGS.get(lang)
        if not info or not info[5]:
            return None
        argv = next(([which(a[0])] + a[1:] for a in info[5] if which(a[0])), None)
        if not argv:
            self._servers[lang] = None
            self._server_note[lang] = ""
            return None
        if lang == "GDScript":
            # Godot's editor is the helper, and only while this project is open in it: looked for again on each file
            # opened (and when a helper that was there goes away), never remembered as missing.
            import huginn_lsp_tcp
            if self._root and hb.godot_major(self._root) == 3:
                argv = argv[:-1] + ["6008"]                            # (where Godot 3's editor listens; Godot 4's is 6005)
            if not huginn_lsp_tcp.port_open(argv[-2], int(argv[-1])):
                self._server_note[lang] = "open the project in Godot for suggestions"
                return None
        root = self._root or Path(d.path).parent
        client = LspClient(argv, root, info[4], self)
        if lang == "GDScript":
            client.proc.finished.connect(lambda *_: (self._servers.pop("GDScript", None), self._server_note.__setitem__("GDScript", "open the project in Godot for suggestions"), self.changed.emit()))
        client.diagnostics.connect(self._got_diagnostics)
        client.applyEdit.connect(self._workspace_edit)
        client.failed.connect(lambda why, l=lang: (self._server_note.__setitem__(l, ""), self.said.emit(f"{l} helper: {why}", True)) if l != "GDScript" else None)
        client.ready.connect(lambda l=lang, name=os.path.basename(argv[0]): (self._server_note.__setitem__(l, name), self.changed.emit()))
        self._servers[lang] = client
        self._server_note[lang] = "starting " + os.path.basename(argv[0])
        return client

    def _lsp_open(self, d: Doc) -> None:
        if d.binary:
            return
        c = self._client_for(d)
        if c:
            c.notify("textDocument/didOpen", {"textDocument": {"uri": d.uri, "languageId": LANGS[d.lang][4], "version": d.version, "text": d.text}})

    def _lsp_close(self, d: Doc) -> None:
        c = self._client_for(d, start=False)
        if c:
            c.notify("textDocument/didClose", {"textDocument": {"uri": d.uri}})

    def _push_changes(self) -> None:
        for i in sorted(getattr(self, "_pending", set())):
            if 0 <= i < len(self._docs):
                d = self._docs[i]
                c = self._client_for(d, start=False)
                if c:
                    c.notify("textDocument/didChange", {"textDocument": {"uri": d.uri, "version": d.version}, "contentChanges": [{"text": d.text}]})
                else:
                    self._lint_python(d)
        self._pending = set()

    def _lint_python(self, d: Doc) -> None:
        """Without a language server, Python still gets its syntax checked as you type; JSON its validity."""
        if self._servers.get(d.lang):
            return
        before = d.problems
        if d.lang == "Python":
            try:
                compile(d.text, d.path, "exec", dont_inherit=True)
                d.problems = []
            except SyntaxError as e:
                d.problems = [{"line": max(0, (e.lineno or 1) - 1), "col": max(0, (e.offset or 1) - 1), "endLine": max(0, (e.lineno or 1) - 1), "endCol": max(0, (e.offset or 1)),
                               "severity": 1, "message": e.msg, "source": "python"}]
            except (ValueError, RecursionError):
                pass
        elif d.lang == "JSON" and d.path.endswith(".json"):
            try:
                json.loads(d.text or "null")
                d.problems = []
            except ValueError as e:
                d.problems = [{"line": getattr(e, "lineno", 1) - 1, "col": getattr(e, "colno", 1) - 1, "endLine": getattr(e, "lineno", 1) - 1, "endCol": getattr(e, "colno", 1),
                               "severity": 1, "message": getattr(e, "msg", str(e)), "source": "json"}]
        if d.problems != before:
            self.changed.emit()

    def _got_diagnostics(self, uri: str, items: list) -> None:
        for d in self._docs:
            if d.uri == uri:
                d.problems = items
                self.changed.emit()
                return

    @Slot(int, int, int)
    def complete(self, i: int, line: int, col: int) -> None:
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]
        c = self._client_for(d, start=False)
        if not c:
            self.completions.emit(i, self._with_snippets(d, line, col, self._word_completions(d, line, col)))
            return
        self._push_changes()

        def got(result, error):
            items = result.get("items", []) if isinstance(result, dict) else (result or [])
            out = []
            for it in items[:200]:
                edit = it.get("textEdit") or {}
                text = edit.get("newText") or it.get("insertText") or it.get("label", "")
                item = {"label": it.get("label", ""), "insert": text, "detail": (it.get("detail") or "")[:80], "kind": it.get("kind", 1),
                        "sort": it.get("sortText") or it.get("label", "")}
                if it.get("insertTextFormat") == 2 and re.search(r"\$\{?\d", text):
                    item["snippet"] = text
                out.append(item)
            out.sort(key=lambda x: x["sort"])
            for n, item in enumerate(out):
                item["rank"] = n                                          # the server's own order, as a hint
            self.completions.emit(i, self._with_snippets(d, line, col, self._ranked(d, line, out) if out else self._word_completions(d, line, col)))
        c.request("textDocument/completion", {"textDocument": {"uri": d.uri}, "position": {"line": line, "character": col}}, got)

    # ---------------------------------------------------------------- which suggestion is likeliest
    # Each suggestion carries what the editor needs to put the likeliest first as you type (Code.qml, filterOffer):
    # how often the word is already in the file (freq), how near its nearest use is to the cursor in lines (near),
    # and how lately you picked it (recent: 1 for the last pick, falling away over the last 200). The editor adds
    # how well it matches what's typed (the same case at the start, any case, then the capitals or parts of the name).
    def _ranked(self, d: Doc, line: int, items: list) -> list:
        uses = {}
        for n, text in enumerate(d.text.split("\n")):
            for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
                count, near = uses.get(w, (0, 10 ** 6))
                uses[w] = (count + 1, min(near, abs(n - line)))
        picked = self._picks()
        for it in items:
            count, near = uses.get(it["label"], (0, 10 ** 6))
            if near == 0 and count == 1:                                  # the word being typed is the only use
                count, near = 0, 10 ** 6
            it["freq"], it["near"] = count, near
            it["recent"] = round(1 - picked.index(it["label"]) / len(picked), 3) if it["label"] in picked else 0
        return items

    def _picks(self) -> list:
        if not hasattr(self, "_picked"):
            try:
                self._picked = [str(w) for w in json.loads(STATE.with_name("code-picks.json").read_text(encoding="utf-8"))][:200]
            except (OSError, ValueError, TypeError):
                self._picked = []
        return self._picked

    @Slot(str)
    def picked(self, label: str) -> None:
        """A suggestion was taken: it comes first sooner next time (kept across runs, the last 200)."""
        if not label:
            return
        self._picked = [label] + [w for w in self._picks() if w != label][:199]
        try:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.with_name("code-picks.json").write_text(json.dumps(self._picked), encoding="utf-8")
        except OSError:
            pass

    def _word_completions(self, d: Doc, line: int, col: int) -> list:
        """Without a language server: the words already in the file that start like this one."""
        lines = d.text.split("\n")
        here = lines[line][:max(0, col)] if 0 <= line < len(lines) else ""
        m = re.search(r"[A-Za-z_][A-Za-z0-9_]*$", here)
        prefix = m.group() if m else ""
        if len(prefix) < 2:
            return []
        low = prefix.lower()
        words = {w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", d.text) if w.lower().startswith(low[:1]) and w != prefix} | \
                {w for w in LANGS.get(d.lang, LANGS["Text"])[3].split() if w.lower().startswith(low[:1]) and w != prefix}
        items = [{"label": w, "insert": w, "detail": "", "kind": 14 if w in LANGS.get(d.lang, LANGS["Text"])[3].split() else 1, "sort": w, "rank": 0} for w in sorted(words)]
        return self._ranked(d, line, items)[:400]

    @Slot(int, int, int)
    def definition(self, i: int, line: int, col: int) -> None:
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]
        c = self._client_for(d, start=False)
        if not c:
            self._guess_definition(d, line, col)
            return
        self._push_changes()

        def got(result, error):
            loc = result[0] if isinstance(result, list) and result else result
            if not loc:
                self._guess_definition(d, line, col)
                return
            uri = loc.get("uri") or loc.get("targetUri")
            rng = loc.get("range") or loc.get("targetSelectionRange") or {}
            start = rng.get("start", {})
            path = QUrl(uri).toLocalFile()
            if path:
                self.openFile(path, True, start.get("line", 0), start.get("character", 0))
        c.request("textDocument/definition", {"textDocument": {"uri": d.uri}, "position": {"line": line, "character": col}}, got)

    # ---------------------------------------------------------------- peek: the definition shown where you are
    peeked = Signal(int, "QVariantMap")                  # tab, {path, name, line, first, text, lang}: a few lines around it

    @Slot(int, int, int)
    def peek(self, i: int, line: int, col: int) -> None:
        """Show the definition of what's under the cursor without leaving the file (the helper's answer, else the
        project searched for a definition of that name)."""
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]

        def show(path: str, at: int) -> None:
            try:
                other = next((x for x in self._docs if x.path == path), None)
                text = other.text if other else Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return
            lines = text.split("\n")
            first = max(0, at - 3)
            try:
                name = os.path.relpath(path, self._root) if self._root and Path(path).is_relative_to(self._root) else path
            except ValueError:
                name = path
            self.peeked.emit(i, {"path": path, "name": name, "line": at, "first": first, "text": "\n".join(line[:400] for line in lines[first:first + 14]),
                                 "lang": language_of(path, text[:200])})

        c = self._client_for(d, start=False)
        if not c:
            self._guess_definition(d, line, col, show)
            return
        self._push_changes()

        def got(result, error):
            loc = result[0] if isinstance(result, list) and result else result
            if not loc:
                self._guess_definition(d, line, col, show)
                return
            path = QUrl(loc.get("uri") or loc.get("targetUri") or "").toLocalFile()
            if path:
                show(path, int(((loc.get("range") or loc.get("targetSelectionRange") or {}).get("start") or {}).get("line", 0)))
        c.request("textDocument/definition", {"textDocument": {"uri": d.uri}, "position": {"line": line, "character": col}}, got)

    # ---------------------------------------------------------------- inlay hints: what the helper adds beside the code
    hinted = Signal(int, "QVariantList")                 # tab, [{line, text}]: hints gathered to the end of their line

    @Slot(int, int, int)
    def inlayHints(self, i: int, first: int, last: int) -> None:
        """Ask the helper for the hints on these lines (parameter names, inferred types). They come back gathered at
        the end of each line, since Code's editor can't put words between yours."""
        if not 0 <= i < len(self._docs) or not self.setting("editor.inlayHints.enabled"):
            return
        d = self._docs[i]
        c = self._client_for(d, start=False)
        if not c or not c.up or not c.caps.get("inlayHintProvider"):
            return
        self._push_changes()
        first, last = max(0, first), max(first, min(last, first + 400))

        def got(result, error):
            rows = {}
            for h in result if isinstance(result, list) else []:
                if not isinstance(h, dict):
                    continue
                label = h.get("label")
                label = "".join(str(p.get("value", "")) for p in label if isinstance(p, dict)) if isinstance(label, list) else str(label or "")
                pos = h.get("position") or {}
                if label.strip():
                    rows.setdefault(int(pos.get("line", 0)), []).append((int(pos.get("character", 0)), label.strip().strip(":").strip() if h.get("kind") == 2 else label.strip()))
            lines = d.text.split("\n")
            out = []
            for ln, hints in sorted(rows.items()):
                if 0 <= ln < len(lines):
                    hints.sort()
                    out.append({"line": ln, "text": "  ".join(text for _, text in hints)[:160]})
            if d in self._docs:
                self.hinted.emit(self._docs.index(d), out)
        c.request("textDocument/inlayHint", {"textDocument": {"uri": d.uri}, "range": {"start": {"line": first, "character": 0}, "end": {"line": last + 1, "character": 0}}}, got)

    # ---------------------------------------------------------------- folding
    folded = Signal(int)                                 # tab: what is folded changed (the editor lays its text out again)

    def _text_doc(self, d: Doc):
        return d.styler.document() if getattr(d, "styler", None) is not None else None

    def _fold_ranges(self, d: Doc) -> list:
        key = (len(d.text), hash(d.text))
        if getattr(d, "_folds", (None,))[0] != key:
            d._folds = (key, more.fold_ranges(d.text, self._tab_width(d)))
        return d._folds[1]

    @Slot(int, result="QVariantList")
    def foldRanges(self, i: int) -> list:
        """[[start, end]…]: the lines that can be folded away under their first."""
        if not 0 <= i < len(self._docs) or not self.setting("editor.folding"):
            return []
        return [list(r) for r in self._fold_ranges(self._docs[i])]

    @Slot(int, result="QVariantList")
    def hiddenOf(self, i: int) -> list:
        """[[first, last]…]: the runs of lines that are folded away now, in order."""
        doc = self._text_doc(self._docs[i]) if 0 <= i < len(self._docs) else None
        out = []
        if doc is None:
            return out
        block, n, run = doc.firstBlock(), 0, None
        while block.isValid():
            if not block.isVisible():
                run = [n, n] if run is None else [run[0], n]
            elif run is not None:
                out.append(run)
                run = None
            block, n = block.next(), n + 1
        if run is not None:
            out.append(run)
        return out

    def _set_hidden(self, i: int, hide: set, show: set) -> bool:
        """Hide and show lines of tab i's text. Returns whether anything changed (and says so to the window)."""
        doc = self._text_doc(self._docs[i])
        if doc is None:
            return False
        changed = False
        for n in sorted(hide | show):
            block = doc.findBlockByNumber(n)
            want = n not in hide
            if block.isValid() and block.isVisible() != want and (n > 0 or want):
                block.setVisible(want)
                changed = True
        if changed:
            doc.markContentsDirty(0, doc.characterCount())
            self.folded.emit(i)
        return changed

    @Slot(int, int)
    def toggleFold(self, i: int, line: int) -> None:
        """Fold what's under this line, or unfold it if it is folded."""
        if not 0 <= i < len(self._docs):
            return
        run = next((r for r in self.hiddenOf(i) if r[0] == line + 1), None)
        if run:
            self._set_hidden(i, set(), set(range(run[0], run[1] + 1)))
            return
        r = more.fold_range_at(self._fold_ranges(self._docs[i]), line)
        if r and self.setting("editor.folding"):
            self._set_hidden(i, set(range(r[0] + 1, r[1] + 1)), set())

    @Slot(int, int)
    def foldAt(self, i: int, line: int) -> None:
        if 0 <= i < len(self._docs) and not any(r[0] == line + 1 for r in self.hiddenOf(i)):
            self.toggleFold(i, line)

    @Slot(int, int)
    def unfoldAt(self, i: int, line: int) -> None:
        """Show a line that is folded away (with the rest of its fold), or what's folded under it."""
        if not 0 <= i < len(self._docs):
            return
        run = next((r for r in self.hiddenOf(i) if r[0] - 1 <= line <= r[1]), None)
        if run:
            self._set_hidden(i, set(), set(range(run[0], run[1] + 1)))

    @Slot(int)
    def foldAll(self, i: int) -> None:
        if 0 <= i < len(self._docs) and self.setting("editor.folding"):
            hide = set()
            for start, end in self._fold_ranges(self._docs[i]):
                hide.update(range(start + 1, end + 1))
            self._set_hidden(i, hide, set())

    @Slot(int)
    def unfoldAll(self, i: int) -> None:
        if 0 <= i < len(self._docs):
            self._set_hidden(i, set(), {n for r in self.hiddenOf(i) for n in range(r[0], r[1] + 1)})

    @Slot(int)
    def checkFolds(self, i: int) -> None:
        """After the text changed: nothing stays hidden unless a line that can still be folded stands over it (text
        you can't see, with no way to bring it back, must never be)."""
        if not 0 <= i < len(self._docs):
            return
        runs = self.hiddenOf(i)
        if not runs:
            return
        starts = {start: end for start, end in self._fold_ranges(self._docs[i])}
        orphans = set()
        for first, last in runs:
            if starts.get(first - 1, -1) < last:
                orphans.update(range(first, last + 1))
        if orphans:
            self._set_hidden(i, set(), orphans)

    # ---------------------------------------------------------------- Emmet
    @Slot(int, str, result="QVariantMap")
    def emmetAt(self, i: int, before: str) -> dict:
        """Tab after an abbreviation in HTML or CSS: {back: how many characters of it to replace, body: the snippet},
        or {} when what's before the cursor isn't one."""
        if not 0 <= i < len(self._docs):
            return {}
        lang = self._docs[i].lang
        kind = "css" if lang == "CSS" else "html" if lang in ("HTML", "PHP", "Vue", "Svelte", "XML") or Path(self._docs[i].path).suffix in (".jsx", ".tsx", ".html", ".htm", ".vue") else ""
        if not kind:
            return {}
        abbr = emmet.abbreviation_before(before[-400:], kind)
        body = (emmet.expand_css(abbr) if kind == "css" else emmet.expand(abbr)) if abbr else None
        return {"back": len(abbr), "body": body} if body else {}

    # ---------------------------------------------------------------- a file's history
    @Slot(int, result="QVariantList")
    def historyOf(self, i: int) -> list:
        return more.history_list(self._docs[i].path) if 0 <= i < len(self._docs) else []

    @Slot(int, str, result="QVariantList")
    def historyDiff(self, i: int, ident: str) -> list:
        """The changes from a kept version to the text now, as rows for the diff sheet."""
        old = more.history_read(self._docs[i].path, ident) if 0 <= i < len(self._docs) else None
        return diff_rows(more.history_diff(old, self._docs[i].text)) if old is not None else []

    @Slot(int, str, result=bool)
    def historyRestore(self, i: int, ident: str) -> bool:
        """Put a kept version's text back in the editor (not saved until you save; undo brings back what was there)."""
        old = more.history_read(self._docs[i].path, ident) if 0 <= i < len(self._docs) else None
        if old is None or self._docs[i].read_only:
            return False
        if old != self._docs[i].text:
            self._edit_text(i, [[0, len(self._docs[i].text), old.replace("\r\n", "\n")]])
        return True

    def _guess_definition(self, d: Doc, line: int, col: int, show=None) -> None:
        lines = d.text.split("\n")
        if not 0 <= line < len(lines):
            return
        text = lines[line]
        m = next((m for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", text) if m.start() <= col <= m.end()), None)
        if not m:
            return
        name = m.group()
        pat = re.compile(rf"^\s*(?:async\s+)?(?:def|class|function|func|fn|struct|enum|interface|type|const|let|var)\s+{re.escape(name)}\b")
        for n, l in enumerate(lines):
            if pat.match(l):
                if show:
                    show(d.path, n)
                else:
                    self.jump.emit(self._docs.index(d), n, l.find(name))
                return
        self.said.emit(f"Couldn't find where “{name}” is made.", True)

    @Slot(int, int, int)
    def hover(self, i: int, line: int, col: int) -> None:
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]
        c = self._client_for(d, start=False)
        if not c:
            return

        def got(result, error):
            if not result:
                return
            contents = result.get("contents")
            if isinstance(contents, dict):
                text = contents.get("value", "")
            elif isinstance(contents, list):
                text = "\n\n".join(x.get("value", "") if isinstance(x, dict) else str(x) for x in contents)
            else:
                text = str(contents or "")
            if text.strip():
                self.hoverText.emit(i, text.strip()[:3000])
        c.request("textDocument/hover", {"textDocument": {"uri": d.uri}, "position": {"line": line, "character": col}}, got)

    @Slot(int)
    def format(self, i: int, then=None) -> None:
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]
        c = self._client_for(d, start=False)
        if not c or not c.caps.get("documentFormattingProvider"):
            if then:
                then()
                return
            self.said.emit("No formatter for this kind of file.", True)
            return
        self._push_changes()

        def got(result, error):
            if not result:
                if then:
                    then()
                    return
                self.said.emit("Already tidy.", False)
                return
            lines = d.text.split("\n")
            offsets = [0]
            for l in lines:
                offsets.append(offsets[-1] + len(l) + 1)

            def at(p):
                return offsets[min(p["line"], len(lines))] + p["character"]
            if d in self._docs:
                self._edit_text(self._docs.index(d), [[at(e["range"]["start"]), at(e["range"]["end"]), e["newText"]] for e in result])
            if then:
                then()
        c.request("textDocument/formatting", {"textDocument": {"uri": d.uri}, "options": {"tabSize": len(self._unit(d).replace("\t", " " * self._tab_width(d))), "insertSpaces": self._unit(d) != "\t"}}, got)



    # ---------------------------------------------------------------- blame and history
    @Slot(int, result="QVariantList")
    def blame(self, i: int) -> list:
        """Who last changed each line of a file, and when: [{sha, short, author, when, summary, first}] a line; lines
        not committed yet say so. `first` marks where a run of lines from one commit starts."""
        if not (0 <= i < len(self._docs)) or not self._root or not self._git:
            return []
        d = self._docs[i]
        try:
            r = subprocess.run(["git", "-C", str(self._root), "blame", "--porcelain", "--contents", "-", "--", str(Path(d.path).relative_to(self._root))],
                               input=d.text, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        except (OSError, subprocess.SubprocessError, ValueError):
            return []
        if r.returncode != 0:
            return []
        out, prev = [], None
        now = time.time()
        for b in parse_blame(r.stdout):
            mine = b["sha"].startswith("0000000")
            out.append({"sha": "" if mine else b["sha"], "short": "" if mine else b["sha"][:7], "author": "You" if mine else b["author"],
                        "when": "not committed" if mine else ago(b["time"], now), "summary": "" if mine else b["summary"], "first": b["sha"] != prev})
            prev = b["sha"]
        return out

    @Slot(int, result=str)
    def relOf(self, i: int) -> str:
        """An open file's path inside the project ("" when it isn't in it): for This File's History."""
        if not self._root or not (0 <= i < len(self._docs)):
            return ""
        path = self._docs[i].path or ""
        return os.path.relpath(path, self._root) if path.startswith(str(self._root) + os.sep) else ""

    @Slot(str, result="QVariantList")
    def history(self, rel: str) -> list:
        """The project's commits (or one file's, following renames), newest first, with a lane graph to draw."""
        if not self._root or not self._git:
            return []
        args = ["log", "--format=%H%x1f%h%x1f%an%x1f%at%x1f%s%x1f%P%x1f%D", "-n", "300"]
        args += (["--follow", "--", rel] if rel else ["--all", "--date-order"])
        try:
            out = git(self._root, *args, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        now = time.time()
        rows = lane_graph(parse_log(out)) if not rel else [dict(c, lane=0, width=1, down=[[0, 0]]) for c in parse_log(out)]
        for c in rows:
            c["when"] = ago(c["time"], now)
        return rows

    @Slot(str, str, result="QVariantList")
    def commitRows(self, sha: str, rel: str) -> list:
        if not self._root or not re.fullmatch(r"[0-9a-f]{4,40}", sha or ""):
            return []
        try:
            out = git(self._root, "show", "--format=", "--no-color", "--no-ext-diff", "-U3", sha, *(["--", rel] if rel else []), timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        return show_rows(out)

    @Slot(str, result="QVariantMap")
    def commitInfo(self, sha: str) -> dict:
        if not self._root or not re.fullmatch(r"[0-9a-f]{4,40}", sha or ""):
            return {}
        try:
            out = git(self._root, "show", "-s", "--format=%H%x1f%an%x1f%ae%x1f%at%x1f%B", sha, timeout=10).stdout
            stat = git(self._root, "show", "--format=", "--numstat", sha, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return {}
        f = out.split("\x1f")
        if len(f) < 5:
            return {}
        files = []
        for line in stat.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                files.append({"path": parts[2], "added": parts[0], "removed": parts[1]})
        return {"sha": f[0], "author": f[1], "email": f[2], "when": time.strftime("%-d %b %Y, %H:%M", time.localtime(int(f[3] or 0))), "message": f[4].strip(), "files": files}

    # ---------------------------------------------------------------- tests
    testsChanged = Signal()

    def _tests_init(self) -> None:
        if not hasattr(self, "_tests"):
            self._tests, self._test_status, self._test_kind, self._test_busy, self._test_out, self._test_proc = [], {}, "", "", "", None

    @Slot()
    def discoverTests(self) -> None:
        """Find the project's tests (pytest, cargo test, go test) in the background."""
        self._tests_init()
        root = self._root
        kind = test_framework(root)
        self._test_kind = kind
        if not kind:
            self._tests = []
            self.testsChanged.emit()
            return
        self._test_busy = "Looking for tests…"
        self.testsChanged.emit()

        def work():
            found = []
            try:
                if kind == "pytest":
                    r = subprocess.run([sys.executable if self._python_has_pytest() else "python3", "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                                       cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
                    found = parse_pytest_collect(r.stdout, root)
                elif kind == "cargo":
                    r = subprocess.run(["cargo", "test", "--", "--list", "--format", "terse"], cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
                    for line in r.stdout.splitlines():
                        if line.endswith(": test"):
                            name = line[:-6]
                            found.append({"id": name, "name": name.split("::")[-1], "file": "", "line": 0, "group": "::".join(name.split("::")[:-1]) or "crate"})
                elif kind == "go":
                    r = subprocess.run(["go", "test", "-list", ".", "./..."], cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
                    pkg = ""
                    for line in r.stdout.splitlines():
                        if line.startswith(("ok ", "?   ")):
                            continue
                        if re.fullmatch(r"(Test|Example|Benchmark)\w*", line.strip()):
                            found.append({"id": line.strip(), "name": line.strip(), "file": "", "line": 0, "group": pkg or "package"})
            except (OSError, subprocess.SubprocessError):
                found = []
            self._back.emit(lambda: self._found_tests(found))
        threading.Thread(target=work, daemon=True).start()

    def _python_has_pytest(self) -> bool:
        import importlib.util
        return importlib.util.find_spec("pytest") is not None

    def _found_tests(self, found: list) -> None:
        self._tests, self._test_busy = found, ""
        if self._root and self._test_kind != "pytest":
            for t in self._tests:                             # where each one is, for Rust and Go
                for f in list(self._root.rglob("*.rs" if self._test_kind == "cargo" else "*_test.go"))[:400]:
                    ln = test_line(self._root, str(f.relative_to(self._root)), t["name"])
                    if ln or re.search(rf"\b(fn|func)\s+{re.escape(t['name'])}\b", _read(f)):
                        t["file"], t["line"] = str(f.relative_to(self._root)), ln
                        if self._test_kind == "go":
                            t["group"] = str(f.relative_to(self._root))
                        break
        self.testsChanged.emit()

    @Slot("QVariantList")
    def runTests(self, ids) -> None:
        """Run some tests (or all, with an empty list); results come in when they're done."""
        self._tests_init()
        ids = ids.toVariant() if hasattr(ids, "toVariant") else list(ids)
        if self._test_busy or not self._test_kind or not self._root:
            return
        self.saveAll()
        kind, root = self._test_kind, self._root
        report = Path(tempfile.gettempdir()) / f"huginn-code-tests-{os.getpid()}.xml"
        if kind == "pytest":
            argv = [sys.executable if self._python_has_pytest() else "python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}"] + list(ids)
        elif kind == "cargo":
            argv = ["cargo", "test"] + ([ids[0], "--", "--exact"] if len(ids) == 1 else ["--"]) + ["--test-threads=1"]
        else:
            argv = ["go", "test", "-v", "./..."] + (["-run", "^(" + "|".join(re.escape(i) for i in ids) + ")$"] if ids else [])
        for t in self._tests:
            if not ids or t["id"] in ids:
                self._test_status[t["id"]] = {"status": "running", "message": "", "seconds": 0}
        self._test_busy, self._test_out = "Running tests…", ""
        self.testsChanged.emit()
        proc = QProcess(self)
        proc.setWorkingDirectory(str(root))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._test_proc = proc

        def read():
            self._test_out = (self._test_out + bytes(proc.readAll()).decode(errors="replace"))[-60000:]

        def done(code, _st):
            read()
            if kind == "pytest":
                res = parse_junit(_read(report))
                for t in self._tests:
                    if not ids or t["id"] in ids:
                        self._test_status[t["id"]] = junit_for(res, t["id"]) or {"status": "failed" if code else "passed", "message": "", "seconds": 0}
                report.unlink(missing_ok=True)
            else:
                res = parse_cargo(self._test_out) if kind == "cargo" else parse_go(self._test_out)
                for t in self._tests:
                    if not ids or t["id"] in ids:
                        self._test_status[t["id"]] = res.get(t["id"]) or {"status": "skipped", "message": "", "seconds": 0}
            self._test_busy, self._test_proc = "", None
            failed = sum(1 for v in self._test_status.values() if v.get("status") == "failed")
            passed = sum(1 for v in self._test_status.values() if v.get("status") == "passed")
            self.said.emit(f"{passed} passed" + (f", {failed} failed" if failed else ""), bool(failed))
            self.testsChanged.emit()
        proc.readyRead.connect(read)
        proc.finished.connect(done)
        proc.start(argv[0], argv[1:])

    @Slot()
    def stopTests(self) -> None:
        if getattr(self, "_test_proc", None) is not None:
            self._test_proc.kill()

    def _tests_view(self) -> list:
        self._tests_init()
        return [dict(t, **self._test_status.get(t["id"], {"status": "", "message": "", "seconds": 0})) for t in self._tests]

    tests = Property("QVariantList", _tests_view, notify=testsChanged)
    testKind = Property(str, lambda self: getattr(self, "_test_kind", ""), notify=testsChanged)
    testBusy = Property(str, lambda self: getattr(self, "_test_busy", ""), notify=testsChanged)
    testOutput = Property(str, lambda self: getattr(self, "_test_out", ""), notify=testsChanged)

    @Slot(str)
    def openTest(self, tid: str) -> None:
        t = next((x for x in getattr(self, "_tests", []) if x["id"] == tid), None)
        if t and t.get("file"):
            self.openRel(t["file"], int(t.get("line", 0)), 0)

    # ---------------------------------------------------------------- rename and references
    def _word_at(self, d: Doc, line: int, col: int) -> str:
        lines = d.text.split("\n")
        if line >= len(lines):
            return ""
        if line < 0 or col < 0:
            return ""
        near = lines[line][max(0, col - 200):col + 200]      # a name is short: only the text around the cursor is looked at
        at = min(col, 200)
        m = next((m for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", near) if m.start() <= at <= m.end()), None)
        return m.group() if m and len(m.group()) < 200 and m.start() > 0 - (col <= 200) and m.end() < len(near) + (col + 200 >= len(lines[line])) else ""

    @Slot(int, int, int, result=str)
    def wordAt(self, i: int, line: int, col: int) -> str:
        return self._word_at(self._docs[i], line, col) if 0 <= i < len(self._docs) else ""

    @Slot(int, int, int)
    def references(self, i: int, line: int, col: int) -> None:
        """Shift+F12: every place the name under the cursor is used, in the Search panel."""
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]
        name = self._word_at(d, line, col)
        if not name:
            return
        c = self._client_for(d, start=False)

        def by_words():
            # open files as they are in their tabs (maybe unsaved), the rest of the project as it is on disk
            opened = {x.path for x in self._docs}
            rest = [h for h in (search_files(self._root, name, True, False, True) if self._root else []) if str(self._root / h["path"]) not in opened]
            hits, word = [], re.compile(rf"\b{re.escape(name)}\b")
            for x in sorted(self._docs, key=lambda x: x.path != d.path):
                if x.binary or (self._root and not x.path.startswith(str(self._root)) and x is not d) or name not in x.text:
                    continue
                for n, l in enumerate(x.text.split("\n")):
                    if name in l:
                        hits += [{"path": x.path, "line": n, "col": m.start(), "length": len(name), "text": l[:400]} for m in itertools.islice(word.finditer(l), 50)]
                    if len(hits) >= 2000:                     # (plenty to read: a one-letter name in a huge file would be millions)
                        break
                if len(hits) >= 2000:
                    break
            self._show_refs(name, hits + rest, exact=False)
        if c and not c.up:                                         # still starting: ask once it's ready
            self._once_ready(c, lambda: self.references(i, line, col), by_words)
            return
        if not c or not c.caps.get("referencesProvider"):
            by_words()
            return
        self._push_changes()

        def got(result, error):
            if error or not result:
                by_words()
                return
            hits, texts = [], {}
            for loc in result:
                path = QUrl(loc.get("uri", "")).toLocalFile()
                start = (loc.get("range") or {}).get("start", {})
                ln, col0 = start.get("line", 0), start.get("character", 0)
                if path not in texts:
                    doc = next((x for x in self._docs if x.path == path), None)
                    try:
                        texts[path] = (doc.text if doc else Path(path).read_text(encoding="utf-8", errors="replace")).split("\n")
                    except OSError:
                        texts[path] = []
                lines = texts[path]
                hits.append({"path": path, "line": ln, "col": col0, "length": len(name), "text": lines[ln][:400] if ln < len(lines) else ""})
            self._show_refs(name, sorted(hits, key=lambda h: (h["path"] != d.path, h["path"], h["line"])), exact=True)
        c.request("textDocument/references", {"textDocument": {"uri": d.uri}, "position": {"line": line, "character": col}, "context": {"includeDeclaration": True}}, got)

    def _show_refs(self, name: str, hits: list, exact: bool) -> None:
        if self._root:                                       # shown like search results: paths inside the project are short
            for h in hits:
                try:
                    h["path"] = str(Path(h["path"]).relative_to(self._root)) if Path(h["path"]).is_absolute() else h["path"]
                except ValueError:
                    pass
        self._results, self._searching = hits, False
        n = len(hits)
        self._results_title = f"{n} reference{'' if n == 1 else 's'} to “{name}”" + ("" if exact else " (by name)")
        self.searchDone.emit()

    @Slot(int, int, int, str)
    def renameSymbol(self, i: int, line: int, col: int, new: str) -> None:
        """F2: rename the thing under the cursor everywhere it's used (the language server knows where; without one,
        whole words in this file)."""
        new = new.strip()
        if not 0 <= i < len(self._docs) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", new):
            self.said.emit("A name is letters, numbers and _, not starting with a number.", True)
            return
        d = self._docs[i]
        old = self._word_at(d, line, col)
        if not old or old == new:
            return
        c = self._client_for(d, start=False)

        def in_this_file():
            text, n = re.subn(rf"\b{re.escape(old)}\b", new, d.text)
            d.text = text
            d.version += 1
            self.textLoaded.emit(i)
            self.changed.emit()
            self.said.emit(f"Renamed {n} use{'s' if n != 1 else ''} in this file (no language helper to look further).", False)
        if c and not c.up:
            self._once_ready(c, lambda: self.renameSymbol(i, line, col, new), in_this_file)
            return
        if not c or not c.caps.get("renameProvider"):
            in_this_file()
            return
        self._push_changes()

        def got(result, error):
            if error or not result:
                if error:
                    self.said.emit(f"Couldn't rename: {str(error)[:160]}", True)
                    return
                in_this_file()
                return
            edits = {}
            for change in result.get("documentChanges") or []:
                if "textDocument" in change:
                    edits.setdefault(QUrl(change["textDocument"]["uri"]).toLocalFile(), []).extend(change.get("edits", []))
            for uri, es in (result.get("changes") or {}).items():
                edits.setdefault(QUrl(uri).toLocalFile(), []).extend(es)
            done = self.apply_edits(edits)
            self.said.emit(f"Renamed “{old}” to “{new}” in {done} file{'s' if done != 1 else ''}. Open files are changed but not saved.", False)
        c.request("textDocument/rename", {"textDocument": {"uri": d.uri}, "position": {"line": line, "character": col}, "newName": new}, got)

    def _once_ready(self, client, then, otherwise, wait: int = 8000) -> None:
        """Run `then` when a starting language server is ready, or `otherwise` if it takes too long."""
        done = []

        def go(fn):
            if done:
                return
            done.append(1)
            try:
                client.ready.disconnect(on_ready)
            except (RuntimeError, TypeError):
                pass
            fn()

        def on_ready():
            go(then)
        client.ready.connect(on_ready)
        QTimer.singleShot(wait, lambda: go(otherwise))

    def apply_edits(self, edits: dict) -> int:
        """LSP text edits per file: open files change in their tabs (unsaved); other files are rewritten on disk."""
        done = 0
        for path, es in edits.items():
            doc = next((x for x in self._docs if x.path == path), None)
            try:
                text = doc.text if doc else Path(path).read_text(encoding="utf-8")
            except OSError:
                continue
            lines = text.split("\n")
            offsets = [0]
            for l in lines:
                offsets.append(offsets[-1] + len(l) + 1)

            def at(p):
                return offsets[min(p["line"], len(lines))] + p["character"]
            for e in sorted(es, key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]), reverse=True):
                text = text[:at(e["range"]["start"])] + e["newText"] + text[at(e["range"]["end"]):]
            if doc:
                if not self._doc_edit(doc, [[at(e["range"]["start"]), at(e["range"]["end"]), e["newText"]] for e in es]):
                    doc.text = text
                    doc.version += 1
                    self.textLoaded.emit(self._docs.index(doc))
            else:
                try:
                    Path(path).write_text(text, encoding="utf-8")
                except OSError:
                    continue
            done += 1
        self.changed.emit()
        return done

    # ================================================================ round four
    def _doc_edit(self, d: Doc, edits: list, qt_offsets: bool = False, join: bool = False) -> bool:
        """Edits [[start, end, text]] made in an open tab's own document, all as one step of its undo. The editor
        shows them at once and tells the rest of Code through its usual way (the text changed)."""
        styler = getattr(d, "styler", None)
        doc = styler.document() if styler is not None else None
        if doc is None:
            return False
        base = d.text
        cur = QTextCursor(doc)
        if join:                                              # letters typed one after another: one undo step for the word
            cur.joinPreviousEditBlock()
        else:
            cur.beginEditBlock()
        for a, b, t in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
            a, b = (int(a), int(b)) if qt_offsets else (more.u16(base, int(a)), more.u16(base, int(b)))
            cur.setPosition(max(0, a))
            cur.setPosition(max(0, b), QTextCursor.KeepAnchor)
            cur.insertText(t)
        cur.endEditBlock()
        if d in self._docs:                                   # the editor says so too, but don't depend on it
            self.edit(self._docs.index(d), doc.toPlainText())
        return True

    def _edit_text(self, i: int, edits: list) -> None:
        """Change tab i by offsets into its text: undoably in its editor, or (no editor yet) in the text itself."""
        d = self._docs[i]
        if self._doc_edit(d, edits):
            return
        text = d.text
        for a, b, t in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
            text = text[:a] + t + text[b:]
        d.text = text
        d.version += 1
        self.textLoaded.emit(i)
        self.changed.emit()

    @Slot(int, "QVariantList", bool)
    def multiEdit(self, i: int, edits, join: bool = False) -> None:
        """Several cursors typing at once: one undo step for all of them (offsets as the editor counts them); a word
        typed at all of them is one step too."""
        if 0 <= i < len(self._docs):
            edits = [list(e) for e in (edits.toVariant() if hasattr(edits, "toVariant") else edits)]
            if any(len(e) != 3 for e in edits):
                return
            if not self._doc_edit(self._docs[i], edits, qt_offsets=True, join=join):
                self._edit_text(i, edits)

    # ---------------------------------------------------------------- snippets
    @Slot(int, str, str, result="QVariantMap")
    def expandSnippet(self, i: int, body: str, indent: str) -> dict:
        unit = self._unit(self._docs[i]) if 0 <= i < len(self._docs) else "    "
        return more.snippet_parse(body, unit, indent)

    def _with_snippets(self, d: Doc, line: int, col: int, items: list) -> list:
        lines = d.text.split("\n")
        here = lines[line][:max(0, col)] if 0 <= line < len(lines) else ""
        m = re.search(r"[A-Za-z_][A-Za-z0-9_]*$", here)
        prefix = m.group() if m else ""
        if not prefix or re.search(r"[.\w]$", here[:len(here) - len(prefix)]):   # not after a dot
            return items
        return more.snippet_items(d.lang, prefix) + items

    # ---------------------------------------------------------------- what a call wants
    @Slot(int, int, int)
    def signatureAt(self, i: int, line: int, col: int) -> None:
        """The function being called at the cursor, with the argument being typed: from the language server, or
        (Python, without one) from its def in an open file."""
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]
        c = self._client_for(d, start=False)

        def by_hand():
            lines = d.text.split("\n")
            before = "\n".join(lines[max(0, line - 20):line] + [lines[line][:max(0, col)] if 0 <= line < len(lines) else ""])[-4000:]
            depth, k, arg = 0, len(before) - 1, 0
            while k >= 0:
                ch = before[k]
                if ch in ")]}":
                    depth += 1
                elif ch in "([{":
                    if depth == 0:
                        break
                    depth -= 1
                elif ch == "," and depth == 0:
                    arg += 1
                k -= 1
            m = re.search(r"([A-Za-z_]\w*)\s*$", before[:max(0, k)])
            if k < 0 or before[k] != "(" or not m or d.lang != "Python":
                self.signature.emit(i, "", -1, -1, "")
                return
            name = m.group(1)
            for doc in [d] + [x for x in self._docs if x is not d and x.lang == "Python"]:
                dm = re.search(rf"^\s*(?:async\s+)?def\s+{name}\s*\(([^)]*)\)", doc.text, re.M)
                if dm:
                    params = [p.strip() for p in dm.group(1).split(",") if p.strip() and p.strip() not in ("self", "cls")]
                    label = f"{name}({', '.join(params)})"
                    if arg < len(params):
                        s = label.index(params[arg], len(name) + 1)
                        self.signature.emit(i, label, s, s + len(params[arg]), "")
                    else:
                        self.signature.emit(i, label, -1, -1, "")
                    return
            self.signature.emit(i, "", -1, -1, "")
        if not c or not c.up or not c.caps.get("signatureHelpProvider"):
            by_hand()
            return
        self._push_changes()

        def got(result, error):
            sigs = (result or {}).get("signatures") or []
            if error or not sigs:
                by_hand()
                return
            k = min(len(sigs) - 1, int(result.get("activeSignature") or 0))
            sig = sigs[k]
            label = sig.get("label", "")
            params = sig.get("parameters") or []
            p = int(sig.get("activeParameter", result.get("activeParameter") or 0) or 0)
            a = b = -1
            if 0 <= p < len(params):
                pl = params[p].get("label")
                if isinstance(pl, list) and len(pl) == 2:
                    a, b = int(pl[0]), int(pl[1])
                elif isinstance(pl, str) and pl in label:
                    a = label.index(pl, label.find("(") + 1 if "(" in label else 0)
                    b = a + len(pl)
            docs = sig.get("documentation") or ""
            if isinstance(docs, dict):
                docs = docs.get("value", "")
            self.signature.emit(i, label, a, b, str(docs)[:400])
        c.request("textDocument/signatureHelp", {"textDocument": {"uri": d.uri}, "position": {"line": line, "character": col}}, got)

    # ---------------------------------------------------------------- quick fixes
    def _project_modules(self) -> set:
        if not self._root:
            return set()
        out = set()
        for rel in self._active_files()[:20000]:
            p = Path(rel)
            if p.suffix == ".py" and p.stem != "__init__" and len(p.parts) <= 2:
                out.add(p.stem)
            elif p.name == "__init__.py" and len(p.parts) == 2:
                out.add(p.parts[0])
        return out

    @Slot(int, int, int)
    def quickFixes(self, i: int, line: int, col: int) -> None:
        """Ctrl+.: what can be done about the problems on this line (the language server's fixes and our own)."""
        if not 0 <= i < len(self._docs):
            return
        d = self._docs[i]
        own = more.python_fixes(d.text, d.problems, line, self._project_modules()) if d.lang == "Python" else []
        self._fixes = {"tab": i, "list": [dict(f, kind="own") for f in own]}
        c = self._client_for(d, start=False)
        here = [p for p in d.problems if p["line"] <= line <= p.get("endLine", p["line"])]
        if not c or not c.up or not c.caps.get("codeActionProvider"):
            self.fixesFound.emit(i, [{"title": f["title"]} for f in self._fixes["list"]])
            return
        self._push_changes()
        diags = [{"range": {"start": {"line": p["line"], "character": p["col"]}, "end": {"line": p["endLine"], "character": p["endCol"]}},
                  "severity": p["severity"], "message": p["message"], "source": p.get("source", "")} for p in here]
        end = len(d.text.split("\n")[line]) if line < len(d.text.split("\n")) else 0

        def got(result, error):
            for a in (result or []) if not error else []:
                if a.get("disabled"):
                    continue
                self._fixes["list"].append({"title": a.get("title", "Fix"), "kind": "lsp", "action": a})
            self.fixesFound.emit(i, [{"title": f["title"]} for f in self._fixes["list"]])
        c.request("textDocument/codeAction", {"textDocument": {"uri": d.uri}, "range": {"start": {"line": line, "character": 0}, "end": {"line": line, "character": end}},
                                              "context": {"diagnostics": diags, "triggerKind": 1}}, got)

    def _workspace_edit(self, edit: dict) -> int:
        edits = {}
        for change in edit.get("documentChanges") or []:
            if "textDocument" in change:
                edits.setdefault(QUrl(change["textDocument"]["uri"]).toLocalFile(), []).extend(change.get("edits", []))
        for uri, es in (edit.get("changes") or {}).items():
            edits.setdefault(QUrl(uri).toLocalFile(), []).extend(es)
        return self.apply_edits(edits)

    @Slot(int)
    def applyFix(self, k: int) -> None:
        fx = getattr(self, "_fixes", None)
        if not fx or not 0 <= k < len(fx["list"]) or not 0 <= fx["tab"] < len(self._docs):
            return
        f, i = fx["list"][k], fx["tab"]
        d = self._docs[i]
        if f["kind"] == "own":
            self._edit_text(i, more.edits_to_offsets(d.text, f["edits"]))
            return
        a = f["action"]
        if a.get("edit"):
            self._workspace_edit(a["edit"])
        cmd = a.get("command") if isinstance(a.get("command"), dict) else (a if "command" in a and isinstance(a.get("command"), str) else None)
        c = self._client_for(d, start=False)
        if cmd and c:
            c.request("workspace/executeCommand", {"command": cmd["command"], "arguments": cmd.get("arguments") or []}, lambda r, e: None)

    # ---------------------------------------------------------------- merge conflicts
    @Slot(int, result="QVariantList")
    def conflictsOf(self, i: int) -> list:
        return more.conflicts(self._docs[i].text) if 0 <= i < len(self._docs) and "<<<<<<<" in self._docs[i].text else []

    @Slot(int, int, str)
    def resolveConflict(self, i: int, k: int, which: str) -> None:
        """Settle conflict k (or all of them, k < 0): keep ours, theirs or both. One undo step."""
        if not 0 <= i < len(self._docs) or which not in ("ours", "theirs", "both"):
            return
        d = self._docs[i]
        found = more.conflicts(d.text)
        lines = d.text.split("\n")
        starts = [0]
        for l in lines:
            starts.append(starts[-1] + len(l) + 1)
        edits = []
        for n, c in enumerate(found):
            if k >= 0 and n != k:
                continue
            sides = [c["ours"]] if which == "ours" else [c["theirs"]] if which == "theirs" else [c["ours"], c["theirs"]]
            keep = "\n".join(x for x in sides if x != "")
            a, b = starts[c["start"]], min(len(d.text), starts[c["end"] + 1])
            body = keep + ("\n" if keep and b > starts[c["end"]] + len(lines[c["end"]]) else "")
            edits.append([a, b, body])
        if edits:
            self._edit_text(i, edits)
            left = len(more.conflicts(d.text))
            if not left:
                self.said.emit("No conflicts left: save it, then mark it resolved.", False)

    @Slot(str, result=str)
    def markResolved(self, rel: str) -> str:
        """Tell Git a conflicted file is settled (it's added to the commit)."""
        d = next((x for x in self._docs if os.path.relpath(x.path, self._root) == rel), None) if self._root else None
        if d and "<<<<<<<" in d.text and more.conflicts(d.text):
            return "It still has conflicts in it."
        if d and d.dirty:
            i = self._docs.index(d)
            got = self.save(i, False)
            if got:
                return "Save it first."
        return self._git_do("add", "--", rel, then_say=f"{Path(rel).name} marked resolved.")

    # ---------------------------------------------------------------- the outline and sticky scroll
    @Slot(int, result="QVariantList")
    def outline(self, i: int) -> list:
        if not 0 <= i < len(self._docs):
            return []
        return more.scopes(self._docs[i].text, self.symbols(i))

    @Slot(int, int, result="QVariantList")
    def crumbsAt(self, i: int, line: int) -> list:
        """Where the cursor is, as the scopes around it (outermost first): Shop › add."""
        if not 0 <= i < len(self._docs) or self._docs[i].binary:
            return []
        d = self._docs[i]
        key = (d.version, i)
        if getattr(self, "_scoped_key", None) != key:
            self._scoped_key, self._scoped = key, self.outline(i)
        inside = [sc for sc in self._scoped if sc["line"] <= line <= sc["end"]]
        inside.sort(key=lambda sc: (sc["indent"], sc["line"]))
        return [{"name": sc["name"], "kind": sc.get("kind", ""), "line": sc["line"]} for sc in inside][-4:]

    @Slot(int, int, result="QVariantList")
    def stickyAt(self, i: int, line: int) -> list:
        """The lines that open the scopes the top line of the view is in (pinned at the editor's top), leaving out
        a scope that ends before the line that would show beneath them."""
        if not 0 <= i < len(self._docs):
            return []
        d = self._docs[i]
        key = (d.version, i)
        if getattr(self, "_scoped_key", None) != key:
            self._scoped_key, self._scoped = key, self.outline(i)
        lines = d.text.split("\n")
        keep = []
        for sc in more.enclosing(self._scoped, line):        # a scope that ends before the line that would show under it goes
            if sc["end"] >= line + len(keep) + 1:
                keep.append(sc)
        return [{"line": sc["line"], "text": lines[sc["line"]].rstrip()} for sc in keep][-4:]

    # ---------------------------------------------------------------- the project's own rules (.editorconfig)
    def _config(self, d: Doc) -> dict:
        """The rules for this file, in .editorconfig's words: Code's settings (the project's .vscode/settings.json
        over the user's, the language's block first), then the project's .editorconfig over those."""
        ids = vsc.vs_ids_for(d.lang, LANGS) if d.lang else ()
        get = lambda key: vsc.value(key, self._user, self._proj, ids)                     # noqa: E731
        cfg = {"trim_trailing_whitespace": "true" if get("files.trimTrailingWhitespace") else "false", "insert_final_newline": "true" if get("files.insertFinalNewline") else "false",
               "format_on_save": "true" if get("editor.formatOnSave") else "false", "tab_width": str(get("editor.tabSize"))}
        cfg.update({k: v for k, v in vsc.editor_config(self._proj, ids).items() if k in ("end_of_line",)})
        try:
            own = more.editorconfig_for(d.path) if not d.path.startswith("untitled:") else {}
        except (OSError, ValueError, RecursionError):
            own = {}
        cfg["_own"], cfg["_file"] = bool(own.get("indent_style") or own.get("indent_size")), bool(own)
        cfg.update(own)
        return cfg

    def _unit(self, d: Doc) -> str:
        """What one level of indentation is in this file: what the project's .editorconfig says, else what the file
        already does (unless told not to look), else the setting: so many spaces, or a tab."""
        cfg = self._config(d)
        if cfg.get("_own"):
            unit = more.editorconfig_unit(cfg)
            if unit:
                return unit
        found = indent_of(d.text) if self.setting("editor.detectIndentation", d) else ""
        return found or (" " * int(self.setting("editor.tabSize", d)) if self.setting("editor.insertSpaces", d) else "\t")

    def _tab_width(self, d: Doc) -> int:
        cfg = self._config(d)
        try:
            w = int(cfg.get("tab_width") or (cfg.get("indent_size") if cfg.get("indent_size") != "tab" else 0) or 4)
            return w if 1 <= w <= 16 else 4
        except ValueError:
            return 4

    # ---------------------------------------------------------------- tidy when saving
    def _tidy_before_save(self, i: int) -> None:
        d = self._docs[i]
        cfg = self._config(d)
        trim, final = cfg.get("trim_trailing_whitespace") == "true", cfg.get("insert_final_newline") == "true"
        if (trim or final) and not d.read_only and not d.binary:
            tidy = more.trim_text(d.text, d.lang, trim, final)
            if tidy != d.text:
                # the smallest change: only the lines that differ, so the cursor and undo stay where they are
                old, new = d.text.split("\n"), tidy.split("\n")
                edits, starts = [], [0]
                for l in old:
                    starts.append(starts[-1] + len(l) + 1)
                for k in range(min(len(old), len(new))):
                    if old[k] != new[k]:
                        edits.append([starts[k], starts[k] + len(old[k]), new[k]])
                if len(new) > len(old):
                    edits.append([len(d.text), len(d.text), "\n" + "\n".join(new[len(old):]) if d.text else "\n".join(new[len(old):])])
                elif len(new) < len(old):
                    edits.append([starts[len(new)] - 1, len(d.text), ""])
                self._edit_text(i, edits)

    @Slot(str, bool)
    def setOption(self, key: str, on: bool) -> None:
        for name in {"formatOnSave": ("editor.formatOnSave",), "trimOnSave": ("files.trimTrailingWhitespace", "files.insertFinalNewline"),
                     "guides": ("editor.guides.indentation",), "occurrences": ("editor.occurrencesHighlight",)}.get(key, ()):
            self.setSetting(name, bool(on))

    options = Property("QVariantMap", lambda self: {"formatOnSave": bool(self.setting("editor.formatOnSave")), "trimOnSave": bool(self.setting("files.trimTrailingWhitespace")),
                                                    "guides": bool(self.setting("editor.guides.indentation")), "occurrences": bool(self.setting("editor.occurrencesHighlight")),
                                                    "sticky": bool(self.setting("editor.stickyScroll.enabled")), "folding": bool(self.setting("editor.folding")),
                                                    "inlay": bool(self.setting("editor.inlayHints.enabled")), "rulers": self.setting("editor.rulers"),
                                                    "autoSave": self.setting("files.autoSave"), "history": bool(self.setting("huginn.localHistory")),
                                                    "keymap": self.setting("huginn.keymap"), "zenNoNumbers": bool(self.setting("zenMode.hideLineNumbers"))},
                       notify=changed)

    # ---------------------------------------------------------------- the minimap
    @Slot(bool)
    def setMinimap(self, on: bool) -> None:
        self._set_user("editor.minimap.enabled", bool(on))
        self._keep()
        self.changed.emit()

    # ---------------------------------------------------------------- debugging
    def _dbg_changed(self) -> None:
        pass

    def _landed(self, path: str, line: int) -> None:
        """The program stopped here: show the file at that line."""
        if not path or not Path(path).exists():
            return
        i = next((k for k, d in enumerate(self._docs) if d.path == path), -1)
        if i < 0:
            self.openFile(path, True, line, 0)
        else:
            self.select(i)
            self.jump.emit(i, line, 0)

    @Slot(int, int)
    def toggleBreakpoint(self, i: int, line: int) -> None:
        if 0 <= i < len(self._docs) and self._docs[i].path:
            self._dbg.toggle(self._docs[i].path, line)
            self._keep()
            self.changed.emit()

    @Slot(int, result="QVariantList")
    def breakpointsOf(self, i: int) -> list:
        return self._dbg.lines_for(self._docs[i].path) if 0 <= i < len(self._docs) else []

    @Slot(str)
    def startDebug(self, program: str = "") -> None:
        """F5: run the current file (or the project's program) under the debugger. Asks for the program once for
        compiled languages (Code guesses the newest one in the build folders)."""
        if self._dbg.active:
            self._dbg.resume()
            return
        chosen = next((c["name"] for c in self._get_launches() if c["chosen"]), "") if not program else ""
        if chosen:
            self.startLaunch(chosen)
            return
        d = self._docs[self._at] if 0 <= self._at < len(self._docs) else None
        if d is None:
            self.said.emit("Open the file to debug first.", True)
            return
        self.saveAll()
        root = self._root or Path(d.path).parent
        if program:
            try:
                (root / ".huginn-debug").write_text(program + "\n", encoding="utf-8")
            except OSError:
                pass
        program = program or hd.saved_program(root)
        try:
            argv, launch, name = hd.adapter_for(d.lang, d.path, root, program)
        except LookupError:
            self.askProgram.emit(hd.guess_program(root))
            return
        except ValueError as err:
            self.said.emit(str(err), True)
            return
        if self._demo:
            self.said.emit(f"Would debug {Path(d.path).name} with {name}.", False)
            return
        self._debug_start(argv, launch, name, str(root))

    def _debug_start(self, argv: list, launch: dict, name: str, cwd: str, request: str = "launch", what: str = "") -> None:
        """Start the debugger where the project runs: here, or on the other computer / in the container, where the
        adapter itself is run (so the program, its libraries and its debugger are all the same machine's) and only
        its conversation comes here."""
        door, where, mount = self._place()
        if not where:
            self._dbg.start(argv, launch, name, cwd, request, what)
            return
        there, here = self._place_paths()
        tool = "gdb" if name == "GDB" else "python3"
        code, _out = door.probe(where, "command -v gdb >/dev/null" if tool == "gdb" else "python3 -c 'import debugpy'")
        place = f"in the container “{where['label']}”" if door is hc else f"on {where['spec']}"
        if code == 255:
            self.said.emit(f"Couldn't reach the debugger {place}." + ("" if door is hc else " Is it still connected? (Code doesn't type passwords: the connection made in the terminal is the one reused.)"), True)
            return
        if code != 0:
            self.said.emit((f"Debugging {place} needs GDB 14 or later there (the gdb package)." if tool == "gdb" else f"Debugging Python {place} needs debugpy there (python3-debugpy, or pip install debugpy)."), True)
            return
        launch = dict(launch)
        for key in ("program", "cwd"):
            if isinstance(launch.get(key), str) and launch[key]:
                launch[key] = there(launch[key]) or launch[key]
        if isinstance(launch.get("args"), list):
            launch["args"] = [there(a) if isinstance(a, str) and a.startswith(str(mount)) else a for a in launch["args"]]
        remote_argv = ["gdb", "-q", "-i", "dap"] if tool == "gdb" else ["python3", "-m", "debugpy.adapter"]
        self._dbg.start(door.adapter_argv(where, remote_argv, there(cwd) if cwd else ""), launch, name, str(Path.home()), request,
                        (what or Path(str(launch.get("program", ""))).name) + f" ({place})", paths=(there, here))

    askProgram = Signal(str)

    # ---------------------------------------------------------------- one Code at a time
    def listen(self, path: str = "") -> bool:
        from PySide6.QtNetwork import QLocalServer, QLocalSocket
        name = f"huginn-code-{os.getuid()}"
        probe = QLocalSocket()
        probe.connectToServer(name)
        if probe.waitForConnected(300):
            probe.write(("open\n" + (str(Path(path).expanduser().resolve()) if path else "")).encode("utf-8"))
            probe.waitForBytesWritten(1000)
            probe.disconnectFromServer()
            return False
        QLocalServer.removeServer(name)
        self._door = QLocalServer(self)
        self._door.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._door.listen(name)

        def came():
            sock = self._door.nextPendingConnection()

            def read():
                msg = bytes(sock.readAll()).decode("utf-8", "replace")
                target = msg.split("\n", 1)[1].strip() if "\n" in msg else ""
                if target:
                    if Path(target).is_dir():
                        self.openFolder(target)
                    else:
                        self.openFile(target)
                self.shown.emit()
            sock.readyRead.connect(read)
        self._door.newConnection.connect(came)
        return True

    def leaving(self) -> None:
        self._dbg.stop(quiet=True)
        self._keep()
        for s in self._servers.values():
            if s:
                s.stop()
        if self._term is not None:
            self._term.stop()


class MinimapProvider(QQuickImageProvider):
    """image://minimap/<tab>/<version>: the whole file drawn small, a line every two pixels, words as little bars,
    comments and strings in their own colours: for seeing where you are in a long file."""

    def __init__(self, code: "Code"):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.code = code

    def requestImage(self, ident, size, requested):
        try:
            i = int(ident.split("/")[0])
            d = self.code._docs[i]
        except (ValueError, IndexError):
            return QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
        lines = d.text.split("\n")[:6000]
        w, step = 120, 2
        img = QImage(w, max(2, len(lines) * step), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        info = LANGS.get(d.lang)
        comment = info[1] if info else ""
        plain, faint, green, orange = QColor(170, 176, 190, 150), QColor(170, 176, 190, 90), QColor(110, 190, 120, 170), QColor(230, 160, 90, 170)
        p = QPainter(img)
        for n, line in enumerate(lines):
            text = line.expandtabs(4)
            stripped = text.lstrip()
            if not stripped:
                continue
            ink = green if comment and stripped.startswith(comment) else plain
            x = len(text) - len(stripped)
            for m in re.finditer(r"\S+", text[:w]):
                word = m.group()
                c = orange if word[:1] in "\"'`" else ink if ink is green or not word[:1].isalpha() or len(word) > 2 else faint
                p.fillRect(m.start(), n * step, len(word), step - 1 if step > 1 else 1, c)
            del x
        p.end()
        if size is not None:
            size.setWidth(img.width())
            size.setHeight(img.height())
        return img
