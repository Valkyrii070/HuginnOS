"""The shell's windows are layer-shell surfaces through Huginn's own QML module, org.huginn.layershell (built from
qt/layershell into the image, and carried ready-built by updates for the same Qt). A system whose update couldn't
bring it (built for another Qt) still has KDE's layer-shell-qt from before: then a stand-in module of the same name,
which is KDE's (layershell-fallback/), keeps the shell, the lock screen and the sign-in screen working.

    use(engine)        before engine.load(): add the stand-in only when the real module isn't there
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent


def use(engine) -> bool:
    """True when the stand-in was added."""
    if any((Path(d) / "org" / "huginn" / "layershell" / "qmldir").is_file() for d in engine.importPathList()):
        return False
    engine.addImportPath(str(HERE / "layershell-fallback"))
    return True
