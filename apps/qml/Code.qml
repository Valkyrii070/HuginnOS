import QtQuick

// Code, "the workbench": the project down the left in one tall island (files, search, Git, problems), the open
// files as tabs floating across the top, and the code itself on a dark, quiet slab that takes up the rest. The
// terminal slides up under the slab; the status runs along the bottom edge. Everything has a key, and the palette
// (Ctrl+P, or Ctrl+Shift+P for every command) reaches all of it.
GlassWindow {
    id: win
    title: "Code"; heading: Backend.rootName; width: 1280; height: 820; minimumWidth: 900; minimumHeight: 560; glow: "left"
    visible: true
    property string panel: "files"
    property bool side: true
    // ---- zen mode: nothing but the code (the side panel, tabs, tools, terminal and status come back when you leave it)
    property bool zen: false
    property var zenWas: ({})
    function toggleZen() {
        if (!zen) { zenWas = { side: side, term: term }; side = false; term = false; zen = true }
        else { zen = false; side = !!zenWas.side; term = !!zenWas.term }
        var v = view(); if (v) v.focusEditor()
    }
    readonly property int curTab: Backend.current
    onCurTabChanged: Backend.autoSave("focus")
    onActiveChanged: if (!active) Backend.autoSave("focus")
    property bool term: false
    property string bottom: "terminal"                     // what the bottom panel shows: terminal or debug
    property bool split: false                             // two editors side by side
    property bool blameOn: false                           // who changed each line, beside the code
    property string gitView: "changes"                     // changes | history
    property var historyRows: []
    property int otherTab: -1                              // the tab in the pane that hasn't got the keyboard
    property int pane: 0                                   // which side has the keyboard: 0 left, 1 right
    property int lastCurrent: -1
    readonly property var dbg: Backend.debug ? Backend.debug : idleDbg
    QtObject { id: idleDbg                                   // stands in while the window closes
        signal changed()
        property string state: "idle"; property bool active: false; property string reason: ""; property string adapter: ""
        property var frames: []; property int frame: -1; property var variables: []; property var output: []
        property string whereFile: ""; property int whereLine: -1
        function resume() {} function pause() {} function stepOver() {} function stepIn() {} function stepOut() {} function restart() {} function stop() {}
        function selectFrame(f) {} function expand(r) {} function evaluate(x) {} function clearConsole() {} }
    property var sheet: null
    property bool palOpen: false
    property bool finding: false
    property bool replacing: false
    property var comp: []
    property var compAll: []
    property int compAt: 0
    property string compPrefix: ""
    property string tip: ""
    property var sig: null                         // the call being typed: {label, a, b, doc}
    property var fixMenu: null                     // quick fixes for the cursor's line: {items, k}
    property bool mdPreview: false                 // Markdown shown as it reads, beside its text
    property var outlineRows: []
    property var matches: []
    property int matchAt: -1
    property int curLine: 1
    property int curCol: 1
    property var menuFor: null
    property string browseAt: Backend.home
    readonly property int sideW: side ? 280 : 0
    readonly property string mono: Qt.fontFamilies().indexOf(Theme.t.fontMono) >= 0 ? Theme.t.fontMono : Qt.fontFamilies().indexOf("DejaVu Sans Mono") >= 0 ? "DejaVu Sans Mono" : "monospace"
    readonly property var tab: Backend.current >= 0 && Backend.current < Backend.tabs.length ? Backend.tabs[Backend.current] : null
    // A VS Code colour theme you imported (Backend.theme) takes the editor's colours; without one, the system's light and dark.
    readonly property var vsTheme: Backend.theme
    readonly property bool themed: !!vsTheme.name
    readonly property bool codeDark: themed ? !!vsTheme.dark : Theme.t.dark
    readonly property color slab: themed && vsTheme.paper ? vsTheme.paper : Theme.t.dark ? "#111318" : "#FCFCFE"
    readonly property color codeInk: themed && vsTheme.ink ? vsTheme.ink : themed ? (codeDark ? "#D4D4D4" : "#1F2328") : Theme.t.text
    readonly property color gutterInk: themed && vsTheme.gutter ? vsTheme.gutter : codeDark ? "#5A6170" : "#A3A9B4"
    readonly property color lineGlow: themed && vsTheme.line ? vsTheme.line : themed ? Qt.alpha(codeInk, 0.07) : Theme.t.dark ? "#1A1D24" : "#F1F2F8"
    readonly property color addInk: "#3FB950"
    readonly property color modInk: "#4D8DFF"
    readonly property color delInk: "#F85149"
    readonly property string unit: Backend.status.indentText || "    "
    function colours() {
        var d = codeDark, t = themed ? vsTheme : ({})
        return { key: t.key || (d ? "#C792EA" : "#7C3AED"), comment: t.comment || (d ? "#6B7385" : "#8A909C"), string: t.string || (d ? "#A5D6A7" : "#2E7D32"),
                 number: t.number || (d ? "#F78C6C" : "#C2410C"), type: t.type || (d ? "#7FDBCA" : "#0F766E"), func: t.func || (d ? "#82AAFF" : "#1D4ED8"),
                 deco: t.deco || (d ? "#FF8FA3" : "#BE185D"), head: t.head || Theme.t.accent }
    }
    function view() { return docs.itemAt(Backend.current) }
    function ask(kind, extra) { var s = extra || {}; s.kind = kind; sheet = s }
    // Huginn AI (Settings › AI): explain, fix, change or write code, on what's selected or else the whole file
    readonly property bool aiOn: aiPanel.on("code")
    readonly property bool aiInline: aiOn && !!AI.state.inline                  // Huginn AI suggests code as you type
    property var crumbs: []                                                     // the scopes the cursor is in: Shop › add
    function aiCode(mode, asked) {
        var v = view()
        if (!v || !win.tab) { toast.say("Open a file first.", false); return }
        var r = v.selRange(), all = r[0] === r[1], text = v.allText()
        var a = all ? 0 : r[0], b = all ? text.length : r[1]
        if (mode === "write") { a = r[0]; b = r[1] }
        var orig = text.slice(a, b), tabNo = Backend.current, lang = win.tab.lang || ""
        if (mode !== "write" && orig.trim() === "") { toast.say("There's no code here yet.", false); return }
        function lineOf(pos) { return text.slice(0, pos).split("\n").length - 1 }
        var problem = ""
        if (mode === "fix") {
            var l0 = lineOf(a), l1 = lineOf(b)
            problem = Backend.problems.filter(function (p) { return p.tab === tabNo && (all || (p.line >= l0 && p.line <= l1)) }).slice(0, 6)
                      .map(function (p) { return "line " + (p.line - (all ? 0 : l0) + 1) + ": " + p.message }).join("; ")
        }
        function put(t) {
            var now = win.view()
            if (Backend.current !== tabNo || !now || now.allText().slice(a, b) !== orig) { aiPanel.copyIt(); toast.say("The file changed meanwhile, so the code is copied: paste it where you want it.", false); return }
            now.replaceRange(a, b, t); now.selectRange(a, a + t.length); now.focusEditor()
        }
        var task = { explain: "explain-code", fix: "fix-code", edit: "edit-code", write: "write-code" }[mode]
        var job = { task: task, text: mode === "write" ? asked : orig, extra: { lang: lang, problem: problem, ask: asked || "" }, mono: mode !== "explain",
                    heading: { explain: "What it does", fix: "Fixed", edit: "Changed", write: "Written" }[mode] }
        if (mode !== "explain") { job.accept = mode === "write" ? (all ? "Insert" : "Replace the Selection") : all ? "Replace the File" : "Replace"; job.onAccept = put }
        aiPanel.run(job)
    }
    // New File: in an open folder, a name (its ending picks the language); with no folder, which language
    function newFile() { if (Backend.root) ask("new", { folder: Backend.root, dir: false }); else ask("langs", { mode: "new" }) }
    function closeTab(i) { if (Backend.close(i, false) === "dirty") ask("dirty", { tab: i, name: Backend.tabs[i].name }) }
    function save() { if (Backend.current < 0) return; if (Backend.save(Backend.current, false) === "changed") ask("clash", { tab: Backend.current }) }
    function openPalette(prefix) { palBox.text = prefix; palList.model = paletteRows(prefix); palOpen = true; palBox.forceActiveFocus(); palBox.cursorPosition = prefix.length; palList.currentIndex = 0 }
    function closeOverlays() { palOpen = false; comp = []; tip = ""; sig = null; fixMenu = null; menuFor = null; var v = view(); if (v) v.focusEditor() }
    function branches() { if (Backend.isGit) ask("branches"); else toast.say("This folder isn't a Git project.", false) }
    function toBracket() { var v = view(); if (!v) return; v.findPair(); if (v.pair.length === 2) { var to = v.pair[1]; v.cursorTo(to + (to > v.pair[0] ? 1 : 0)) } }
    function refreshOutline() { outlineRows = Backend.current >= 0 ? Backend.outline(Backend.current) : [] }
    function showPanel(p) { side = true; panel = p; if (p === "outline") refreshOutline(); if (p === "search") Qt.callLater(function () { searchBox.forceActiveFocus() }); if (p === "tests" && Backend.tests.length === 0 && Backend.testBusy === "") Backend.discoverTests() }
    function syncDocs() {
        var tabs = Backend.tabs, i, j, k
        for (i = docModel.count - 1; i >= 0; i--) {
            var p = docModel.get(i).path, keep = false
            for (j = 0; j < tabs.length; j++) if (tabs[j].path === p) keep = true
            if (!keep) docModel.remove(i)
        }
        for (j = 0; j < tabs.length; j++) {
            var at = -1
            for (k = j; k < docModel.count; k++) if (docModel.get(k).path === tabs[j].path) { at = k; break }
            if (at < 0) docModel.insert(j, { path: tabs[j].path })
            else if (at !== j) docModel.move(at, j, 1)
        }
    }
    readonly property var commands: [
        { name: "Save", key: "Ctrl+S", run: function () { win.save() } },
        { name: "Save All", key: "Ctrl+Alt+S", run: function () { toast.say(Backend.saveAll() + " saved", false) } },
        { name: "Close Tab", key: "Ctrl+W", run: function () { if (Backend.current >= 0) win.closeTab(Backend.current) } },
        { name: "Quick Open a File", key: "Ctrl+P", run: function () { win.openPalette("") } },
        { name: "Go to Line…", key: "Ctrl+G", run: function () { win.openPalette(":") } },
        { name: "Go Back", key: "Alt+Left", run: function () { win.travel(-1) } },
        { name: "Go Forward", key: "Alt+Right", run: function () { win.travel(1) } },
        { name: "Reopen Closed File", key: "Ctrl+Alt+W", run: function () { Backend.reopenClosed() } },
        { name: (Backend.options.guides ? "Hide Indent Guides" : "Show Indent Guides"), key: "", run: function () { Backend.setOption("guides", !Backend.options.guides) } },
        { name: (Backend.options.occurrences ? "Stop Highlighting the Word Under the Cursor" : "Highlight the Word Under the Cursor"), key: "", run: function () { Backend.setOption("occurrences", !Backend.options.occurrences) } },
        { name: "Go to Symbol…", key: "Ctrl+Shift+O", run: function () { win.openPalette("@") } },
        { name: "Go to Definition", key: "F12", run: function () { var v = win.view(); if (v) v.definition() } },
        { name: "Show Information Here", key: "Ctrl+I", run: function () { var v = win.view(); if (v) v.hover() } },
        { name: "Suggest", key: "Ctrl+Space", run: function () { var v = win.view(); if (v) v.suggest() } },
        { name: "Find", key: "Ctrl+F", run: function () { win.startFind(false) } },
        { name: "Replace", key: "Ctrl+H", run: function () { win.startFind(true) } },
        { name: "Search the Project", key: "Ctrl+Shift+F", run: function () { win.showPanel("search") } },
        { name: "Show Files", key: "Ctrl+Shift+E", run: function () { win.showPanel("files") } },
        { name: "Show Changes (Git)", key: "Ctrl+Shift+G", run: function () { win.showPanel("git") } },
        { name: "Show Problems", key: "Ctrl+Shift+M", run: function () { win.showPanel("problems") } },
        { name: "Show Tests", key: "Ctrl+Shift+T", run: function () { win.showPanel("tests") } },
        { name: "Run All Tests", key: "", run: function () { win.showPanel("tests"); Backend.runTests([]) } },
        { name: "Git: Blame (Who Changed Each Line)", key: "Ctrl+Alt+B", run: function () { win.blameOn = !win.blameOn } },
        { name: "Git: History", key: "", run: function () { win.showPanel("git"); win.gitView = "history"; win.historyRows = Backend.history("") } },
        { name: "Git: This File's History", key: "", run: function () { var v = win.view(); if (v) { win.showPanel("git"); win.gitView = "history"; win.historyRows = Backend.history(Backend.relOf ? Backend.relOf(Backend.current) : "") } } },
        { name: "Toggle the Side Panel", key: "Ctrl+B", run: function () { win.side = !win.side } },
        { name: "Toggle the Terminal", key: "Ctrl+`", run: function () { win.toggleTerm() } },
        { name: "Start Debugging / Continue", key: "F5", run: function () { win.debugIt() } },
        { name: "Run Without Debugging", key: "Ctrl+F5", run: function () { win.runIt() } },
        { name: "Stop Debugging", key: "Shift+F5", run: function () { win.dbg.stop() } },
        { name: "Step Over", key: "F10", run: function () { win.dbg.stepOver() } },
        { name: "Step Into", key: "F11", run: function () { win.dbg.stepIn() } },
        { name: "Step Out", key: "Shift+F11", run: function () { win.dbg.stepOut() } },
        { name: "Toggle Breakpoint", key: "F9", run: function () { var v = win.view(); if (v) { var lc = v.lineCol(); Backend.toggleBreakpoint(Backend.current, lc[0]) } } },
        { name: "Rename Symbol…", key: "F2", run: function () { var v = win.view(); if (v) v.renameHere() } },
        { name: "Find All References", key: "Shift+F12", run: function () { var v = win.view(); if (v) v.referencesHere() } },
        { name: "Split the Editor", key: "Ctrl+\\", run: function () { win.toggleSplit() } },
        { name: "Toggle the Minimap", key: "", run: function () { Backend.setMinimap(!Backend.minimap) } },
        { name: "Show the Debug Console", key: "", run: function () { win.bottom = "debug"; win.term = true } },
        { name: "Extensions…", key: "", run: function () { win.ask("extensions") } },
        { name: "Workspace: Add a Folder…", key: "", run: function () { win.browseAt = Backend.root ? Backend.root.replace(/\/[^\/]+\/?$/, "") || "/" : Backend.home; win.ask("open", { add: true }) } },
        { name: "Workspace: Save as a .code-workspace File…", key: "", run: function () { if (Backend.folders.length) win.ask("space", { now: Backend.workspaceFile || (Backend.folders[0].path + ".code-workspace") }); else toast.say("One folder isn't a workspace: add another first.", true) } },
        { name: "Debug: Attach to a Running Program…", key: "", run: function () { win.attachAsk("") } },
        { name: "Debug: The Game in Godot (main scene)", key: "", run: function () { win.bottom = "debug"; win.term = true; Backend.debugGame("godot") }, when: function () { return Backend.gameDebug.godot } },
        { name: "Debug: The Scene Open in Godot's Editor", key: "", run: function () { win.bottom = "debug"; win.term = true; Backend.debugGame("godot-current") }, when: function () { return Backend.gameDebug.godot } },
        { name: "Debug: This Scene in Godot", key: "", run: function () { win.bottom = "debug"; win.term = true; Backend.debugGame("godot-scene") }, when: function () { return Backend.gameDebug.godot } },
        { name: "Debug: Unreal Editor with This Project", key: "", run: function () { win.bottom = "debug"; win.term = true; Backend.debugGame("unreal-editor") }, when: function () { return Backend.gameDebug.unreal } },
        { name: "Debug: The Game on Its Own (Unreal)", key: "", run: function () { win.bottom = "debug"; win.term = true; Backend.debugGame("unreal-game") }, when: function () { return Backend.gameDebug.unreal } },
        { name: "Container: Open This Project in Its Container…", key: "", run: function () { win.containerAsk() } },
        { name: "Container: Open a Shell Inside", key: "", run: function () { if (Backend.container.running) { win.bottom = "terminal"; win.term = true; Backend.containerShell() } else toast.say("No container is running for this project.", true) } },
        { name: "Container: Stop", key: "", run: function () { if (Backend.container.running || Backend.container.starting) Backend.containerStop(false); else toast.say("No container is running for this project.", true) } },
        { name: "Container: Stop and Remove (rebuilt at the next start)", key: "", run: function () { if (Backend.container.has) Backend.containerStop(true); else toast.say("This project has no devcontainer.json.", true) } },
        { name: "Remote: Open a Folder on Another Computer (SSH)…", key: "", run: function () { win.ask("remote", { now: "" }) } },
        { name: "Remote: Open a Shell There", key: "", run: function () { if (Backend.remote.spec) { win.bottom = "terminal"; win.term = true; Backend.remoteShell() } else toast.say("This project isn't on another computer.", true) } },
        { name: "Remote: Disconnect", key: "", run: function () { if (Backend.remote.spec) Backend.remoteDisconnect(); else toast.say("This project isn't on another computer.", true) } },
        { name: "Fold", key: "Ctrl+Shift+[", run: function () { var v = win.view(); if (v) v.foldHere(1) } },
        { name: "Unfold", key: "Ctrl+Shift+]", run: function () { var v = win.view(); if (v) v.foldHere(-1) } },
        { name: "Fold All", key: "", run: function () { if (Backend.current >= 0) Backend.foldAll(Backend.current) } },
        { name: "Unfold All", key: "", run: function () { if (Backend.current >= 0) Backend.unfoldAll(Backend.current) } },
        { name: "Zen Mode", key: "", run: function () { win.toggleZen() } },
        { name: "Peek at the Definition", key: "Alt+F12", run: function () { var v = win.view(); if (v) v.peek() } },
        { name: "Emmet: Expand the Abbreviation", key: "", run: function () { var v = win.view(); if (v) v.emmet() } },
        { name: "File History…", key: "", run: function () { if (Backend.current >= 0) win.ask("history", { tab: Backend.current, name: Backend.tabs[Backend.current].name, rows: Backend.historyOf(Backend.current) }) } },
        { name: "Show All Commands", key: "Ctrl+Shift+P", run: function () { win.openPalette(">") } },
        { name: "Settings…", key: "Ctrl+,", run: function () { win.ask("settings") } },
        { name: "Keyboard Shortcuts…", key: "", run: function () { win.ask("keys") } },
        { name: "Settings: Open settings.json", key: "", run: function () { Backend.openSettingsFile() } },
        { name: "Colour Theme: Import a VS Code Theme…", key: "", run: function () { win.ask("theme", { now: "" }) } },
        { name: "Colour Theme: Use the System's Colours", key: "", run: function () { Backend.clearTheme() } },
        { name: "VS Code: Bring My Snippets, Settings and Keys", key: "", run: function () { toast.say(Backend.importFromVSCode(), false) } },
        { name: "Build", key: "Ctrl+Shift+B", run: function () { win.buildIt() } },
        { name: "Build: Show Tasks and Output", key: "", run: function () { win.showBuild() } },
        { name: "Build: Run the Last Task Again", key: "", run: function () { win.showBuild(); win.bld.again() } },
        { name: "Build: Stop", key: "", run: function () { win.bld.stop() } },
        { name: "Build: Next Error", key: "F8", run: function () { win.bld.step(1) } },
        { name: "Build: Previous Error", key: "Shift+F8", run: function () { win.bld.step(-1) } },
        { name: "Build: Choose Unreal Engine's Folder…", key: "", run: function () { win.ask("unreal", { now: win.bld.unrealRoot || (Backend.home + "/UnrealEngine") }) } },
        { name: "Set the Run Command…", key: "", run: function () { win.ask("run", { now: Backend.runCommand() }) } },
        { name: "Format Document", key: "Ctrl+Shift+I", run: function () { if (Backend.current >= 0) Backend.format(Backend.current) } },
        { name: "Quick Fix…", key: "Ctrl+.", run: function () { var v = win.view(); if (v) v.fixHere() } },
        { name: "Add the Next Match to the Selection (another cursor)", key: "Ctrl+D", run: function () { var v = win.view(); if (v) v.addNext() } },
        { name: "Select Every Match (a cursor on each)", key: "Ctrl+Shift+L", run: function () { var v = win.view(); if (v) v.selectEvery() } },
        { name: "Add a Cursor Below", key: "Ctrl+Alt+Down", run: function () { var v = win.view(); if (v) v.addVertical(1) } },
        { name: "Add a Cursor Above", key: "Ctrl+Alt+Up", run: function () { var v = win.view(); if (v) v.addVertical(-1) } },
        { name: "Markdown: Show How It Reads", key: "Ctrl+Shift+V", run: function () { win.mdPreview = !win.mdPreview } },
        { name: "Show the Outline", key: "", run: function () { win.showPanel("outline") } },
        { name: (Backend.options.formatOnSave ? "Stop Formatting When Saving" : "Format When Saving"), key: "", run: function () { Backend.setOption("formatOnSave", !Backend.options.formatOnSave) } },
        { name: (Backend.options.trimOnSave ? "Stop Tidying Line Ends When Saving" : "Tidy Line Ends When Saving"), key: "", run: function () { Backend.setOption("trimOnSave", !Backend.options.trimOnSave) } },
        { name: "Merge: Keep Ours Everywhere in This File", key: "", run: function () { if (Backend.current >= 0) Backend.resolveConflict(Backend.current, -1, "ours") } },
        { name: "Merge: Keep Theirs Everywhere in This File", key: "", run: function () { if (Backend.current >= 0) Backend.resolveConflict(Backend.current, -1, "theirs") } },
        { name: "Comment or Uncomment Lines", key: "Ctrl+/", run: function () { var v = win.view(); if (v) v.toggleComment() } },
        { name: "Move Lines Up", key: "Alt+Up", run: function () { var v = win.view(); if (v) v.lineCmd("up") } },
        { name: "Move Lines Down", key: "Alt+Down", run: function () { var v = win.view(); if (v) v.lineCmd("down") } },
        { name: "Copy Lines Up", key: "Alt+Shift+Up", run: function () { var v = win.view(); if (v) v.lineCmd("copy_up") } },
        { name: "Copy Lines Down", key: "Alt+Shift+Down", run: function () { var v = win.view(); if (v) v.lineCmd("copy_down") } },
        { name: "Delete Lines", key: "Ctrl+Shift+K", run: function () { var v = win.view(); if (v) v.lineCmd("delete") } },
        { name: "Join Lines", key: "Ctrl+J", run: function () { var v = win.view(); if (v) v.lineCmd("join") } },
        { name: "Select the Line", key: "Ctrl+L", run: function () { var v = win.view(); if (v) v.lineCmd("select") } },
        { name: "New Line Below", key: "Ctrl+Enter", run: function () { var v = win.view(); if (v) v.lineCmd("below") } },
        { name: "New Line Above", key: "Ctrl+Shift+Enter", run: function () { var v = win.view(); if (v) v.lineCmd("above") } },
        { name: "Sort Lines", key: "", run: function () { var v = win.view(); if (v) v.lineCmd("sort") } },
        { name: "Sort Lines, Z to A", key: "", run: function () { var v = win.view(); if (v) v.lineCmd("sort_desc") } },
        { name: "Remove Repeated Lines", key: "", run: function () { var v = win.view(); if (v) v.lineCmd("unique") } },
        { name: "Make Upper Case", key: "", run: function () { var v = win.view(); if (v) v.lineCmd("upper") } },
        { name: "Make Lower Case", key: "", run: function () { var v = win.view(); if (v) v.lineCmd("lower") } },
        { name: "Make Title Case", key: "", run: function () { var v = win.view(); if (v) v.lineCmd("title") } },
        { name: "Go to the Next Change", key: "F7", run: function () { var v = win.view(); if (v) v.goChange(1) } },
        { name: "Go to the Previous Change", key: "Shift+F7", run: function () { var v = win.view(); if (v) v.goChange(-1) } },
        { name: "Put This Change Back", key: "", run: function () { var v = win.view(); if (v) v.putBack() } },
        { name: "Toggle Word Wrap", key: "Alt+Z", run: function () { Backend.setWrap(!Backend.wrap) } },
        { name: "Bigger Text", key: "Ctrl+=", run: function () { Backend.setSize(Backend.size + 1) } },
        { name: "Smaller Text", key: "Ctrl+-", run: function () { Backend.setSize(Backend.size - 1) } },
        { name: "New File", key: "Ctrl+N", run: function () { win.newFile() } },
        { name: "New File in a Language…", key: "", run: function () { win.ask("langs", { mode: "new" }) } },
        { name: "AI: Explain This Code", key: "", ai: true, run: function () { win.aiCode("explain", "") } },
        { name: "AI: Fix This Code", key: "", ai: true, run: function () { win.aiCode("fix", "") } },
        { name: "AI: Change This Code…", key: "", ai: true, run: function () { win.ask("aiask", { mode: "edit" }) } },
        { name: "Go to Matching Bracket", key: "Ctrl+Shift+\\", run: function () { win.toBracket() } },
        { name: "AI: Write Code…", key: "", ai: true, run: function () { win.ask("aiask", { mode: "write" }) } },
        { name: "AI: Suggest as I Type (On or Off)", key: "", ai: true, run: function () {
            var on = !AI.state.inline; AI.setInline(on)
            toast.say(on ? "Huginn AI suggests code when you pause, in grey: Tab takes it, Escape drops it." + (AI.state.provider === "local" ? "" : " Each pause is a request to " + (AI.state.label || "your service") + ".")
                         : "Huginn AI no longer suggests as you type.", false) } },
        { name: "Languages: Add Support…", key: "", run: function () { win.ask("langs", { mode: "manage" }) } },
        { name: "New Folder", key: "", run: function () { win.ask("new", { folder: Backend.root, dir: true }) } },
        { name: "Open Folder…", key: "Ctrl+O", run: function () { win.browseAt = Backend.root || Backend.home; win.ask("open") } },
        { name: "Close Folder", key: "", run: function () { Backend.closeFolder() } },
        { name: "Reload This File from Disk", key: "", run: function () { if (Backend.current >= 0) Backend.reload(Backend.current) } },
        { name: "Show This File in Files", key: "", run: function () { if (win.tab) Backend.reveal(win.tab.path) } },
        { name: "Git: Switch Branch…", key: "", run: function () { if (Backend.branch) win.ask("branches"); else toast.say("This folder isn't a Git repository yet.", false) } },
        { name: "Git: Start a Branch…", key: "", run: function () { if (Backend.branch) win.ask("branches"); else toast.say("This folder isn't a Git repository yet.", false) } },
        { name: "Git: Commit…", key: "", run: function () { win.showPanel("git"); commitBox.focusIn() } },
        { name: "Git: Stage Everything", key: "", run: function () { Backend.stageAll() } },
        { name: "Git: Pull", key: "", run: function () { Backend.sync("pull") } },
        { name: "Git: Push", key: "", run: function () { Backend.sync("push") } },
        { name: "Git: Pull, Then Push", key: "", run: function () { Backend.sync("sync") } },
        { name: "Git: Make This Folder a Repository", key: "", run: function () { Backend.initRepo() } }
    ]
    function toggleTerm() { term = !term; if (term) Qt.callLater(function () { termKeys.forceActiveFocus() }); else { var v = view(); if (v) v.focusEditor() } }
    readonly property var bld: Backend.build
    // ---- shortcuts you chose (Settings › Keyboard Shortcuts), and VS Code's when that keymap is on. A command's own
    // shortcut gives way when the command is given another, and when its keys are given to another command.
    readonly property var keyOver: Backend.keys
    property bool capturing: false                       // the next key press is being taken as a new shortcut
    readonly property var keyState: {
        var taken = {}, moved = {}, list = [], over = keyOver
        for (var n = 0; n < commands.length; n++) {
            var seq = over[commands[n].name]
            if (seq === undefined || seq.toLowerCase() === (commands[n].key || "").toLowerCase()) continue
            if (commands[n].key) moved[commands[n].key.toLowerCase()] = true
            if (seq) { taken[seq.toLowerCase()] = true; taken[seq.split(",")[0].trim().toLowerCase()] = true; list.push({ name: commands[n].name, seq: seq, n: n }) }
        }
        return { taken: taken, moved: moved, list: list }
    }
    function free(seq) { var k = seq.toLowerCase(); return !capturing && !keyState.taken[k] && !keyState.moved[k] }
    function keyOf(cmd) { var o = keyOver[cmd.name]; return o !== undefined ? o : cmd.key }
    function commandWith(seq, but) {                     // the command a shortcut runs now ("" when none)
        var k = seq.toLowerCase()
        for (var n = 0; n < commands.length; n++) if (commands[n].name !== but && (keyOf(commands[n]) || "").toLowerCase() === k) return commands[n].name
        return ""
    }
    Repeater { model: win.capturing ? [] : win.keyState.list
        Item { id: overKey; required property var modelData; Shortcut { sequence: overKey.modelData.seq; onActivated: win.commands[overKey.modelData.n].run() } } }
    function showBuild() { bottom = "build"; term = true; buildOut.follow = true }
    function buildIt() { showBuild(); bld.runDefault() }
    function runTask(id) { showBuild(); bld.run(id) }
    function runIt() { bottom = "terminal"; term = true; Backend.run(""); Qt.callLater(function () { termKeys.forceActiveFocus() }) }
    function attachAsk(config) { if (dbg.active) { toast.say("The debugger is busy. Stop it first.", true); return } ask("attach", { config: config || "" }) }
    function containerAsk() { var c = Backend.container
        if (!c.has) { toast.say("This project has no .devcontainer/devcontainer.json.", true); return }
        if (c.running) { toast.say("Already working in its container.", false); return }
        ask("container") }
    function debugIt() { if (dbg.active) { dbg.resume(); return } bottom = "debug"; term = true; Backend.startDebug("") }
    // ---- back and forward through the places you've been (a jump of more than a few lines, or to another file, is a place)
    property var trail: []
    property int trailAt: -1
    property bool trailBusy: false
    readonly property int tabW: Backend.status.tabWidth || 4
    function noteMove(path, line, col) {
        if (trailBusy || !path) return
        var cur = trailAt >= 0 ? trail[trailAt] : null
        if (cur && cur.path === path && Math.abs(cur.line - line) <= 8) { cur.line = line; cur.col = col; return }
        var t = trail.slice(0, trailAt + 1); t.push({ path: path, line: line, col: col })
        if (t.length > 80) t.shift()
        trail = t; trailAt = t.length - 1 }
    function travel(d) {
        var k = trailAt + d
        while (k >= 0 && k < trail.length && !Backend.fileThere(trail[k].path)) k += d      // (a file since deleted is stepped over)
        if (k < 0 || k >= trail.length) { toast.say(d < 0 ? "That's as far back as it goes." : "That's as far forward as it goes.", false); return }
        trailBusy = true; trailAt = k; trailRest.restart()
        Backend.openRel(trail[k].path, trail[k].line, trail[k].col) }
    Timer { id: trailRest; interval: 220; onTriggered: win.trailBusy = false }
    function toggleSplit() {
        if (split) { split = false; return }
        if (Backend.tabs.length < 2) { toast.say("Open another file to see two side by side.", false); return }
        otherTab = lastCurrent >= 0 && lastCurrent !== Backend.current && lastCurrent < Backend.tabs.length ? lastCurrent : (Backend.current + 1) % Backend.tabs.length
        pane = 0; split = true }
    Connections { target: Backend
        function onChanged() {
            if (Backend.current !== win.lastCurrent) {
                if (win.split && Backend.current === win.otherTab) win.otherTab = win.lastCurrent          // picked the other pane's tab: they swap
                win.lastCurrent = Backend.current }
            if (win.split && (win.otherTab < 0 || win.otherTab >= Backend.tabs.length || win.otherTab === Backend.current)) win.split = false }
        function onAskProgram(guess) { win.ask("debugprog", { now: guess }) }
        function onAskAttach(config) { win.attachAsk(config) }
        function onAskUnreal() { win.ask("unreal", { now: Backend.build.unrealRoot || (Backend.home + "/UnrealEngine") }) } }
    function startFind(rep) {
        finding = true; replacing = rep
        var v = view()
        if (v && v.selected() && v.selected().indexOf("\n") < 0) findBox.text = v.selected()
        findBox.forceActiveFocus(); findBox.selectAll(); refind()
    }
    function pattern() {
        var q = findBox.text
        if (!q) return null
        try {
            var src = matchRe.on ? q : q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
            if (matchWord.on) src = "\\b" + src + "\\b"
            return new RegExp(src, matchCase.on ? "g" : "gi")
        } catch (e) { return null }
    }
    function refind() {
        var v = view(), re = pattern(), out = []
        if (!v || !re) { matches = []; matchAt = -1; return }
        var text = v.allText(), m
        while ((m = re.exec(text)) !== null && out.length < 5000) { if (m[0].length === 0) { re.lastIndex++; continue } out.push([m.index, m.index + m[0].length]) }
        matches = out
        var from = v.cursor(), best = 0
        for (var i = 0; i < out.length; i++) if (out[i][0] >= from - (out[i][1] - out[i][0])) { best = i; break }
        matchAt = out.length ? best : -1
        if (matchAt >= 0) v.selectRange(out[matchAt][0], out[matchAt][1])
    }
    function step(d) { if (!matches.length) return; matchAt = (matchAt + d + matches.length) % matches.length; view().selectRange(matches[matchAt][0], matches[matchAt][1]) }
    function replaceOne() {
        var v = view(); if (!v || matchAt < 0) return
        var m = matches[matchAt]; v.replaceRange(m[0], m[1], replaceBox.text); refind()
    }
    function replaceEvery() {
        var v = view(); if (!v || !matches.length) return
        var n = matches.length
        for (var i = matches.length - 1; i >= 0; i--) v.replaceRange(matches[i][0], matches[i][1], replaceBox.text)
        refind(); toast.say("Replaced " + n, false)
    }
    function paletteRows(text) {
        var out = [], q = text.toLowerCase(), i
        if (text.charAt(0) === ">") {
            q = q.substring(1).trim()
            for (i = 0; i < commands.length; i++) if (commands[i].name.toLowerCase().indexOf(q) >= 0 && (!commands[i].ai || win.aiOn) && (!commands[i].when || commands[i].when())) out.push({ label: commands[i].name, detail: win.keyOf(commands[i]), act: "cmd", n: i })
            var ls = Backend.launches, ts = win.bld.tasks
            for (i = 0; i < ls.length; i++) if (("debug: " + ls[i].name).toLowerCase().indexOf(q) >= 0) out.push({ label: "Debug: " + ls[i].name, detail: ls[i].ok ? "launch.json" : "can't start here", act: "launch", name: ls[i].name })
            var xs = Backend.extensionCommands
            for (i = 0; i < xs.length; i++) if (xs[i].title.toLowerCase().indexOf(q) >= 0) out.push({ label: xs[i].title, detail: "from " + xs[i].from, act: "ext", n: i })
            for (i = 0; i < ts.length; i++) if (("task: " + ts[i].name).toLowerCase().indexOf(q) >= 0) out.push({ label: "Task: " + ts[i].name, detail: ts[i].detail, act: "task", id: ts[i].id })
            return out
        }
        if (text.charAt(0) === ":") {
            var n = parseInt(text.substring(1))
            return [{ label: isNaN(n) ? "Type a line number" : "Go to line " + n, detail: win.view() ? (win.view().lines() === 1 ? "1 line" : win.view().lines() + " lines") : "", act: "line", n: isNaN(n) ? -1 : n }]
        }
        if (text.charAt(0) === "@") {
            q = q.substring(1).trim()
            var syms = Backend.symbols(Backend.current)
            for (i = 0; i < syms.length; i++) if (!q || syms[i].name.toLowerCase().indexOf(q) >= 0) out.push({ label: syms[i].name, detail: syms[i].kind + " · line " + (syms[i].line + 1), act: "sym", n: syms[i].line, depth: syms[i].depth })
            return out
        }
        var files = Backend.quickOpen(text)
        for (i = 0; i < files.length; i++) out.push({ label: files[i].name, detail: files[i].where, act: "file", rel: files[i].rel })
        return out
    }
    function choose(row) {
        palOpen = false
        if (!row) return
        if (row.act === "cmd") commands[row.n].run()
        else if (row.act === "ext") { bottom = "terminal"; term = true; Backend.runExtensionCommand(row.n) }
        else if (row.act === "launch") { bottom = "debug"; term = true; Backend.startLaunch(row.name) }
        else if (row.act === "task") runTask(row.id)
        else if (row.act === "file") Backend.openRel(row.rel, -1, 0)
        else if (row.act === "line" && row.n > 0) { var v = view(); if (v) v.goTo(row.n - 1, 0) }
        else if (row.act === "sym") { var w = view(); if (w) w.goTo(row.n, 0) }
        if (row.act !== "cmd") Qt.callLater(function () { var x = win.view(); if (x) x.focusEditor() })
    }
    function searchRows(results) {
        var out = [], last = ""
        for (var i = 0; i < results.length; i++) {
            var r = results[i]
            if (r.path !== last) { out.push({ header: true, path: r.path, count: 0 }); last = r.path }
            out.push({ header: false, path: r.path, line: r.line, col: r.col, length: r.length, text: r.text })
        }
        for (var j = 0, h = -1; j < out.length; j++) { if (out[j].header) h = j; else out[h].count++ }
        return out
    }
    function gitInk(kind) { return kind === "new" || kind === "added" ? addInk : kind === "deleted" ? delInk : kind === "conflict" ? "#E3B341" : kind === "inside" ? Theme.t.text_secondary : modInk }
    function gitLetter(kind) { return ({ "new": "U", "added": "A", "deleted": "D", "renamed": "R", "conflict": "!", "changed": "M", "inside": "•" })[kind] || "" }
    function langInk(lang) {
        return ({ "Python": "#4B8BBE", "JavaScript": "#E8C547", "TypeScript": "#3178C6", "C": "#8C9EFF", "C++": "#F06292", "Rust": "#DEA584", "Go": "#00ADD8", "QML": "#41CD52",
                  "Shell": "#89E051", "JSON": "#CBA34A", "Markdown": "#8E9AAF", "HTML": "#E44D26", "CSS": "#2965F1", "YAML": "#CB171E", "TOML": "#9C4221", "Java": "#B07219", "C#": "#178600", "Lua": "#000080",
                  "GDScript": "#478CBF", "Godot Resource": "#6A9FB5", "Godot Shader": "#8FB8DE", "GLSL": "#5686A5", "HLSL": "#AACE60", "CMake": "#DA3434" })[lang] || Theme.t.text_secondary
    }

    ListModel { id: docModel }
    Connections {
        target: Backend
        function onChanged() { win.syncDocs() }
        function onSaid(msg, wrong) { toast.say(msg, wrong) }
        function onTextLoaded(i) { var v = docs.itemAt(i); if (v) v.reload() }
        function onJump(i, line, col) { Backend.select(i); Qt.callLater(function () { var v = docs.itemAt(i); if (v) v.goTo(line, col) }) }
        function onCompletions(i, items) { var v = docs.itemAt(i); if (i === Backend.current && v) v.offer(items) }
        function onHoverText(i, text) { if (i === Backend.current) win.tip = text }
        function onSignature(i, label, a, b, doc) { var v = win.view(); if (i === Backend.current) win.sig = label && v && v.inCall() ? { label: label, a: a, b: b, doc: doc } : null }   // (it can come back after the call was closed)
        function onFixesFound(i, items) { if (i !== Backend.current) return; if (items.length) win.fixMenu = { items: items, k: 0 }; else toast.say("Nothing to fix on this line", false) }
        function onShown() { win.show(); win.raise(); win.requestActivate() }
    }
    Component.onCompleted: syncDocs()

    Shortcut { sequence: "Ctrl+S"; enabled: win.free("Ctrl+S"); onActivated: win.save() }
    Shortcut { sequence: "Ctrl+Alt+S"; enabled: win.free("Ctrl+Alt+S"); onActivated: toast.say(Backend.saveAll() + " saved", false) }
    Shortcut { sequence: "Ctrl+W"; enabled: win.free("Ctrl+W"); onActivated: if (Backend.current >= 0) win.closeTab(Backend.current) }
    Shortcut { sequence: "Ctrl+P"; enabled: win.free("Ctrl+P"); onActivated: win.openPalette("") }
    Shortcut { sequence: "Ctrl+Shift+P"; enabled: win.free("Ctrl+Shift+P"); onActivated: win.openPalette(">") }
    Shortcut { sequence: "Ctrl+G"; enabled: win.free("Ctrl+G"); onActivated: win.openPalette(":") }
    Shortcut { sequence: "Alt+Left"; enabled: win.free("Alt+Left"); onActivated: win.travel(-1) }
    Shortcut { sequence: "Alt+Right"; enabled: win.free("Alt+Right"); onActivated: win.travel(1) }
    Shortcut { sequence: "Ctrl+Alt+W"; enabled: win.free("Ctrl+Alt+W"); onActivated: Backend.reopenClosed() }
    Shortcut { sequence: "Ctrl+Shift+O"; enabled: win.free("Ctrl+Shift+O"); onActivated: win.openPalette("@") }
    Shortcut { sequence: "Ctrl+F"; enabled: win.free("Ctrl+F"); onActivated: win.startFind(false) }
    Shortcut { sequence: "Ctrl+H"; enabled: win.free("Ctrl+H"); onActivated: win.startFind(true) }
    Shortcut { sequence: "Ctrl+Shift+F"; enabled: win.free("Ctrl+Shift+F"); onActivated: win.showPanel("search") }
    Shortcut { sequence: "Ctrl+Shift+E"; enabled: win.free("Ctrl+Shift+E"); onActivated: win.showPanel("files") }
    Shortcut { sequence: "Ctrl+Shift+G"; enabled: win.free("Ctrl+Shift+G"); onActivated: win.showPanel("git") }
    Shortcut { sequence: "Ctrl+Shift+M"; enabled: win.free("Ctrl+Shift+M"); onActivated: win.showPanel("problems") }
    Shortcut { sequence: "Ctrl+Shift+\\"; enabled: win.free("Ctrl+Shift+\\"); onActivated: win.toBracket() }
    Shortcut { sequence: "Ctrl+Shift+T"; enabled: win.free("Ctrl+Shift+T"); onActivated: win.showPanel("tests") }
    Shortcut { sequence: "Ctrl+Alt+B"; enabled: win.free("Ctrl+Alt+B"); onActivated: win.blameOn = !win.blameOn }
    function showCommit(sha, title) { if (!sha) return; var info = Backend.commitInfo(sha); win.ask("diff", { rel: "", staged: false, commit: info, rows: Backend.commitRows(sha, "") }) }
    Shortcut { sequence: "Ctrl+B"; enabled: win.free("Ctrl+B"); onActivated: win.side = !win.side }
    Shortcut { sequence: "Ctrl+`"; enabled: win.free("Ctrl+`"); onActivated: win.toggleTerm() }
    Shortcut { sequence: "F5"; enabled: win.free("F5"); onActivated: win.debugIt() }
    Shortcut { sequence: "Ctrl+,"; enabled: win.free("Ctrl+,"); onActivated: win.ask("settings") }
    Shortcut { sequence: "Ctrl+Shift+["; enabled: win.free("Ctrl+Shift+["); onActivated: { var v = win.view(); if (v) v.foldHere(1) } }
    Shortcut { sequence: "Ctrl+Shift+]"; enabled: win.free("Ctrl+Shift+]"); onActivated: { var v = win.view(); if (v) v.foldHere(-1) } }
    Shortcut { sequence: "Ctrl+Shift+B"; enabled: win.free("Ctrl+Shift+B"); onActivated: win.buildIt() }
    Shortcut { sequence: "F8"; enabled: win.free("F8"); onActivated: win.bld.step(1) }
    Shortcut { sequence: "Shift+F8"; enabled: win.free("Shift+F8"); onActivated: win.bld.step(-1) }
    Shortcut { sequence: "Ctrl+F5"; enabled: win.free("Ctrl+F5"); onActivated: win.runIt() }
    Shortcut { sequence: "Shift+F5"; enabled: win.free("Shift+F5"); onActivated: win.dbg.stop() }
    Shortcut { sequence: "F6"; enabled: win.free("F6"); onActivated: win.dbg.pause() }
    Shortcut { sequence: "F10"; enabled: win.free("F10"); onActivated: win.dbg.stepOver() }
    Shortcut { sequence: "F11"; enabled: win.free("F11"); onActivated: win.dbg.stepIn() }
    Shortcut { sequence: "Shift+F11"; enabled: win.free("Shift+F11"); onActivated: win.dbg.stepOut() }
    Shortcut { sequence: "Ctrl+\\"; enabled: win.free("Ctrl+\\"); onActivated: win.toggleSplit() }
    Shortcut { sequence: "Ctrl+N"; enabled: win.free("Ctrl+N"); onActivated: win.newFile() }
    Shortcut { sequence: "Ctrl+O"; enabled: win.free("Ctrl+O"); onActivated: { win.browseAt = Backend.root || Backend.home; win.ask("open") } }
    Shortcut { sequence: "Ctrl+Shift+I"; enabled: win.free("Ctrl+Shift+I"); onActivated: if (Backend.current >= 0) Backend.format(Backend.current) }
    Shortcut { sequence: "Ctrl+Shift+V"; enabled: win.free("Ctrl+Shift+V"); onActivated: win.mdPreview = !win.mdPreview }
    Shortcut { sequence: "Alt+Z"; enabled: win.free("Alt+Z"); onActivated: Backend.setWrap(!Backend.wrap) }
    Shortcut { sequences: ["Ctrl+=", "Ctrl++"]; enabled: win.free("Ctrl+="); onActivated: Backend.setSize(Backend.size + 1) }
    Shortcut { sequence: "Ctrl+-"; enabled: win.free("Ctrl+-"); onActivated: Backend.setSize(Backend.size - 1) }
    Shortcut { sequence: "Ctrl+Tab"; enabled: win.free("Ctrl+Tab"); onActivated: if (Backend.tabs.length) Backend.select((Backend.current + 1) % Backend.tabs.length) }
    Shortcut { sequence: "Ctrl+Shift+Tab"; enabled: win.free("Ctrl+Shift+Tab"); onActivated: if (Backend.tabs.length) Backend.select((Backend.current - 1 + Backend.tabs.length) % Backend.tabs.length) }
    Shortcut { sequence: "Escape"; enabled: aiPanel.visible || win.palOpen || win.finding || win.tip !== "" || win.comp.length > 0 || win.menuFor !== null || win.sheet !== null || win.sig !== null || win.fixMenu !== null || win.zen
        onActivated: { if (win.sheet) win.sheet = null; else if (aiPanel.visible) aiPanel.close(); else if (win.palOpen || win.tip || win.comp.length || win.menuFor || win.sig || win.fixMenu) win.closeOverlays(); else if (win.finding) { win.finding = false; var v = win.view(); if (v) v.focusEditor() } else if (win.zen) win.toggleZen() } }

    islands: [
        // the open files, floating across the top
        Item { id: tabsBar; objectName: "tabsBar"; x: Math.max(win.sideW + 24, win.lifted ? win.titleEnd + 10 : 0); y: win.topY; height: 40; width: win.width - x - toolBox.width - 26; visible: Backend.tabs.length > 0 && !win.zen
            ListView { id: tabList; anchors.fill: parent; orientation: ListView.Horizontal; spacing: 6; clip: true; model: Backend.tabs; boundsBehavior: Flickable.StopAtBounds
                currentIndex: Backend.current
                onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
                delegate: Pressable { id: tabPill; required property var modelData; required property int index; readonly property bool on: index === Backend.current
                    width: Math.min(230, tabRow.width + 26); height: 36; y: 2; radius: 18
                    color: on ? win.slab : hovered ? Theme.t.hover : Theme.t.island; border.width: 1; border.color: on ? Theme.t.accent : Theme.t.islandLine
                    onClicked: Backend.select(index)
                    Row { id: tabRow; x: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 7
                        Rectangle { width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter; color: win.langInk(tabPill.modelData.lang) }
                        Label { text: tabPill.modelData.name; font.pixelSize: 12; font.weight: tabPill.on ? Font.DemiBold : Font.Normal; width: Math.min(implicitWidth, 150); elide: Text.ElideMiddle
                            color: tabPill.modelData.errors > 0 ? win.delInk : tabPill.on ? win.codeInk : Theme.t.text }
                        Item { width: 16; height: 16; anchors.verticalCenter: parent.verticalCenter
                            Rectangle { visible: tabPill.modelData.dirty && !closeX.hovered; anchors.centerIn: parent; width: 8; height: 8; radius: 4; color: Theme.t.text }
                            Pressable { id: closeX; anchors.fill: parent; radius: 8; color: hovered ? Theme.t.hover : "transparent"; visible: !tabPill.modelData.dirty || hovered || tabPill.hovered
                                onClicked: win.closeTab(tabPill.index)
                                Glyph { anchors.centerIn: parent; name: "x"; size: 10; visible: !tabPill.modelData.dirty || closeX.hovered } } } } } } },
        // The tools on the left, Run and Debug on their own at the right edge: a quick second click on the terminal
        // (or anything else) never lands on Run
        Item { id: toolBox; visible: !win.zen; anchors { right: parent.right; rightMargin: win.liftRight } y: win.topY; height: runBox.height; width: toolsIsland.width + 12 + runBox.width
            Island { id: toolsIsland; objectName: "toolsIsland"
                Seg { objectName: "newFileButton"; icon: "newfile"; tip: "New file (Ctrl+N)"; onClicked: win.newFile() }
                Seg { icon: "search"; tip: "Go to a file or command (Ctrl+P)"; onClicked: win.openPalette("") }
                Seg { objectName: "termButton"; icon: "terminal"; tip: "Terminal (Ctrl+`)"; on: win.term; onClicked: win.toggleTerm() }
                Seg { icon: "split"; tip: "Two editors side by side (Ctrl+\\)"; on: win.split; onClicked: win.toggleSplit() }
                Seg { objectName: "settingsButton"; icon: "gear"; tip: "Settings (Ctrl+,)"; onClicked: win.ask("settings") } }
            Island { id: runBox; objectName: "runIsland"; x: toolsIsland.width + 12
                Seg { icon: "bug"; text: win.dbg.active ? "Debugging" : "Debug"; on: win.dbg.active; tip: "Debug (F5)"; onClicked: win.debugIt() }
                Seg { objectName: "buildButton"; visible: win.bld.tasks.length > 0; icon: win.bld.running ? "stop" : "check"; text: win.bld.running ? "Stop" : "Build"; on: win.bld.running
                    tip: win.bld.running ? "Stop “" + win.bld.taskName + "”" : "Build (Ctrl+Shift+B)"; onClicked: win.bld.running ? win.bld.stop() : win.buildIt() }
                Seg { objectName: "runButton"; icon: "play"; text: "Run"; tip: "Run (Ctrl+F5): " + (Backend.runCommand() || "nothing yet"); onClicked: win.runIt() } } },
        Toast { id: toast; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 56 } },
        AiPanel { id: aiPanel; z: 27; width: Math.min(680, win.width - 80); x: (win.width - width) / 2; anchors { bottom: parent.bottom; bottomMargin: 48 } maxHeight: win.height * 0.6 },

        // the palette: files, commands (>), lines (:) and symbols (@)
        Item { anchors.fill: parent; z: 30; visible: win.palOpen
            MouseArea { anchors.fill: parent; onClicked: win.closeOverlays() }
            Rectangle { objectName: "palette"; x: (parent.width - width) / 2; y: 58; width: Math.min(640, parent.width - 80); height: 66 + Math.min(10, palList.count) * 40; radius: 16
                color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                MouseArea { anchors.fill: parent }
                TextInput { id: palBox; objectName: "palBox"; x: 18; y: 18; width: parent.width - 36; font.pixelSize: 16; color: Theme.t.text; clip: true; selectByMouse: true
                    onTextChanged: { palList.model = win.paletteRows(text); palList.currentIndex = 0 }
                    Keys.onPressed: function (e) {
                        if (e.key === Qt.Key_Down) { palList.currentIndex = Math.min(palList.count - 1, palList.currentIndex + 1); e.accepted = true }
                        else if (e.key === Qt.Key_Up) { palList.currentIndex = Math.max(0, palList.currentIndex - 1); e.accepted = true }
                        else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { win.choose(palList.model[palList.currentIndex]); e.accepted = true }
                        else if (e.key === Qt.Key_Escape) { win.closeOverlays(); e.accepted = true } }
                    Text { visible: !palBox.text; text: "Type a file's name · > for commands · : for a line · @ for a symbol"; font: palBox.font; color: Theme.t.text_secondary } }
                ListView { id: palList; x: 8; y: 54; width: parent.width - 16; height: parent.height - 62; clip: true; boundsBehavior: Flickable.StopAtBounds; highlightMoveDuration: 0
                    delegate: Pressable { required property var modelData; required property int index; width: palList.width; height: 40; radius: 10
                        color: index === palList.currentIndex ? Qt.alpha(Theme.t.accent, 0.22) : hovered ? Theme.t.hover : "transparent"
                        onClicked: win.choose(modelData)
                        Label { x: 12 + (modelData.depth || 0) * 12; width: parent.width * 0.6; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; font.weight: Font.DemiBold }
                        Label { anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } width: Math.min(implicitWidth, parent.width * 0.38); elide: Text.ElideLeft
                            text: modelData.detail || ""; secondary: true; font.pixelSize: 11; font.family: modelData.act === "cmd" ? win.mono : Theme.t.font } } } } },

        // a right-click menu in the files list
        Item { anchors.fill: parent; z: 28; visible: win.menuFor !== null
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: win.menuFor = null }
            Rectangle { x: win.menuFor ? Math.min(win.menuFor.x, win.width - width - 8) : 0; y: win.menuFor ? Math.min(win.menuFor.y, win.height - height - 8) : 0; width: 210; height: menuCol.height + 12; radius: 12
                color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                Column { id: menuCol; x: 6; y: 6; width: parent.width - 12
                    Repeater { model: !win.menuFor ? [] : win.menuFor.root ? ["New File Here", "New Folder Here", "Open Terminal Here", "Copy Path", "Show in Files", "Add a Folder to the Workspace…"].concat(win.menuFor.space ? ["Remove from the Workspace"] : [])
                                   : win.menuFor.dir ? ["New File Here", "New Folder Here", "Open Terminal Here", "Copy Path", "Rename…", "Show in Files", "Move to Trash"]
                                   : ["Open", "Open Terminal Here", "Copy Path", "Rename…", "Show in Files", "Move to Trash"]
                        Pressable { required property string modelData; width: menuCol.width; height: 32; radius: 8; color: hovered ? Theme.t.hover : "transparent"
                            // what was picked is read first: clearing menuFor empties this Repeater, which ends this row (and
                            // with it modelData, win and Backend here), so every item used to do nothing
                            onClicked: { var f = win.menuFor, what = modelData
                                if (what === "Add a Folder to the Workspace…") { win.menuFor = null; win.browseAt = f.path.replace(/\/[^\/]+\/?$/, "") || "/"; win.ask("open", { add: true }); return }
                                if (what === "Remove from the Workspace") { win.menuFor = null; var no = Backend.removeFolder(f.path); if (no) toast.say(no, true); return }
                                if (what === "Open") Backend.openFile(f.path)
                                else if (what === "New File Here") win.ask("new", { folder: f.path, dir: false })
                                else if (what === "New Folder Here") win.ask("new", { folder: f.path, dir: true })
                                else if (what === "Rename…") win.ask("rename", { path: f.path, name: f.name })
                                else if (what === "Show in Files") Backend.reveal(f.path)
                                else if (what === "Open Terminal Here") { win.bottom = "terminal"; win.term = true; Backend.terminalAt(f.path); Qt.callLater(function () { termKeys.forceActiveFocus() }) }
                                else if (what === "Copy Path") Backend.copyPath(f.path)
                                else win.ask("trash", { path: f.path, name: f.name })
                                win.menuFor = null }
                            Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData; font.pixelSize: 12; color: modelData === "Move to Trash" ? Theme.t.danger : Theme.t.text } } } } } },

        // sheets: open a folder, unsaved changes, a clash on disk, names, the Run command, a diff
        Item { anchors.fill: parent; z: 32; visible: win.sheet !== null
            Rectangle { anchors.fill: parent; radius: win.r; color: "#77000000"; MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: if (win.sheet && win.sheet.kind !== "dirty") win.sheet = null } }
            Rectangle { id: card; anchors.centerIn: parent; radius: 18; color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                readonly property string kind: win.sheet ? win.sheet.kind : ""
                width: kind === "diff" ? win.width - 120 : kind === "settings" || kind === "keys" ? Math.min(win.width - 80, 760) : kind === "open" || kind === "langs" || kind === "branches" || kind === "history" || kind === "attach" || kind === "container" ? 560 : kind === "extensions" ? Math.min(win.width - 80, 720) : 470
                height: kind === "diff" ? win.height - 100 : kind === "settings" || kind === "keys" || kind === "extensions" ? win.height - 90 : kind === "open" || kind === "langs" || kind === "branches" || kind === "history" || kind === "attach" ? Math.min(win.height - 80, 560) : kind === "container" ? Math.min(win.height - 80, 440) : kind === "dirty" || kind === "clash" || kind === "trash" || kind === "discard" ? 170 : kind === "remote" ? 290 : 200
                MouseArea { anchors.fill: parent }
                Label { x: 24; y: 20; width: parent.width - 48; elide: Text.ElideMiddle; font.pixelSize: 17; font.weight: Font.DemiBold
                    text: ({ "open": win.sheet && win.sheet.add ? "Add a folder to the workspace" : "Open a folder", "space": "Save the workspace as a file", "dirty": "Save changes to “" + (win.sheet ? win.sheet.name : "") + "”?", "clash": "This file changed on disk",
                             "new": win.sheet && win.sheet.dir ? "New folder" : "New file", "rename": "Rename “" + (win.sheet ? win.sheet.name : "") + "”",
                             "trash": "Move “" + (win.sheet ? win.sheet.name : "") + "” to the Trash?", "renamesym": "Rename “" + (win.sheet ? win.sheet.name : "") + "” everywhere", "debugprog": "Which program should be debugged?", "unreal": "Where is Unreal Engine?", "theme": "Which theme file?", "remote": "Open a folder on another computer", "attach": "Attach the debugger to a running program", "extensions": "Extensions", "container": "Open this project in its container", "aiask": win.sheet && win.sheet.mode === "write" ? "What should it write?" : "How should it change?", "run": "What Run does", "discard": "Throw away the changes to “" + (win.sheet ? win.sheet.rel : "") + "”?",
                             "langs": win.sheet && win.sheet.mode === "new" ? "New file in…" : "Languages", "branches": "Branches", "settings": "Settings", "keys": "Keyboard Shortcuts", "history": "History of “" + (win.sheet ? win.sheet.name : "") + "”",
                             "diff": (win.sheet ? win.sheet.rel : "") + (win.sheet && win.sheet.staged ? "  ·  staged" : "") })[card.kind] || "" }
                // ---- Settings: Code's own, kept in its settings.json under VS Code's names; a project's .vscode/settings.json lies over them
                ListView { id: setList; objectName: "settingsList"; visible: card.kind === "settings"; x: 24; y: 58; width: parent.width - 48; height: parent.height - 58 - 66; clip: true; boundsBehavior: Flickable.StopAtBounds
                    model: card.kind === "settings" ? Backend.settingsList : []
                    property real keepY: 0                                  // (the list is made again when a setting changes: stay where you were)
                    onModelChanged: contentY = keepY
                    function set(key, value) { keepY = contentY; Backend.setSetting(key, value) }
                    section.property: "group"
                    section.delegate: Label { required property string section; height: 34; verticalAlignment: Text.AlignBottom; bottomPadding: 6; text: section.toUpperCase(); font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1; secondary: true }
                    delegate: Item { id: setRow; required property var modelData; width: setList.width - 8; height: Math.max(46, setCol.height + 16)
                        readonly property bool wide: modelData.kind === "globs"
                        Column { id: setCol; y: 8; width: parent.width - (setRow.wide ? 0 : 250); spacing: 2
                            Label { width: parent.width; elide: Text.ElideRight; text: setRow.modelData.title; font.pixelSize: 13; font.weight: setRow.modelData.changed ? Font.DemiBold : Font.Normal }
                            Label { visible: text !== ""; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11; text: setRow.modelData.about }
                            Label { visible: setRow.modelData.where === "project"; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; color: win.modInk; text: "This project's .vscode/settings.json sets this." }
                            Label { width: parent.width; elide: Text.ElideRight; secondary: true; font.pixelSize: 10; font.family: win.mono; opacity: 0.7; text: setRow.modelData.key }
                            Rectangle { visible: setRow.wide; width: parent.width - 40; height: 64; radius: 10; color: Theme.t.capsule; border.width: 1; border.color: globBox.activeFocus ? Theme.t.accent : Theme.t.capsule_border
                                Flickable { anchors { fill: parent; margins: 8 } contentHeight: globBox.contentHeight; clip: true
                                    TextEdit { id: globBox; width: parent.width; text: setRow.modelData.kind === "globs" ? setRow.modelData.value : ""; color: Theme.t.text; font.family: win.mono; font.pixelSize: 12; selectByMouse: true
                                        onActiveFocusChanged: if (!activeFocus && setRow.modelData.kind === "globs" && text !== setRow.modelData.value) setList.set(setRow.modelData.key, text) } } } }
                        Row { visible: !setRow.wide; anchors { right: parent.right; rightMargin: 4; verticalCenter: parent.verticalCenter } spacing: 6; opacity: setRow.modelData.where === "project" ? 0.55 : 1
                            Seg { visible: setRow.modelData.changed; icon: "refresh"; tip: "Back to Code's own"; onClicked: { setList.keepY = setList.contentY; Backend.resetSetting(setRow.modelData.key) } }
                            Toggle { visible: setRow.modelData.kind === "bool"; anchors.verticalCenter: parent.verticalCenter; on: setRow.modelData.kind === "bool" && setRow.modelData.value === true; onToggled: function (v) { setList.set(setRow.modelData.key, v) } }
                            Repeater { model: setRow.modelData.choices
                                Seg { required property string modelData; text: modelData; on: setRow.modelData.value === modelData; onClicked: setList.set(setRow.modelData.key, modelData) } }
                            Rectangle { visible: ["int", "numbers", "text"].indexOf(setRow.modelData.kind) >= 0; width: setRow.modelData.kind === "int" ? 70 : 170; height: 30; radius: 10; anchors.verticalCenter: parent.verticalCenter
                                color: Theme.t.capsule; border.width: 1; border.color: setIn.activeFocus ? Theme.t.accent : Theme.t.capsule_border
                                TextInput { id: setIn; anchors { fill: parent; leftMargin: 10; rightMargin: 10 } verticalAlignment: TextInput.AlignVCenter; clip: true; color: Theme.t.text; font.pixelSize: 13; selectByMouse: true
                                    readOnly: setRow.modelData.kind === "text"; text: "" + setRow.modelData.value
                                    onEditingFinished: if (!readOnly && text !== "" + setRow.modelData.value) setList.set(setRow.modelData.key, setRow.modelData.kind === "int" ? (parseInt(text) || 0) : text) } } } } }
                Row { visible: card.kind === "settings"; anchors { left: parent.left; leftMargin: 20; bottom: parent.bottom; bottomMargin: 18 } spacing: 4
                    Seg { text: "Keyboard Shortcuts…"; onClicked: win.ask("keys") }
                    Seg { text: "settings.json"; tip: "Open Code's settings file to edit by hand"; tipAbove: true; onClicked: { win.sheet = null; Backend.openSettingsFile() } }
                    Seg { text: "Import a Theme…"; onClicked: win.ask("theme", { now: "" }) }
                    Seg { text: "Extensions…"; onClicked: win.ask("extensions") }
                    Seg { visible: Backend.vscodeFolder !== ""; text: "Bring from VS Code"; tip: "Your snippets, settings and key bindings, from " + Backend.vscodeFolder; tipAbove: true; onClicked: toast.say(Backend.importFromVSCode(), false) } }
                // the computers you've opened before, and the ones ~/.ssh/config names
                Flow { visible: card.kind === "remote" && Backend.remoteHosts.length > 0; x: 24; y: 176; width: parent.width - 48; height: 50; clip: true; spacing: 6
                    Repeater { model: card.kind === "remote" ? Backend.remoteHosts.slice(0, 8) : []
                        Seg { required property string modelData; text: modelData; onClicked: nameBox.text = modelData } } }
                // ---- Extensions: what is installed, a .vsix to install, and the Open VSX registry to look in
                Item { id: extPage; objectName: "extPage"; visible: card.kind === "extensions"; x: 24; y: 56; width: parent.width - 48; height: parent.height - 56 - 66
                    property var found: []
                    property string why: ""
                    property bool looking: false
                    property bool store: false                       // looking in the registry, not at what is installed
                    onVisibleChanged: if (visible) { store = false; found = []; why = ""; extFind.text = "" }
                    Connections { target: Backend; function onExtensionsFound(rows, why) { extPage.found = rows; extPage.why = why; extPage.looking = false } }
                    Row { id: extTop; width: parent.width; height: 30; spacing: 6
                        Seg { text: "Installed"; on: !extPage.store; onClicked: extPage.store = false }
                        Seg { text: "Open VSX"; on: extPage.store; tip: "The open registry of VS Code extensions (open-vsx.org)"; onClicked: { extPage.store = true; if (!extPage.found.length && !extPage.looking) { extPage.looking = true; Backend.searchExtensions("") } } }
                        Field { id: extFind; objectName: "extFind"; width: parent.width - 240; placeholder: extPage.store ? "Search Open VSX: a theme, a language, snippets…" : "A .vsix file to install: /home/you/Downloads/theme.vsix"
                            onAccepted: extPage.go() }
                        Seg { text: extPage.store ? "Search" : "Install"; onClicked: extPage.go() } }
                    function go() { if (store) { looking = true; why = ""; Backend.searchExtensions(extFind.text) }
                        else { var said = Backend.installExtension(extFind.text); if (said) { toast.say(said, said.indexOf("Installed") !== 0); if (said.indexOf("Installed") === 0) extFind.text = "" } } }
                    Label { y: 38; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                        text: "Code uses the parts of a VS Code extension that are data: colour themes, snippets, file types, key bindings. An extension's program runs only inside VS Code itself, so Code leaves that part out and says so." }
                    ListView { id: extList; objectName: "extList"; visible: !extPage.store; y: 78; width: parent.width; height: parent.height - 78; clip: true; boundsBehavior: Flickable.StopAtBounds; spacing: 4
                        model: card.kind === "extensions" ? Backend.extensions : []
                        delegate: Rectangle { id: extRow; required property var modelData; width: extList.width - 6; height: extCol.height + 16; radius: 10; color: Qt.alpha(Theme.t.text, 0.04)
                            readonly property var themes: Backend.extensionThemes.filter(function (t) { return t.ext === extRow.modelData.id })
                            Column { id: extCol; x: 12; y: 8; width: parent.width - 24; spacing: 3
                                Item { width: parent.width; height: 24
                                    Label { width: parent.width - 170; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; font.weight: Font.DemiBold; opacity: extRow.modelData.on ? 1 : 0.5
                                        text: extRow.modelData.name + (extRow.modelData.version ? "  " + extRow.modelData.version : "") }
                                    Row { anchors.right: parent.right; spacing: 4
                                        Seg { text: extRow.modelData.on ? "On" : "Off"; on: extRow.modelData.on; onClicked: Backend.setExtensionOn(extRow.modelData.id, !extRow.modelData.on) }
                                        Seg { text: "Remove"; onClicked: Backend.removeExtension(extRow.modelData.id) } } }
                                Label { visible: text !== ""; width: parent.width; elide: Text.ElideRight; maximumLineCount: 2; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12; text: extRow.modelData.about }
                                Label { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true
                                    text: "In use: " + extRow.modelData.takes + (extRow.modelData.leaves ? "   ·   Left out: " + extRow.modelData.leaves : "") }
                                Flow { visible: extRow.themes.length > 0 && extRow.modelData.on; width: parent.width; spacing: 4
                                    Repeater { model: extRow.themes
                                        Seg { required property var modelData; text: modelData.label; on: Backend.theme.name === modelData.label && Backend.theme.ext === modelData.ext
                                            onClicked: { var no = Backend.useExtensionTheme(modelData.ext, modelData.label); if (no) toast.say(no, true) } } } } } } }
                    Label { visible: !extPage.store && extList.count === 0; anchors.centerIn: parent; width: parent.width - 80; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
                        text: "No extensions yet. Look in Open VSX, or give a .vsix file above." }
                    ListView { id: vsxList; objectName: "vsxList"; visible: extPage.store; y: 78; width: parent.width; height: parent.height - 78; clip: true; boundsBehavior: Flickable.StopAtBounds; spacing: 2
                        model: extPage.found
                        delegate: Pressable { id: vsxRow; required property var modelData; width: vsxList.width - 6; height: 50; radius: 10; color: hovered ? Theme.t.hover : "transparent"
                            Label { x: 12; y: 7; width: parent.width - 130; elide: Text.ElideRight; font.weight: Font.DemiBold; text: vsxRow.modelData.title + "   " + vsxRow.modelData.namespace + "." + vsxRow.modelData.name }
                            Label { x: 12; y: 27; width: parent.width - 130; elide: Text.ElideRight; font.pixelSize: 11; secondary: true; text: vsxRow.modelData.about }
                            Seg { anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } text: "Install"; onClicked: Backend.fetchExtension(vsxRow.modelData.namespace, vsxRow.modelData.name) } } }
                    Label { visible: extPage.store && vsxList.count === 0; anchors.centerIn: parent; width: parent.width - 80; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
                        text: extPage.looking ? "Asking the registry…" : extPage.why ? extPage.why : "Nothing found." } }
                // ---- attach: your running programs; pick one and the debugger joins it (it keeps running when you detach)
                Field { id: attachFilter; objectName: "attachFilter"; visible: card.kind === "attach"; x: 24; y: 56; width: parent.width - 48; placeholder: "Find by name, command or number"
                    onVisibleChanged: if (visible) { text = ""; focusIn(); card.attachTick++ } }
                property int attachTick: 0
                Timer { interval: 2500; repeat: true; running: card.kind === "attach"; onTriggered: card.attachTick++ }
                property var attachRows: card.kind === "attach" && attachTick >= 0 ? Backend.runningPrograms(attachFilter.text) : []
                ListView { id: attachList; objectName: "attachList"; visible: card.kind === "attach"; x: 12; y: 98; width: parent.width - 24; height: parent.height - 98 - (Backend.attachNote ? 104 : 66); clip: true; boundsBehavior: Flickable.StopAtBounds
                    model: card.attachRows
                    delegate: Pressable { id: attachRow; required property var modelData; width: attachList.width - 6; height: 44; radius: 10; color: hovered ? Theme.t.hover : "transparent"
                        onClicked: { var c = win.sheet.config; win.sheet = null; win.bottom = "debug"; win.term = true; Backend.attachTo(modelData.pid, c) }
                        Label { x: 12; y: 5; width: parent.width - 150; elide: Text.ElideRight; font.weight: Font.DemiBold; text: attachRow.modelData.name }
                        Label { x: 12; y: 24; width: parent.width - 150; elide: Text.ElideMiddle; font.pixelSize: 11; font.family: win.mono; secondary: true; text: attachRow.modelData.command }
                        Label { anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } font.pixelSize: 11; secondary: true
                            text: (attachRow.modelData.kind === "python" ? "Python · " : "") + attachRow.modelData.pid } } }
                Label { visible: card.kind === "attach" && attachList.count === 0; anchors.centerIn: parent; secondary: true; text: attachFilter.text ? "None of your running programs match." : "None of your programs are running." }
                Label { visible: card.kind === "attach" && Backend.attachNote !== ""; x: 24; anchors { bottom: parent.bottom; bottomMargin: 62 } width: parent.width - 48; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight; font.pixelSize: 11; secondary: true; text: Backend.attachNote }
                // ---- a dev container: what the project's devcontainer.json will do here, before it does it
                Flickable { visible: card.kind === "container"; x: 24; y: 56; width: parent.width - 48; height: parent.height - 56 - 66; clip: true; contentHeight: boxCol.height; boundsBehavior: Flickable.StopAtBounds
                    Column { id: boxCol; width: parent.width - 8; spacing: 6
                        Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                            text: card.kind !== "container" ? "" : Backend.container.problem ? Backend.container.problem
                                : "“" + Backend.container.title + "”, with " + (Backend.container.engine === "podman" ? "Podman" : "Docker") + ". Your files stay in this folder and are edited here; Run, Build and the debugger happen inside the container. Its devcontainer.json is the project's own instructions, so read what it will do:" }
                        Repeater { model: card.kind === "container" && !Backend.container.problem ? Backend.container.asks : []
                            Row { required property string modelData; width: boxCol.width; spacing: 8
                                Label { text: "•"; secondary: true }
                                Label { width: parent.width - 20; wrapMode: Text.WrapAnywhere; font.pixelSize: 12; font.family: modelData.indexOf("Run inside") === 0 || modelData.indexOf("Extra options") === 0 ? win.mono : Theme.t.font
                                    color: modelData.indexOf("PRIVILEGED") >= 0 || modelData.indexOf("NOT done") === 0 ? win.delInk : Theme.t.text; text: modelData } } } } }
                // ---- a file's history: a copy kept at every save; pick one to see what changed since, and go back to it if you like
                ListView { id: fileHist; objectName: "historyList"; visible: card.kind === "history"; x: 16; y: 58; width: parent.width - 32; height: parent.height - 58 - 66; clip: true; boundsBehavior: Flickable.StopAtBounds
                    model: card.kind === "history" ? win.sheet.rows : []
                    delegate: Pressable { id: fileHistRow; required property var modelData; required property int index; width: fileHist.width - 6; height: 36; radius: 9; color: hovered ? Theme.t.hover : "transparent"
                        onClicked: { var s = win.sheet; win.ask("diff", { rel: s.name + "  ·  " + modelData.when + "  →  now", staged: false, rows: Backend.historyDiff(s.tab, modelData.id), restore: { tab: s.tab, id: modelData.id } }) }
                        Label { x: 12; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 13; text: fileHistRow.modelData.when }
                        Label { anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } secondary: true; font.pixelSize: 12
                            text: fileHistRow.modelData.lines + (fileHistRow.modelData.lines === 1 ? " line" : " lines") + (fileHistRow.index === 0 ? "  ·  the latest" : "") } } }
                Label { visible: card.kind === "history" && fileHist.count === 0; anchors.centerIn: parent; width: parent.width - 80; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
                    text: Backend.options.history ? "Nothing kept yet. Code keeps a copy each time this file is saved, for a month." : "Keeping a history is switched off in Settings." }
                // ---- Keyboard Shortcuts: click a command, press its new keys
                Item { id: keysPage; visible: card.kind === "keys"; x: 24; y: 56; width: parent.width - 48; height: parent.height - 56 - 66
                    property string taking: ""                            // the command whose new shortcut is being pressed
                    onVisibleChanged: { taking = ""; win.capturing = false; if (visible) keyFilter.focusIn() }
                    onTakingChanged: { win.capturing = taking !== ""; if (taking !== "") keyCatch.forceActiveFocus() }
                    readonly property var rows: { var q = keyFilter.text.toLowerCase(), o = win.keyOver, mine = Backend.ownKeys, out = []
                        for (var n = 0; n < win.commands.length; n++) { var c = win.commands[n], k = win.keyOf(c)
                            if (!q || c.name.toLowerCase().indexOf(q) >= 0 || (k || "").toLowerCase().indexOf(q) >= 0) out.push({ name: c.name, key: k || "", own: mine[c.name] !== undefined, other: o[c.name] !== undefined && o[c.name].toLowerCase() !== (c.key || "").toLowerCase() }) }
                        return out }
                    Field { id: keyFilter; width: 260; placeholder: "Find a command or a key" }
                    Row { anchors.right: parent.right; height: 30; spacing: 4
                        Label { anchors.verticalCenter: parent.verticalCenter; secondary: true; font.pixelSize: 12; text: "Keys like" }
                        Seg { text: "Huginn"; on: Backend.options.keymap === "Huginn"; onClicked: Backend.setSetting("huginn.keymap", "Huginn") }
                        Seg { text: "VS Code"; on: Backend.options.keymap === "VS Code"; onClicked: Backend.setSetting("huginn.keymap", "VS Code") } }
                    Item { id: keyCatch; focus: keysPage.taking !== ""
                        Keys.onPressed: function (e) {
                            if (keysPage.taking === "") return
                            e.accepted = true
                            if (e.key === Qt.Key_Escape) { keysPage.taking = ""; return }
                            var seq = (e.key === Qt.Key_Backspace || e.key === Qt.Key_Delete) && e.modifiers === Qt.NoModifier ? "" : Backend.keyName(e.key, e.modifiers)
                            if (seq === "" && e.key !== Qt.Key_Backspace && e.key !== Qt.Key_Delete) return            // a modifier on its own: keep waiting
                            var was = seq ? win.commandWith(seq, keysPage.taking) : ""
                            Backend.setKey(keysPage.taking, seq)
                            if (was) { Backend.setKey(was, ""); toast.say(seq + " was “" + was + "”, which has no shortcut now.", false) }
                            keysPage.taking = "" } }
                    ListView { id: keyList; objectName: "keyList"; y: 40; width: parent.width; height: parent.height - 40; clip: true; boundsBehavior: Flickable.StopAtBounds; model: keysPage.rows; reuseItems: true
                        delegate: Pressable { id: keyRow; required property var modelData; width: keyList.width - 8; height: 32; radius: 8
                            readonly property bool taking: keysPage.taking === modelData.name
                            color: taking ? Qt.alpha(Theme.t.accent, 0.22) : hovered ? Theme.t.hover : "transparent"
                            onClicked: keysPage.taking = taking ? "" : modelData.name
                            Label { x: 10; width: parent.width - 300; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 13; text: keyRow.modelData.name }
                            Label { anchors { right: parent.right; rightMargin: 44; verticalCenter: parent.verticalCenter } font.pixelSize: 12; font.family: keyRow.taking ? Theme.t.font : win.mono
                                font.weight: keyRow.modelData.own ? Font.DemiBold : Font.Normal; color: keyRow.taking ? Theme.t.accent : keyRow.modelData.own || keyRow.modelData.other ? Theme.t.text : Theme.t.text_secondary
                                text: keyRow.taking ? "Press the keys  (Esc: leave it, Backspace: none)" : keyRow.modelData.key || "—" }
                            Seg { visible: keyRow.modelData.own && !keyRow.taking; anchors { right: parent.right; rightMargin: 4; verticalCenter: parent.verticalCenter } icon: "refresh"; tip: "Back to Code's own"
                                onClicked: Backend.resetKey(keyRow.modelData.name) } } } }
                Row { visible: card.kind === "keys"; anchors { left: parent.left; leftMargin: 20; bottom: parent.bottom; bottomMargin: 18 } spacing: 4
                    Seg { text: "Settings…"; onClicked: win.ask("settings") }
                    Seg { text: "Put Them All Back"; onClicked: Backend.resetKeys() }
                    Seg { visible: Backend.vscodeFolder !== ""; text: "Bring from VS Code"; tipAbove: true; tip: "Your key bindings (and snippets and settings), from " + Backend.vscodeFolder; onClicked: toast.say(Backend.importFromVSCode(), false) } }
                // Languages: pick one for a new file (it starts with a few lines of it), or add what one needs: its helper
                // for suggestions and problems, and its tools for Run (from Ubuntu, or npm into your own folder)
                Label { visible: card.kind === "langs"; x: 24; y: 48; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                    text: win.sheet && win.sheet.mode === "new" ? "The file starts with a few lines of the language, in " + (Backend.root ? Backend.rootName : "Documents") + "."
                                                                : "Every language is coloured. Adding one puts in its helper (suggestions, problems, go to definition) and the tools Run uses." }
                ListView { id: langList; visible: card.kind === "langs"; x: 12; y: 86; width: parent.width - 24; height: parent.height - 150; clip: true; boundsBehavior: Flickable.StopAtBounds
                    model: card.kind === "langs" ? Backend.languages : []
                    delegate: Pressable { required property var modelData; width: langList.width; height: 46; radius: 10; color: hovered ? Theme.t.hover : "transparent"
                        onClicked: if (win.sheet.mode === "new") { Backend.newFileIn(modelData.name); win.sheet = null }   // (closing the sheet ends this row)
                        Label { x: 12; y: 6; text: modelData.name; font.weight: Font.DemiBold }
                        Label { x: 12; y: 25; font.pixelSize: 11; secondary: true
                            text: modelData.adding ? "Adding…" : modelData.helper ? "Ready · " + modelData.helper + (modelData.tools ? "" : " · its tools aren't in yet")
                                  : modelData.hasHelper ? "Colours only until its helper is added" : "Colours" + (modelData.tools ? "" : " · its tools aren't in yet") }
                        Label { anchors { right: addLang.left; rightMargin: 12; verticalCenter: parent.verticalCenter } text: modelData.ext; font.family: win.mono; font.pixelSize: 11; secondary: true }
                        Btn { id: addLang; anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                            visible: modelData.canAdd || modelData.adding; enabled: !modelData.adding; text: modelData.adding ? "Adding…" : "Add"
                            onClicked: { var lang = modelData.name; Backend.addLanguage(lang) } } } }
                // Branches: switch to one, start a new one from here, or delete one that's merged
                property var branchRows: card.kind === "branches" ? Backend.branches() : []
                Row { visible: card.kind === "branches"; x: 24; y: 52; width: parent.width - 48; spacing: 8
                    TextBox { id: branchName; width: parent.width - newBranchBtn.width - 8; mono: true; placeholder: "a new branch, from here"; onAccepted: newBranchBtn.clicked() }
                    Btn { id: newBranchBtn; text: "Start Branch"; primary: branchName.text.trim() !== ""; anchors.verticalCenter: parent.verticalCenter
                        onClicked: { var why = Backend.newBranch(branchName.text); if (why) toast.say(why, true); else { branchName.text = ""; win.sheet = null } } } }
                ListView { id: branchList; visible: card.kind === "branches"; x: 12; y: 100; width: parent.width - 24; height: parent.height - 164; clip: true; boundsBehavior: Flickable.StopAtBounds
                    model: card.branchRows
                    delegate: Pressable { required property var modelData; width: branchList.width; height: 46; radius: 10; color: modelData.current ? Qt.alpha(Theme.t.accent, 0.16) : hovered ? Theme.t.hover : "transparent"
                        onClicked: { if (modelData.current) return; var name = modelData.name, why = Backend.switchBranch(name); if (why) toast.say(why, true); else win.sheet = null }
                        Glyph { x: 12; anchors.verticalCenter: parent.verticalCenter; name: modelData.current ? "check" : "route"; size: 14; ink: modelData.current ? Theme.t.accent : Theme.t.icon }
                        Label { x: 36; y: 6; width: parent.width - 120; elide: Text.ElideRight; text: modelData.name; font.family: win.mono; font.weight: Font.DemiBold }
                        Label { x: 36; y: 25; width: parent.width - 120; elide: Text.ElideRight; font.pixelSize: 11; secondary: true
                            text: (modelData.current ? "You're on it" : "Switch to it") + (modelData.when ? " · " + modelData.when : "") + (modelData.subject ? " · " + modelData.subject : "") }
                        Seg { visible: !modelData.current; anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } icon: "trash"; tip: "Delete it (only if it's merged)"
                            onClicked: { var name = modelData.name, why = Backend.deleteBranch(name); if (why) toast.say(why, true); else card.branchRows = Backend.branches() } } } }
                Label { visible: ["dirty", "clash", "trash", "discard"].indexOf(card.kind) >= 0; x: 24; y: 52; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true
                    text: card.kind === "dirty" ? "If you don't save, your changes are lost." : card.kind === "clash" ? "Something else changed it since you opened it. Keep yours (overwrite) or take what's on disk?"
                        : card.kind === "trash" ? "You can put it back from the Trash in Files." : "This can't be undone: the file goes back to how it was at the last commit." }
                TextBox { id: nameBox; objectName: "nameBox"; visible: ["new", "rename", "run", "renamesym", "debugprog", "aiask", "unreal", "theme", "remote", "space"].indexOf(card.kind) >= 0; x: 24; y: 58; width: parent.width - 48; mono: card.kind === "run" || card.kind === "renamesym" || card.kind === "debugprog" || card.kind === "unreal" || card.kind === "remote"
                    placeholder: card.kind === "remote" ? "astrid@build-box:/srv/game" : card.kind === "theme" ? "for example: /home/you/Downloads/monokai-color-theme.json" : card.kind === "unreal" ? "for example: /home/you/UnrealEngine" : card.kind === "run" ? "for example: python3 -m aurora" : card.kind === "renamesym" ? "new name" : card.kind === "debugprog" ? "build/myprogram" : card.kind === "aiask" ? (win.sheet && win.sheet.mode === "write" ? "for example: a function that reads a CSV file into a list of dicts" : "for example: add error handling") : card.kind === "new" ? (win.sheet && win.sheet.dir ? "folder name" : "name.py, or folder/name.py") : ""
                    onAccepted: sheetOk.clicked() }
                Label { visible: card.kind === "aiask"; x: 24; y: 100; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                    text: (win.sheet && win.sheet.mode === "write" ? "Written in " + (win.tab && win.tab.lang ? win.tab.lang : "this file's language") + ", at the cursor"
                           : "On what's selected, or the whole file") + ". Huginn AI shows it first; nothing changes until you say so." }
                Label { visible: card.kind === "run" || card.kind === "debugprog" || card.kind === "renamesym" || card.kind === "unreal" || card.kind === "theme" || card.kind === "remote" || card.kind === "space"; x: 24; y: 100; width: parent.width - 48; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                    text: card.kind === "space" ? "Where to write the .code-workspace file. It is VS Code's own format: opening it there, or here, opens these folders together."
                        : card.kind === "remote" ? "Who, which computer, and the folder there (over SSH; the other computer needs nothing installed). Its files open here as if they were on this one; Run and Build happen there. If ssh needs a password, it asks in the terminal: Code never sees it." : card.kind === "theme" ? "A VS Code colour theme is a .json file (inside a theme extension, in its themes folder). Code takes its editor and syntax colours; the rest of the window keeps the system's look." : card.kind === "unreal" ? "The folder that holds Engine/ and Setup.sh: the one Epic's download unpacks to, or your clone of its source after Setup.sh and make. Code remembers it for every project." : card.kind === "run" ? "Kept in the project as .huginn-run, so it travels with it." : card.kind === "debugprog" ? "The program you built, with debugging information (gcc -g, cargo build). Kept in the project as .huginn-debug."
                        : "Every place it's used changes, in every file (the language helper finds them). Open files change but aren't saved." }
                // the folder picker
                Item { visible: card.kind === "open"; x: 16; y: 54; width: parent.width - 32; height: parent.height - 120
                    Row { id: crumbs; x: 8; spacing: 6; height: 30
                        Seg { icon: "up"; tip: "Up a folder"; onClicked: { var p = win.browseAt.replace(/\/[^\/]+\/?$/, ""); win.browseAt = p || "/" } }
                        Label { anchors.verticalCenter: parent.verticalCenter; text: win.browseAt.replace(Backend.home, "~"); width: card.width - 120; elide: Text.ElideLeft; font.family: win.mono; font.pixelSize: 12 } }
                    ListView { id: folders; y: 36; width: parent.width; height: parent.height - 36; clip: true; boundsBehavior: Flickable.StopAtBounds
                        model: card.kind === "open" ? (Backend.recent.length && win.browseAt === Backend.home ? Backend.recent.map(function (r) { return { name: r.name, path: r.path, git: false, recent: r.where } }).concat(Backend.browse(win.browseAt)) : Backend.browse(win.browseAt)) : []
                        delegate: Pressable { required property var modelData; width: folders.width; height: 38; radius: 9; color: hovered ? Theme.t.hover : "transparent"
                            onClicked: win.browseAt = modelData.path
                            onDoubleClicked: { var p = modelData.path; var be = Backend; win.sheet = null; be.openFolder(p) }
                            Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: modelData.recent ? "history" : "folder"; size: 15; ink: modelData.recent ? Theme.t.accent : Theme.t.icon }
                            Label { x: 36; width: parent.width - 180; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.name }
                            Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } font.pixelSize: 11; secondary: true
                                text: modelData.recent ? "recent · " + modelData.recent : modelData.git ? "Git" : "" } } } }
                // a diff
                ListView { id: diffList; visible: card.kind === "diff"; x: 12; y: 56; width: parent.width - 24; height: parent.height - 120; clip: true; boundsBehavior: Flickable.StopAtBounds
                    model: card.kind === "diff" ? win.sheet.rows : []
                    header: Column { visible: !!(win.sheet && win.sheet.commit && win.sheet.commit.sha); width: diffList.width; spacing: 2; bottomPadding: visible ? 10 : 0
                        height: visible ? implicitHeight : 0
                        Label { width: parent.width; wrapMode: Text.WordWrap; text: win.sheet && win.sheet.commit ? win.sheet.commit.message || "" : ""; font.pixelSize: 13; font.weight: Font.DemiBold }
                        Label { text: win.sheet && win.sheet.commit ? (win.sheet.commit.sha || "").substring(0, 10) + "  ·  " + win.sheet.commit.author + "  ·  " + win.sheet.commit.when + "  ·  " + ((win.sheet.commit.files || []).length === 1 ? "1 file" : (win.sheet.commit.files || []).length + " files") : ""
                            font.pixelSize: 11; secondary: true; font.family: win.mono } }
                    delegate: Rectangle { required property var modelData; width: diffList.width; height: modelData.kind === "hunk" ? 30 : modelData.kind === "file" ? 32 : 20
                        color: modelData.kind === "add" ? Qt.rgba(0.25, 0.73, 0.31, 0.16) : modelData.kind === "del" ? Qt.rgba(0.97, 0.32, 0.29, 0.16) : modelData.kind === "hunk" ? Theme.t.hover : modelData.kind === "file" ? Qt.alpha(Theme.t.accent, 0.14) : "transparent"
                        Text { x: 6; width: 34; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.old; color: win.gutterInk; font.family: win.mono; font.pixelSize: 11 }
                        Text { x: 44; width: 34; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.new; color: win.gutterInk; font.family: win.mono; font.pixelSize: 11 }
                        Text { x: modelData.kind === "file" ? 10 : 86; anchors.verticalCenter: parent.verticalCenter; text: (modelData.kind === "add" ? "+ " : modelData.kind === "del" ? "− " : modelData.kind === "hunk" || modelData.kind === "file" ? "" : "  ") + modelData.text
                            color: modelData.kind === "hunk" ? Theme.t.text_secondary : Theme.t.text; font.family: win.mono; font.pixelSize: 12; font.weight: modelData.kind === "file" ? Font.Bold : Font.Normal; textFormat: Text.PlainText } } }
                Label { visible: card.kind === "diff" && diffList.count === 0; anchors.centerIn: parent; secondary: true; text: "No differences" }
                Row { anchors { right: parent.right; rightMargin: 20; bottom: parent.bottom; bottomMargin: 18 } spacing: 8
                    Btn { visible: card.kind === "dirty"; text: "Don't Save"; onClicked: { var t = win.sheet.tab; win.sheet = null; Backend.close(t, true) } }
                    Btn { visible: card.kind === "new" && !(win.sheet && win.sheet.dir); text: "In a Language…"; onClicked: win.ask("langs", { mode: "new" }) }
                    Btn { text: card.kind === "diff" || card.kind === "branches" || card.kind === "settings" || card.kind === "keys" || card.kind === "history" || card.kind === "extensions" || card.kind === "langs" && win.sheet.mode !== "new" ? "Done" : "Cancel"; onClicked: win.sheet = null }
                    Btn { visible: card.kind === "diff" && !!win.sheet.restore; text: "Go Back to This Version"; onClicked: { var r = win.sheet.restore; win.sheet = null; if (Backend.historyRestore(r.tab, r.id)) toast.say("That version is in the editor. Save to keep it; undo brings back what was here.", false) } }
                    Btn { visible: card.kind === "diff" && !win.sheet.staged && !!win.sheet.canStage; text: "Stage"; onClicked: { Backend.stage(win.sheet.rel); win.sheet = null } }
                    Btn { visible: card.kind === "clash"; text: "Take Theirs"; onClicked: { var t = win.sheet.tab; win.sheet = null; Backend.reload(t) } }
                    Btn { id: sheetOk; visible: card.kind !== "diff" && card.kind !== "langs" && card.kind !== "branches" && card.kind !== "settings" && card.kind !== "keys" && card.kind !== "history" && card.kind !== "attach" && card.kind !== "extensions" && !(card.kind === "container" && Backend.container.problem); primary: card.kind !== "trash" && card.kind !== "discard"; danger: card.kind === "trash" || card.kind === "discard"
                        text: ({ "open": win.sheet && win.sheet.add ? "Add This Folder" : "Open This Folder", "space": "Write It", "dirty": "Save", "clash": "Keep Mine", "new": "Make", "rename": "Rename", "trash": "Move to Trash", "run": "Use It", "discard": "Throw Away", "renamesym": "Rename", "debugprog": "Debug", "aiask": "Ask", "unreal": "Use This Folder", "theme": "Use This Theme", "remote": "Connect", "container": "Start It" })[card.kind] || "OK"
                        onClicked: {
                            var s = win.sheet, why = ""
                            if (s.kind === "open" && s.add) { var why = Backend.addFolder(win.browseAt); if (why) { toast.say(why, true); return } win.sheet = null; return }
                            if (s.kind === "space") { var bad = Backend.saveWorkspace(nameBox.text); if (bad) { toast.say(bad, true); return } win.sheet = null; toast.say("The workspace was written to " + Backend.workspaceFile + ".", false); return }
                            if (s.kind === "open") { win.sheet = null; Backend.openFolder(win.browseAt); return }
                            if (s.kind === "dirty") { if (Backend.save(s.tab, false) === "") { win.sheet = null; Backend.close(s.tab, true) } return }
                            if (s.kind === "clash") { win.sheet = null; Backend.save(s.tab, true); return }
                            if (s.kind === "new") why = Backend.create(s.folder, nameBox.text, s.dir)
                            else if (s.kind === "rename") why = Backend.rename(s.path, nameBox.text)
                            else if (s.kind === "trash") why = Backend.remove(s.path)
                            else if (s.kind === "discard") why = Backend.discard(s.rel)
                            else if (s.kind === "run") { Backend.setRun(nameBox.text); win.sheet = null; return }
                            else if (s.kind === "renamesym") { win.sheet = null; Backend.renameSymbol(s.tab, s.line, s.col, nameBox.text); return }
                            else if (s.kind === "remote") { var bad = Backend.remoteConnect(nameBox.text); if (bad) { toast.say(bad, true); return } win.sheet = null; win.bottom = "terminal"; win.term = true; return }
                            else if (s.kind === "theme") { var no = Backend.importTheme(nameBox.text); if (no) { toast.say(no, true); return } win.sheet = null; return }
                            else if (s.kind === "unreal") { var why = Backend.build.setUnreal(nameBox.text); if (why) { toast.say(why, true); return } win.sheet = null; win.showBuild(); return }
                            else if (s.kind === "container") { var no = Backend.containerOpen(); if (no) { toast.say(no, true); return } win.sheet = null; win.bottom = "terminal"; win.term = true; return }
                            else if (s.kind === "debugprog") { win.sheet = null; win.bottom = "debug"; win.term = true; Backend.startDebug(nameBox.text); return }
                            else if (s.kind === "aiask") { var said = nameBox.text.trim(); if (!said) return; win.sheet = null; win.aiCode(s.mode, said); return }
                            if (why) toast.say(why, true); else win.sheet = null } } } } }
    ]
    onSheetChanged: if (sheet && ["new", "rename", "run", "renamesym", "debugprog", "aiask", "unreal", "theme", "remote"].indexOf(sheet.kind) >= 0) {
        nameBox.text = sheet.kind === "rename" || sheet.kind === "renamesym" ? sheet.name : sheet.kind === "run" || sheet.kind === "debugprog" || sheet.kind === "unreal" || sheet.kind === "theme" || sheet.kind === "remote" || sheet.kind === "space" ? (sheet.now || "") : ""; nameBox.focusIn(); nameBox.input.selectAll() }

    // ================================================================ the side island
    Rectangle { id: sideBox; visible: win.side; x: 12; y: 64; width: win.sideW; height: parent.height - y - 12; radius: 18; color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine; clip: true
        Row { id: panes; x: 10; y: 10; spacing: 4
            Repeater { model: [["files", "folder", "Files (Ctrl+Shift+E)"], ["search", "search", "Search (Ctrl+Shift+F)"], ["git", "route", "Changes (Ctrl+Shift+G)"], ["problems", "info", "Problems (Ctrl+Shift+M)"], ["tests", "check", "Tests (Ctrl+Shift+T)"], ["outline", "list", "Outline"]]
                Seg { required property var modelData; icon: modelData[1]; tip: modelData[2]; on: win.panel === modelData[0]; onClicked: win.showPanel(modelData[0])
                    Rectangle { visible: (modelData[0] === "git" && Backend.changes.length > 0) || (modelData[0] === "problems" && Backend.problems.length > 0)
                                         || (modelData[0] === "tests" && Backend.tests.some(function (t) { return t.status === "failed" }))
                        anchors { right: parent.right; top: parent.top } width: 8; height: 8; radius: 4; color: modelData[0] === "git" ? win.modInk : win.delInk } } } }

        // ---- files
        Item { visible: win.panel === "files"; x: 0; y: 52; width: parent.width; height: parent.height - 52
            Row { x: 14; width: parent.width - 28; height: 28; spacing: 4
                Label { width: parent.width - 96; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: (Backend.folders.length ? "Workspace · " + Backend.folders.length + " folders" : Backend.rootName || "No folder").toUpperCase(); font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1; secondary: true }
                Seg { visible: !!Backend.root; icon: "plus"; tip: "New file"; onClicked: win.ask("new", { folder: Backend.root, dir: false }) }
                Seg { visible: !!Backend.root; icon: "folder"; tip: "New folder"; onClicked: win.ask("new", { folder: Backend.root, dir: true }) } }
            // a right-click on the list's empty space, or on its heading, is the project folder's own menu
            function rootMenu(item, m) { if (!Backend.root) return; var p = item.mapToItem(win.contentItem, m.x, m.y)
                win.menuFor = { path: Backend.root, name: Backend.rootName, dir: true, root: true, x: p.x, y: p.y } }
            MouseArea { objectName: "explorerBack"; y: 0; width: parent.width; height: parent.height; acceptedButtons: Qt.RightButton; onClicked: function (m) { parent.rootMenu(this, m) } }
            ListView { id: explorer; objectName: "explorer"; y: 32; width: parent.width; height: parent.height - 32; clip: true; model: Backend.tree; boundsBehavior: Flickable.StopAtBounds; reuseItems: true
                delegate: Pressable { id: row; required property var modelData; width: explorer.width - 12; x: 6; height: 26; radius: 7
                    readonly property bool on: !!win.tab && win.tab.path === modelData.path
                    color: on ? Qt.alpha(Theme.t.accent, 0.2) : hovered ? Theme.t.hover : "transparent"
                    onClicked: modelData.dir ? Backend.toggle(modelData.path) : Backend.openFile(modelData.path)
                    readonly property bool isTop: !!modelData.root                 // a workspace folder's heading
                    MouseArea { anchors.fill: parent; acceptedButtons: Qt.RightButton
                        onClicked: function (m) { var p = row.mapToItem(win.contentItem, m.x, m.y); win.menuFor = { path: row.modelData.path, name: row.modelData.name, dir: row.modelData.dir, root: row.isTop, space: row.isTop, x: p.x, y: p.y } } }
                    Rectangle { visible: row.isTop && !!row.modelData.active; anchors { right: parent.right; rightMargin: 9; verticalCenter: parent.verticalCenter } width: 7; height: 7; radius: 4; color: Theme.t.accent }
                    Text { x: 8 + row.modelData.depth * 14; width: 12; anchors.verticalCenter: parent.verticalCenter; text: row.modelData.dir ? (row.modelData.open ? "▾" : "▸") : ""; color: Theme.t.text_secondary; font.pixelSize: 11 }
                    Rectangle { visible: !row.modelData.dir; x: 11 + row.modelData.depth * 14; anchors.verticalCenter: parent.verticalCenter; width: 7; height: 7; radius: 2; color: win.langInk(row.modelData.lang) }
                    Label { x: 24 + row.modelData.depth * 14; width: parent.width - x - 24; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: row.isTop ? row.modelData.name.toUpperCase() : row.modelData.name
                        font.pixelSize: row.isTop ? 11 : 12; font.weight: row.isTop ? Font.Bold : Font.Normal; font.letterSpacing: row.isTop ? 0.8 : 0
                        opacity: row.modelData.dim ? 0.55 : 1; color: row.modelData.git && row.modelData.git !== "inside" ? win.gitInk(row.modelData.git) : Theme.t.text }
                    Label { anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } text: win.gitLetter(row.modelData.git); font.pixelSize: 11; font.weight: Font.Bold; color: win.gitInk(row.modelData.git) } }
                Column { visible: !Backend.root; anchors.centerIn: parent; spacing: 10; width: parent.width - 40
                    Label { width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true; text: "Open a folder to see its files here." }
                    Btn { anchors.horizontalCenter: parent.horizontalCenter; primary: true; text: "Open Folder…"; onClicked: { win.browseAt = Backend.home; win.ask("open") } } } } }

        // ---- search
        Item { visible: win.panel === "search"; x: 12; y: 52; width: parent.width - 24; height: parent.height - 52
            Column { id: sCol; width: parent.width; spacing: 8
                TextBox { id: searchBox; objectName: "searchBox"; width: parent.width; placeholder: "Search the project"; onAccepted: win.runSearch(); onEdited: searchTimer.restart() }
                Row { spacing: 4
                    Seg { id: sCase; text: "Aa"; tip: "Match case"; property bool on2: false; on: on2; onClicked: { on2 = !on2; win.runSearch() } }
                    Seg { id: sWord; text: "W"; tip: "Whole words"; property bool on2: false; on: on2; onClicked: { on2 = !on2; win.runSearch() } }
                    Seg { id: sRe; text: ".*"; tip: "Pattern (regular expression)"; property bool on2: false; on: on2; onClicked: { on2 = !on2; win.runSearch() } } }
                TextBox { id: sReplace; width: parent.width; placeholder: "Replace with (optional)" }
                Row { spacing: 8
                    Label { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 11; secondary: true
                        text: Backend.resultsTitle !== "" ? Backend.resultsTitle : Backend.searching ? "Searching…" : Backend.results.length === 1 ? "1 match" : Backend.results.length ? (Backend.results.length === 1 ? "1 match" : Backend.results.length + (Backend.results.length >= 2000 ? "+" : "") + " matches") : searchBox.text ? "No matches" : "" }
                    Btn { visible: Backend.results.length > 0 && sReplace.text !== ""; text: "Replace All"; onClicked: toast.say("Replaced " + Backend.replaceAll(searchBox.text, sReplace.text, sCase.on2, sRe.on2, sWord.on2) + " places", false) } } }
            ListView { id: hits; objectName: "hits"; y: sCol.height + 10; width: parent.width; height: parent.height - y; clip: true; boundsBehavior: Flickable.StopAtBounds; reuseItems: true
                model: win.searchRows(Backend.results)
                delegate: Pressable { required property var modelData; width: hits.width; height: modelData.header ? 28 : 24; radius: 6; color: hovered && !modelData.header ? Theme.t.hover : "transparent"
                    onClicked: if (!modelData.header && modelData.line >= 0) Backend.openRel(modelData.path, modelData.line, modelData.col)
                    Label { visible: modelData.header; x: 2; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 30; elide: Text.ElideLeft; text: modelData.path; font.pixelSize: 11; font.weight: Font.Bold }
                    Label { visible: modelData.header; anchors { right: parent.right; rightMargin: 4; verticalCenter: parent.verticalCenter } text: modelData.count || ""; font.pixelSize: 10; secondary: true }
                    Text { visible: !modelData.header; x: 12; width: parent.width - 16; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; textFormat: Text.StyledText; font.family: win.mono; font.pixelSize: 11; color: Theme.t.text
                        text: { if (modelData.header) return ""; var t = modelData.text || "", c = modelData.col || 0, n = modelData.length || 0, s = Math.max(0, c - 24)
                            function esc(x) { return x.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
                            return (s ? "…" : "") + esc(t.substring(s, c).replace(/^\s+/, "")) + "<b><font color='" + Theme.t.accent + "'>" + esc(t.substr(c, n)) + "</font></b>" + esc(t.substring(c + n, c + n + 80)) } } } } }

        // ---- changes (Git)
        Item { id: gitPanel; objectName: "gitPanel"; visible: win.panel === "git"; x: 12; y: 52; width: parent.width - 24; height: parent.height - 52
            Column { visible: !Backend.isGit; width: parent.width; spacing: 10; y: 20
                Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; text: Backend.root ? "This folder isn't a Git repository yet." : "Open a folder first." }
                Btn { visible: !!Backend.root; text: "Make It a Repository"; onClicked: Backend.initRepo() } }
            Row { id: gSwitch; visible: Backend.isGit; spacing: 2; height: 30
                Seg { text: "Changes"; on: win.gitView === "changes"; onClicked: win.gitView = "changes" }
                Seg { objectName: "historyTab"; text: "History"; on: win.gitView === "history"; onClicked: { win.gitView = "history"; win.historyRows = Backend.history("") } } }
            // the history: commits with their graph; click one to see what it changed
            ListView { id: histList; objectName: "histList"; visible: Backend.isGit && win.gitView === "history"; y: 38; width: parent.width; height: parent.height - 38; clip: true
                model: win.historyRows; boundsBehavior: Flickable.StopAtBounds
                delegate: Pressable { id: hc; required property var modelData; required property int index; width: histList.width; height: 44; radius: 8; color: hovered ? Theme.t.hover : "transparent"
                    onClicked: win.showCommit(modelData.sha, modelData.subject)
                    readonly property real lw: 12
                    Canvas { id: graph; x: 4; width: Math.max(1, hc.modelData.width) * hc.lw + 6; height: parent.height
                        onPaint: { var c = getContext("2d"); c.reset(); var cols = ["#7C9CFF", "#3DDC84", "#F5B83D", "#FF6FAE", "#43D9B8", "#B57BFF"]
                            var m = hc.modelData, mid = height / 2
                            for (var k = 0; k < (m.down || []).length; k++) { var a = m.down[k][0], b = m.down[k][1]; c.strokeStyle = cols[a % cols.length]; c.lineWidth = 2; c.beginPath()
                                c.moveTo(6 + a * hc.lw, a === m.lane ? mid : 0); c.bezierCurveTo(6 + a * hc.lw, height * 0.85, 6 + b * hc.lw, height * 0.85, 6 + b * hc.lw, height); c.stroke() }
                            for (var j = 0; j < m.width; j++) if (j !== m.lane && (m.down || []).some(function (d) { return d[0] === j })) { c.strokeStyle = cols[j % cols.length]; c.beginPath(); c.moveTo(6 + j * hc.lw, 0); c.lineTo(6 + j * hc.lw, mid); c.stroke() }
                            if (hc.index !== 0) { c.strokeStyle = cols[m.lane % cols.length]; c.beginPath(); c.moveTo(6 + m.lane * hc.lw, 0); c.lineTo(6 + m.lane * hc.lw, mid); c.stroke() }
                            c.fillStyle = cols[m.lane % cols.length]; c.beginPath(); c.arc(6 + m.lane * hc.lw, mid, 4.5, 0, Math.PI * 2); c.fill() } }
                    Column { x: graph.width + 10; anchors.verticalCenter: parent.verticalCenter; width: parent.width - x - 8
                        Row { spacing: 6; width: parent.width
                            Rectangle { visible: !!hc.modelData.refs; height: 15; width: refL.width + 10; radius: 7; color: Qt.alpha(Theme.t.accent, 0.25); anchors.verticalCenter: parent.verticalCenter
                                Label { id: refL; anchors.centerIn: parent; text: (hc.modelData.refs || "").replace("HEAD -> ", "").split(",")[0]; font.pixelSize: 9 } }
                            Label { width: parent.width - (hc.modelData.refs ? refL.width + 16 : 0); elide: Text.ElideRight; text: hc.modelData.subject; font.pixelSize: 12 } }
                        Label { text: hc.modelData.short + "  ·  " + hc.modelData.author + "  ·  " + hc.modelData.when; font.pixelSize: 10; secondary: true; font.family: win.mono } } }
                Label { visible: histList.count === 0; anchors.centerIn: parent; secondary: true; text: "No commits yet" } }
            Column { id: gCol; visible: Backend.isGit && win.gitView === "changes"; y: 38; width: parent.width; spacing: 8
                Row { spacing: 6; height: 30
                    Glyph { name: "route"; size: 14; anchors.verticalCenter: parent.verticalCenter; ink: Theme.t.accent }
                    Label { anchors.verticalCenter: parent.verticalCenter; text: Backend.branch || "no branch"; font.weight: Font.DemiBold; width: gCol.width - 154; elide: Text.ElideRight
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: win.ask("branches") } }
                    Seg { icon: "split"; tip: "Branches"; onClicked: win.ask("branches") }
                    Seg { icon: "down"; tip: "Pull"; onClicked: Backend.sync("pull") }
                    Seg { icon: "up"; tip: "Push"; onClicked: Backend.sync("push") } }
                TextBox { id: commitBox; objectName: "commitBox"; width: parent.width; lines: 3; placeholder: "What changed? (the commit message)" }
                Row { spacing: 8
                    Btn { primary: true; text: "Commit"; onClicked: { var why = Backend.commit(commitBox.many); if (why) toast.say(why, true); else commitBox.many = "" } }
                    Btn { text: "Stage All"; onClicked: Backend.stageAll() }
                    Label { visible: Backend.busy !== ""; anchors.verticalCenter: parent.verticalCenter; text: Backend.busy + "…"; secondary: true; font.pixelSize: 11 } }
                Label { text: Backend.changes.length ? Backend.changes.length + " changed" : "Nothing changed since the last commit"; font.pixelSize: 11; secondary: true; topPadding: 4 } }
            ListView { id: changeList; visible: Backend.isGit && win.gitView === "changes"; y: gCol.y + gCol.height + 8; width: parent.width; height: parent.height - y; clip: true; model: Backend.changes; boundsBehavior: Flickable.StopAtBounds
                delegate: Pressable { id: ch; required property var modelData; width: changeList.width; height: 30; radius: 8; color: hovered ? Theme.t.hover : "transparent"
                    onClicked: win.ask("diff", { rel: modelData.path, staged: modelData.staged && !modelData.unstaged, rows: Backend.diff(modelData.path, modelData.staged && !modelData.unstaged), canStage: modelData.unstaged })
                    onDoubleClicked: Backend.openRel(modelData.path, -1, 0)
                    Text { x: 6; width: 14; anchors.verticalCenter: parent.verticalCenter; text: win.gitLetter(ch.modelData.kind); color: win.gitInk(ch.modelData.kind); font.weight: Font.Bold; font.pixelSize: 11 }
                    Label { x: 24; width: parent.width - 24 - (ch.hovered ? 84 : 26); elide: Text.ElideLeft; anchors.verticalCenter: parent.verticalCenter; text: ch.modelData.path; font.pixelSize: 12 }
                    Rectangle { visible: ch.modelData.staged && !ch.hovered; anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } width: 8; height: 8; radius: 4; color: win.addInk }
                    Row { visible: ch.hovered; anchors { right: parent.right; rightMargin: 4; verticalCenter: parent.verticalCenter } spacing: 2
                        Seg { visible: ch.modelData.kind === "conflict"; icon: "check"; tip: "Settled: mark it resolved"; onClicked: { var why = Backend.markResolved(ch.modelData.path); if (why) toast.say(why, !/resolved/.test(why)) } }
                        Seg { icon: "back"; tip: "Throw away these changes"; onClicked: win.ask("discard", { rel: ch.modelData.path }) }
                        Seg { icon: ch.modelData.staged && !ch.modelData.unstaged ? "x" : "plus"; tip: ch.modelData.staged && !ch.modelData.unstaged ? "Unstage" : "Stage"
                            onClicked: ch.modelData.staged && !ch.modelData.unstaged ? Backend.unstage(ch.modelData.path) : Backend.stage(ch.modelData.path) } } } } }

        // ---- outline: the file's functions, classes and headings
        ListView { id: outlineList; objectName: "outlineList"; visible: win.panel === "outline"; x: 10; y: 56; width: parent.width - 20; height: parent.height - 66; clip: true
            model: win.outlineRows; boundsBehavior: Flickable.StopAtBounds
            Timer { id: outlineTick; interval: 600; onTriggered: if (win.panel === "outline") win.refreshOutline() }
            Connections { target: Backend; function onChanged() { if (win.panel === "outline") outlineTick.restart() } }
            delegate: Pressable { required property var modelData; width: outlineList.width; height: 26; radius: 7
                readonly property bool here: win.curLine - 1 >= modelData.line && win.curLine - 1 <= modelData.end
                color: here ? Qt.alpha(Theme.t.accent, 0.14) : hovered ? Theme.t.hover : "transparent"
                onClicked: { var v = win.view(); if (v) v.goTo(modelData.line, 0) }
                Text { x: 8 + Math.min(6, modelData.depth) * 14; width: 16; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 11; font.bold: true
                    color: modelData.kind === "class" || modelData.kind === "struct" || modelData.kind === "interface" ? "#F0B72F" : modelData.kind === "heading" ? Theme.t.text_secondary : "#B392F0"
                    text: modelData.kind === "heading" ? "#" : modelData.kind === "class" || modelData.kind === "struct" || modelData.kind === "interface" || modelData.kind === "enum" ? "C" : "ƒ" }
                Label { x: 26 + Math.min(6, modelData.depth) * 14; width: parent.width - x - 40; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.pixelSize: 12 }
                Label { anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } text: modelData.line + 1; font.pixelSize: 10; secondary: true } }
            Label { visible: outlineList.count === 0; anchors.centerIn: parent; width: parent.width - 40; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
                text: "No functions, classes or headings found in this file" } }

        // ---- problems
        ListView { id: probList; objectName: "probList"; visible: win.panel === "problems"; x: 10; y: 56; width: parent.width - 20; height: parent.height - 66; clip: true; model: Backend.problems
            boundsBehavior: Flickable.StopAtBounds
            delegate: Pressable { required property var modelData; width: probList.width; height: probText.height + 26; radius: 8; color: hovered ? Theme.t.hover : "transparent"
                onClicked: { Backend.select(modelData.tab); Qt.callLater(function () { var v = docs.itemAt(modelData.tab); if (v) v.goTo(modelData.line, modelData.col) }) }
                Rectangle { x: 8; y: 9; width: 8; height: 8; radius: 4; color: modelData.severity === 1 ? win.delInk : modelData.severity === 2 ? "#E3B341" : win.modInk }
                Label { id: probText; x: 24; y: 5; width: parent.width - 30; wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight; text: modelData.message; font.pixelSize: 12 }
                Label { x: 24; y: probText.height + 7; text: modelData.name + "  " + (modelData.line + 1) + ":" + (modelData.col + 1) + (modelData.source ? "  ·  " + modelData.source : ""); font.pixelSize: 10; secondary: true } }
            Label { visible: probList.count === 0; anchors.centerIn: parent; secondary: true; text: "No problems in your open files" } }

        // ---- tests
        Item { id: testPanel; objectName: "testPanel"; visible: win.panel === "tests"; x: 12; y: 52; width: parent.width - 24; height: parent.height - 52
            readonly property int failed: Backend.tests.filter(function (t) { return t.status === "failed" }).length
            readonly property int passed: Backend.tests.filter(function (t) { return t.status === "passed" }).length
            Row { id: tRow; spacing: 4; height: 30
                Btn { objectName: "runAll"; primary: true; text: Backend.testBusy === "Running tests…" ? "Running…" : "Run All"; enabled: Backend.tests.length > 0 && Backend.testBusy === ""; onClicked: Backend.runTests([]) }
                Seg { visible: Backend.testBusy === "Running tests…"; icon: "stop"; tip: "Stop"; onClicked: Backend.stopTests() }
                Seg { icon: "refresh"; tip: "Find the tests again"; onClicked: Backend.discoverTests() }
                Seg { visible: Backend.testOutput !== ""; icon: "list"; tip: "What the last run printed"; onClicked: win.ask("diff", { rel: "", staged: false, rows: Backend.testOutput.split("\n").map(function (l) { return { text: l, kind: "same", old: "", new: "" } }) }) } }
            Label { y: 36; width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; secondary: true
                text: Backend.testBusy !== "" ? Backend.testBusy : !Backend.testKind ? "No tests found. Code runs pytest, cargo test and go test." :
                      (Backend.tests.length + " tests (" + ({ pytest: "pytest", cargo: "cargo test", go: "go test" })[Backend.testKind] + ")" + (testPanel.passed + testPanel.failed ? "  ·  " + testPanel.passed + " passed" + (testPanel.failed ? ", " + testPanel.failed + " failed" : "") : "")) }
            ListView { id: testList; objectName: "testList"; y: 60; width: parent.width; height: parent.height - 60; clip: true; model: Backend.tests; boundsBehavior: Flickable.StopAtBounds
                section.property: "group"
                section.delegate: Label { required property string section; width: testList.width; elide: Text.ElideLeft; text: section; font.pixelSize: 10; font.weight: Font.Bold; secondary: true; topPadding: 8; leftPadding: 4 }
                delegate: Pressable { id: tc; required property var modelData; width: testList.width; height: msg.visible ? 30 + msg.height + 6 : 28; radius: 8; color: hovered ? Theme.t.hover : "transparent"
                    onClicked: Backend.openTest(modelData.id)
                    Rectangle { x: 8; y: 10; width: 9; height: 9; radius: 4.5
                        color: tc.modelData.status === "passed" ? "#3DDC84" : tc.modelData.status === "failed" ? win.delInk : tc.modelData.status === "running" ? "#F5B83D" : tc.modelData.status === "skipped" ? "#9CA3AF" : Theme.t.islandLine }
                    Label { x: 24; y: 6; width: parent.width - 60; elide: Text.ElideRight; text: tc.modelData.name; font.pixelSize: 12; font.family: win.mono }
                    Seg { visible: tc.hovered; anchors { right: parent.right; rightMargin: 2 } y: 1; icon: "play"; tip: "Run this test"; onClicked: Backend.runTests([tc.modelData.id]) }
                    Text { id: msg; visible: tc.modelData.status === "failed" && tc.modelData.message !== ""; x: 24; y: 26; width: parent.width - 30; wrapMode: Text.WrapAnywhere; maximumLineCount: 6; elide: Text.ElideRight
                        text: tc.modelData.message; color: win.delInk; font.family: win.mono; font.pixelSize: 10; textFormat: Text.PlainText } } } }
    }
    Timer { id: searchTimer; interval: 350; onTriggered: win.runSearch() }
    function runSearch() { Backend.search(searchBox.text, sCase.on2, sRe.on2, sWord.on2) }

    // ================================================================ the slab: the code
    Rectangle { id: slab; objectName: "slab"; x: win.sideW + (win.side ? 24 : 12); y: win.zen ? 56 : 64; width: parent.width - x - 12; height: parent.height - y - (win.zen ? 12 : 46) - (termBox.visible ? termBox.height + 10 : 0)
        radius: 18; color: win.slab; border.width: 1; border.color: Theme.t.islandLine; clip: true
        Repeater { id: docs; model: docModel
            delegate: Item { id: v; required property string path; required property int index
                readonly property int side: !win.split ? (index === Backend.current ? 0 : -1) : (index === Backend.current ? win.pane : index === win.otherTab ? 1 - win.pane : -1)
                visible: side >= 0; y: 0; height: parent.height
                x: win.split && side === 1 ? parent.width / 2 + 1 : 0; width: win.split ? parent.width / 2 - 1 : parent.width
                property var bps: []
                property string known: ""
                property var blameRows: []
                readonly property var blameNow: blameRows.length ? blameRows[Math.max(0, Math.min(blameRows.length - 1, win.curLine - 1))] || null : null
                function loadBlame() { blameRows = win.blameOn ? Backend.blame(index) : [] }
                Connections { target: win; function onBlameOnChanged() { v.loadBlame() } }
                Connections { target: Backend; function onTextLoaded(i) { if (i === v.index && win.blameOn) v.loadBlame() } }
                function renameHere() { var lc = lineCol(); var w = Backend.wordAt(index, lc[0], lc[1]); if (w) win.ask("renamesym", { tab: index, line: lc[0], col: lc[1], name: w }) }
                function referencesHere() { var lc = lineCol(); Backend.references(index, lc[0], lc[1]); win.showPanel("search") }
                property bool loading: false
                // Huginn AI's suggestion as you type (grey, after the cursor; Tab takes it, Escape or typing drops it)
                property string ghost: ""
                property string ghostBuf: ""
                property int ghostAt: -1
                property int ghostJob: -1
                property string ghostText: ""
                function dropGhost() { if (ghostJob >= 0) AI.stop(ghostJob); ghostJob = -1; ghost = ""; ghostBuf = "" }
                function askGhost() {
                    if (!win.aiInline || !v.visible || !edit.activeFocus || edit.selectedText !== "" || win.comp.length || v.extra.length || v.info.readOnly) return
                    var at = edit.cursorPosition, t = edit.text
                    if (t.trim() === "" || /\S/.test(t.substring(at, t.indexOf("\n", at) < 0 ? t.length : t.indexOf("\n", at)).replace(/[)\]}"';,]+$/, ""))) return   // (mid-line: only at its end)
                    dropGhost()
                    ghostAt = at; ghostText = t
                    ghostJob = AI.ask("complete-code", t.substring(Math.max(0, at - 4000), at) + "<CURSOR>" + t.substring(at, at + 800), { lang: v.info.lang || "", limit: 160 })
                }
                function ghostReady() {
                    if (edit.cursorPosition !== ghostAt || edit.text !== ghostText) { ghost = ""; return }
                    var g = AI.clean(ghostBuf).replace(/\s+$/, ""), lineStart = ghostText.lastIndexOf("\n", ghostAt - 1) + 1, typed = ghostText.substring(lineStart, ghostAt)
                    if (typed.trim() !== "" && g.indexOf(typed.trim()) === 0) g = g.substring(typed.trim().length)       // (it said the line again)
                    else if (typed !== "" && g.indexOf(typed) === 0) g = g.substring(typed.length)
                    ghost = g.replace(/^\n+/, typed.trim() === "" ? "" : "\n")
                }
                function acceptGhost() { var g = ghost, at = ghostAt; dropGhost(); edit.insert(at, g); edit.cursorPosition = at + g.length }
                Timer { id: ghostTick; interval: 750; onTriggered: v.askGhost() }
                Connections { target: win.aiInline ? AI : null
                    function onChunk(id, piece) { if (id === v.ghostJob) v.ghostBuf += piece }
                    function onDone(id, why) { if (id !== v.ghostJob) return; v.ghostJob = -1; if (!why) v.ghostReady() } }
                property var marks: ({})
                property var probs: []
                property var starts: [0]
                // ---- folding: lines folded away take no room, so a line's row on screen is no longer its number
                property var hid: []                         // [[first, last]…] the runs of hidden lines, in order
                property var foldable: []                    // [[start, end]…] what could be folded
                readonly property int hidCount: { var n = 0; for (var k = 0; k < hid.length; k++) n += hid[k][1] - hid[k][0] + 1; return n }
                function row(line) { var r = line; for (var k = 0; k < hid.length && hid[k][0] <= line; k++) r -= Math.min(line, hid[k][1]) - hid[k][0] + 1; return r }
                function lineAt(row) { var l = row; for (var k = 0; k < hid.length && hid[k][0] <= l; k++) l += hid[k][1] - hid[k][0] + 1; return l }
                function isHidden(line) { for (var k = 0; k < hid.length; k++) if (line >= hid[k][0] && line <= hid[k][1]) return true; return false }
                function relayout() { edit.font.pixelSize = Backend.size + 1; edit.font.pixelSize = Qt.binding(function () { return Backend.size }) }     // (the text is laid out again: nothing lighter does it)
                function refold() {
                    hid = Backend.hiddenOf(index); relayout()
                    var lc = lineCol()
                    if (isHidden(lc[0])) { var k = lc[0]; while (k > 0 && isHidden(k)) k--; lineStarts(); edit.cursorPosition = posOf(k + 1, 0) - 1 }     // the cursor never stays in what's folded
                }
                function foldHere(way) { var lc = lineCol(); if (way > 0) Backend.foldAt(index, lc[0]); else if (way < 0) Backend.unfoldAt(index, lc[0]); else Backend.toggleFold(index, lc[0]) }
                Timer { id: foldTick; interval: 350; onTriggered: { v.foldable = Backend.options.folding ? Backend.foldRanges(v.index) : []; if (v.hid.length) Backend.checkFolds(v.index) } }
                Connections { target: Backend
                    function onFolded(i) { if (i === v.index) v.refold() }
                    function onHinted(i, rows) { if (i === v.index) v.hints = rows }
                    function onPeeked(i, what) { if (i === v.index && v.visible) v.peekAt = what } }
                // ---- inlay hints (from the language's helper), gathered at the end of their lines
                property var hints: []
                property var peekAt: null                    // {path, name, line, first, text}: a definition shown here
                Timer { id: hintTick; interval: 500; onTriggered: if (Backend.options.inlay && v.visible) Backend.inlayHints(v.index, v.topLine, v.lineAt(v.row(v.topLine) + Math.ceil(scroll.height / Math.max(1, edit.cursorRectangle.height)) + 2)) }
                readonly property var info: (index >= 0 && index < Backend.tabs.length && Backend.tabs[index]) || ({})
                // ---- a notebook (.ipynb) is shown as cells over its text; "As JSON" shows the text itself
                property bool rawNb: false
                readonly property bool nbOn: !!info.notebook && !rawNb
                onNbOnChanged: if (!nbOn && info.notebook) { Backend.nbFlush(index); reload() }      // (the text was changed through the cells: take it again)
                Loader { id: nbLoader; active: v.nbOn; anchors.fill: parent; z: 30
                    sourceComponent: NotebookView { tab: v.index; host: win; readOnly: !!v.info.readOnly; onWantsRaw: v.rawNb = true } }
                Seg { visible: !!v.info.notebook && v.rawNb; z: 31; anchors { right: parent.right; rightMargin: 120; top: parent.top; topMargin: 8 } text: "As a Notebook"; on: true; onClicked: v.rawNb = false }
                function reload() { loading = true; var at = edit.cursorPosition; known = Backend.textOf(index); edit.text = known; edit.cursorPosition = Math.min(at, edit.length); loading = false; hid = []; foldTick.restart(); hintTick.restart(); restyle(); refresh() }
                function restyle() { Backend.style(index, { doc: edit.textDocument, colours: win.colours() }) }
                readonly property string look: (win.themed ? win.vsTheme.name : "") + (win.codeDark ? "/dark" : "/light")       // another theme, or light to dark: colour the text again
                onLookChanged: if (!loading) restyle()
                function refresh() { marks = Backend.marksOf(index); probs = Backend.problemsOf(index); bps = Backend.breakpointsOf(index); lineStarts() }
                function lineStarts() { var s = [0], t = edit.text; for (var k = t.indexOf("\n"); k >= 0; k = t.indexOf("\n", k + 1)) s.push(k + 1); starts = s }
                function posOf(line, col) { return Math.min(edit.length, (starts[Math.min(line, starts.length - 1)] || 0) + col) }
                function focusEditor() { edit.forceActiveFocus() }
                function allText() { return edit.text }
                function cursor() { return edit.cursorPosition }
                function lines() { return edit.lineCount }
                function selected() { return edit.selectedText }
                function selRange() { return [edit.selectionStart, edit.selectionEnd] }
                function selectRange(a, b) { edit.select(a, b); scroll.follow(edit.positionToRectangle(a)) }
                function replaceRange(a, b, text) { edit.remove(a, b); edit.insert(a, text) }
                function lineCol() { var before = edit.getText(0, edit.cursorPosition); var nl = before.lastIndexOf("\n"); return [before.split("\n").length - 1, edit.cursorPosition - nl - 1] }
                function cursorTo(p) { edit.cursorPosition = p; edit.forceActiveFocus(); scroll.follow(edit.positionToRectangle(p)) }
                function goTo(line, col) { if (hid.length && isHidden(line)) Backend.unfoldAt(index, line); lineStarts(); var p = posOf(line, col); edit.cursorPosition = p; edit.forceActiveFocus(); scroll.centreOn(edit.positionToRectangle(p)) }
                function suggest() { var lc = lineCol(); Backend.complete(index, lc[0], lc[1]) }
                function definition() { var lc = lineCol(); Backend.definition(index, lc[0], lc[1]) }
                function peek() { var lc = lineCol(); Backend.peek(index, lc[0], lc[1]) }
                function emmet() { var t = edit.text, at = edit.cursorPosition, em = Backend.emmetAt(index, t.substring(t.lastIndexOf("\n", at - 1) + 1, at))
                    if (em.body) startSnippet(at - em.back, at, em.body); else toast.say("There's no Emmet abbreviation before the cursor (it works in HTML and CSS).", true) }
                function hover() { var lc = lineCol(); Backend.hover(index, lc[0], lc[1]) }
                function wordBefore() { var t = edit.getText(Math.max(0, edit.cursorPosition - 80), edit.cursorPosition); var m = /[A-Za-z_][A-Za-z0-9_]*$/.exec(t); return m ? m[0] : "" }
                function offer(items) { win.compAll = items; filterOffer() }
                // How well a suggestion matches what's typed: the same letters at its start, then in any case, then
                // its capitals or the parts of its name (gV, get_v: getValue, get_value), then the letters in order.
                function matchScore(label, p) {
                    if (!p) return 1
                    if (label.indexOf(p) === 0) return 4
                    var l = label.toLowerCase(), q = p.toLowerCase()
                    if (l.indexOf(q) === 0) return 3
                    if (l[0] !== q[0]) return 0
                    var heads = label.replace(/([a-z0-9])([A-Z])/g, "$1 $2").split(/[\s_]+/).map(function (w) { return w[0] ? w[0].toLowerCase() : "" }).join("")
                    if (heads.indexOf(q) === 0) return 2
                    var at = 0
                    for (var n = 0; n < q.length; n++) { at = l.indexOf(q[n], at); if (at < 0) return 0; at++ }
                    return 1
                }
                function filterOffer() {
                    var p = wordBefore(), scored = []
                    for (var k = 0; k < win.compAll.length; k++) {
                        var it = win.compAll[k], m = matchScore(it.label, p)
                        if (m <= 0) continue
                        // likeliest first: how well it matches, then picked lately, used near here and often in this file,
                        // the language server's own order, and shorter before longer when all else is even
                        var s = m * 10 + (it.recent || 0) * 6 + (it.near !== undefined && it.near < 1e6 ? 3 / (1 + it.near / 25) : 0)
                                + Math.min(3, Math.log(1 + (it.freq || 0))) - (it.rank || 0) * 0.01 - it.label.length * 0.02 + (it.snippet ? 0.5 : 0)
                        scored.push([s, k, it])
                    }
                    scored.sort(function (a, b) { return b[0] - a[0] || a[1] - b[1] })
                    var out = scored.slice(0, 50).map(function (x) { return x[2] })
                    if (out.length === 1 && out[0].label === p) out = []
                    win.compPrefix = p; win.comp = out; win.compAt = 0
                }
                function accept(item) {
                    var p = win.compPrefix, at = edit.cursorPosition
                    Backend.picked(item.label)
                    win.comp = []; win.compAll = []
                    if (item.snippet) { startSnippet(at - p.length, at, item.snippet); return }
                    edit.remove(at - p.length, at); edit.insert(at - p.length, item.insert)
                }
                // ---- snippets: places to type, Tab to the next
                property var snip: null                    // {stops: [[a, b]…], same: [[[a, b]…]…], k, len}
                function startSnippet(from, to, body) {
                    var t = edit.text, ls = t.lastIndexOf("\n", from - 1) + 1, ind = /^[ \t]*/.exec(t.substring(ls, from))[0]
                    var x = Backend.expandSnippet(index, body, ind)
                    v.multiBusy = true
                    edit.remove(from, to); edit.insert(from, x.text)
                    v.multiBusy = false
                    var stops = x.stops.map(function (r) { return [r[0] + from, r[1] + from] })
                    var same = x.same.map(function (l) { return l.map(function (r) { return [r[0] + from, r[1] + from] }) })
                    snip = stops.length > 1 ? { stops: stops, same: same, k: 0, len: edit.length } : null
                    edit.select(stops[0][0], stops[0][1])
                }
                function checkSnip() { if (!snip) return; var r = snip.stops[snip.k]; if (edit.cursorPosition < r[0] || edit.cursorPosition > r[1]) snip = null }
                function snipShift(delta) {                // the text changed by delta at the current stop
                    if (!snip) return
                    var cur = snip.stops[snip.k], at = cur[0], out = { stops: [], same: [], k: snip.k, len: edit.length }
                    function mv(r) { return r[0] > at || (r[0] === at && r !== cur && r[1] > cur[1]) ? [r[0] + delta, r[1] + delta] : r }
                    for (var n = 0; n < snip.stops.length; n++) {
                        var r = snip.stops[n]
                        out.stops.push(n === snip.k ? [r[0], Math.max(r[0], r[1] + delta)] : (r[0] > at ? [r[0] + delta, r[1] + delta] : r))
                        out.same.push(snip.same[n].map(function (q) { return q[0] > at ? [q[0] + delta, q[1] + delta] : q }))
                    }
                    snip = out
                }
                function nextStop() {
                    var cur = snip.stops[snip.k], typed = edit.getText(cur[0], cur[1]), mirrors = snip.same[snip.k]
                    if (mirrors.length) {                  // the same name again: write what was typed there too
                        var edits = mirrors.map(function (r) { return [r[0], r[1], typed] }), was = snip
                        v.multiBusy = true; Backend.multiEdit(index, edits, false); v.multiBusy = false
                        var out = { stops: [], same: [], k: was.k, len: edit.length }
                        function moved(r) { var d = 0; for (var e = 0; e < mirrors.length; e++) if (mirrors[e][0] < r[0]) d += typed.length - (mirrors[e][1] - mirrors[e][0]); return [r[0] + d, r[1] + d] }
                        for (var n = 0; n < was.stops.length; n++) { out.stops.push(moved(was.stops[n])); out.same.push(n === was.k ? [] : was.same[n].map(moved)) }
                        snip = out
                    }
                    snip.k++
                    var r = snip.stops[snip.k]
                    if (snip.k >= snip.stops.length - 1) { snip = null; if (r[1] > r[0]) edit.select(r[0], r[1]); else edit.cursorPosition = r[0]; return }
                    snip = { stops: snip.stops, same: snip.same, k: snip.k, len: edit.length }
                    edit.select(r[0], r[1])
                }
                // ---- more than one cursor
                property var extra: []                     // [{a, p}]: where each extra selection starts, and its caret
                property bool multiBusy: false
                function anchorOf() { return edit.cursorPosition === edit.selectionStart ? edit.selectionEnd : edit.selectionStart }
                function allCursors() { return [{ a: anchorOf(), p: edit.cursorPosition, main: true }].concat(extra.map(function (c) { return { a: c.a, p: c.p, main: false } })) }
                function wordBounds(at) { var t = edit.text, s = at, e = at; while (s > 0 && /\w/.test(t.charAt(s - 1))) s--; while (e < t.length && /\w/.test(t.charAt(e))) e++; return [s, e] }
                function taken(a, b) { return allCursors().some(function (c) { return Math.min(c.a, c.p) === a && Math.max(c.a, c.p) === b }) }
                function addNext() {
                    if (edit.selectionStart === edit.selectionEnd && !extra.length) { var w = wordBounds(edit.cursorPosition); if (w[1] > w[0]) edit.select(w[0], w[1]); return }
                    var word = edit.getText(edit.selectionStart, edit.selectionEnd); if (!word) return
                    var last = extra.length ? extra[extra.length - 1] : { a: edit.selectionStart, p: edit.selectionEnd }, t = edit.text
                    var from = Math.max(last.a, last.p), k = t.indexOf(word, from)
                    if (k < 0) k = t.indexOf(word)
                    while (k >= 0 && taken(k, k + word.length)) { k = t.indexOf(word, k + 1); if (k < 0) break }
                    if (k < 0) { toast.say("No more of “" + word + "”", false); return }
                    extra = extra.concat([{ a: k, p: k + word.length }]); scroll.follow(edit.positionToRectangle(k))
                }
                function selectEvery() {
                    if (edit.selectionStart === edit.selectionEnd) { var w = wordBounds(edit.cursorPosition); if (w[1] <= w[0]) return; edit.select(w[0], w[1]) }
                    var word = edit.getText(edit.selectionStart, edit.selectionEnd), t = edit.text, out = []
                    for (var k = t.indexOf(word); k >= 0; k = t.indexOf(word, k + word.length)) if (k !== edit.selectionStart) out.push({ a: k, p: k + word.length })
                    extra = out
                    toast.say((out.length + 1) + " cursors", false)
                }
                function addVertical(dir) {
                    lineStarts()
                    var cs = allCursors(), ref = cs.reduce(function (b, c) { return dir > 0 ? (c.p > b.p ? c : b) : (c.p < b.p ? c : b) })
                    var line = 0; while (line + 1 < starts.length && starts[line + 1] <= ref.p) line++
                    var col = ref.p - starts[line], to = line + dir
                    if (to < 0 || to >= starts.length) return
                    var end = to + 1 < starts.length ? starts[to + 1] - 1 : edit.length, p = Math.min(starts[to] + col, end)
                    extra = extra.concat([{ a: p, p: p }])
                }
                property bool typing: false                // the last multi-cursor change was letters: the next joins its undo step
                function typeAll(fn, letters) {   // fn(cursor) -> [from, to, text, caret offset from `from` after]
                    var cs = allCursors().slice().sort(function (x, y) { return Math.min(x.a, x.p) - Math.min(y.a, y.p) }), edits = [], shift = 0, next = [], main = 0
                    for (var n = 0; n < cs.length; n++) {
                        var r = fn(cs[n]); if (!r) { next.push({ a: cs[n].p + shift, p: cs[n].p + shift, main: cs[n].main }); continue }
                        edits.push([r[0], r[1], r[2]])
                        var at = r[0] + shift + r[3]
                        next.push({ a: at, p: at, main: cs[n].main })
                        shift += r[2].length - (r[1] - r[0])
                    }
                    multiBusy = true
                    if (edits.length) Backend.multiEdit(index, edits, !!letters && typing)
                    typing = !!letters
                    var others = []
                    for (var m = 0; m < next.length; m++) if (next[m].main) main = next[m].p; else others.push({ a: next[m].a, p: next[m].p })
                    edit.cursorPosition = main
                    extra = others
                    multiBusy = false
                }
                function moveAll(fn, keep) {   // fn(position) -> new position; keep: extend the selections
                    var cs = allCursors(), others = []
                    typing = false
                    for (var n = 0; n < cs.length; n++) {
                        var to = fn(cs[n].p, cs[n])
                        if (cs[n].main) { multiBusy = true; if (keep) edit.select(cs[n].a, to); else edit.cursorPosition = to; if (keep && to < cs[n].a) edit.select(cs[n].a, to); multiBusy = false }
                        else others.push({ a: keep ? cs[n].a : to, p: to })
                    }
                    extra = others
                }
                function multiKey(e) {   // a key with more than one cursor: true when dealt with
                    var t = edit.text, shift = (e.modifiers & Qt.ShiftModifier)
                    function sel(c) { return [Math.min(c.a, c.p), Math.max(c.a, c.p)] }
                    function lineOf(p) { return [t.lastIndexOf("\n", p - 1) + 1, (t.indexOf("\n", p) < 0 ? t.length : t.indexOf("\n", p))] }
                    if (e.key === Qt.Key_Escape) { extra = []; return true }
                    if (e.key === Qt.Key_Backspace) { typeAll(function (c) { var r = sel(c); if (r[1] > r[0]) return [r[0], r[1], "", 0]; return c.p > 0 ? [c.p - 1, c.p, "", 0] : null }); return true }
                    if (e.key === Qt.Key_Delete) { typeAll(function (c) { var r = sel(c); if (r[1] > r[0]) return [r[0], r[1], "", 0]; return c.p < t.length ? [c.p, c.p + 1, "", 0] : null }); return true }
                    if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { typeAll(function (c) { var r = sel(c), ind = /^[ \t]*/.exec(t.substring(lineOf(r[0])[0], r[0]))[0]; return [r[0], r[1], "\n" + ind, 1 + ind.length] }); return true }
                    if (e.key === Qt.Key_Tab) { typeAll(function (c) { var r = sel(c); return [r[0], r[1], win.unit, win.unit.length] }); return true }
                    if (e.key === Qt.Key_Left) { moveAll(function (p, c) { var r = sel(c); return !shift && r[1] > r[0] ? r[0] : Math.max(0, p - 1) }, shift); return true }
                    if (e.key === Qt.Key_Right) { moveAll(function (p, c) { var r = sel(c); return !shift && r[1] > r[0] ? r[1] : Math.min(t.length, p + 1) }, shift); return true }
                    if (e.key === Qt.Key_Home) { moveAll(function (p) { var l = lineOf(p), ind = /^[ \t]*/.exec(t.substring(l[0], l[1]))[0].length; return p === l[0] + ind ? l[0] : l[0] + ind }, shift); return true }
                    if (e.key === Qt.Key_End) { moveAll(function (p) { return lineOf(p)[1] }, shift); return true }
                    if (e.key === Qt.Key_Up || e.key === Qt.Key_Down || e.key === Qt.Key_PageUp || e.key === Qt.Key_PageDown) { extra = []; return false }
                    if (e.text.length === 1 && !(e.modifiers & Qt.ControlModifier) && e.text >= " ") {
                        var ch = e.text; typeAll(function (c) { var r = sel(c); return [r[0], r[1], ch, ch.length] }, /\w/.test(ch)); return true }
                    return false
                }
                // ---- what the call wants; what can be fixed
                function fixHere() { var lc = lineCol(); win.fixMenu = null; Backend.quickFixes(index, lc[0], lc[1]) }
                function askSignature() { var lc = lineCol(); Backend.signatureAt(index, lc[0], lc[1]) }
                // the bracket by the cursor and the one that closes (or opens) it
                property var pair: []
                function findPair() {
                    var t = edit.text, at = edit.cursorPosition, opens = "([{", shuts = ")]}", k = -1
                    if (at > 0 && (opens + shuts).indexOf(t[at - 1]) >= 0) k = at - 1
                    else if (at < t.length && (opens + shuts).indexOf(t[at]) >= 0) k = at
                    if (k < 0 || edit.selectedText !== "") { if (pair.length) pair = []; return }
                    var c = t[k], o = opens.indexOf(c), fwd = o >= 0, mine = fwd ? c : opens[shuts.indexOf(c)], other = fwd ? shuts[o] : shuts[opens.indexOf(mine)], depth = 0
                    for (var j = k + (fwd ? 1 : -1), n = 0; j >= 0 && j < t.length && n < 20000; j += fwd ? 1 : -1, n++) {
                        if (t[j] === c) depth++
                        else if (t[j] === (fwd ? other : mine)) { if (depth === 0) { pair = [k, j]; return } depth-- }
                    }
                    pair = [k]                                       // (nothing closes it: just the one, in red)
                }
                Timer { id: pairTick; interval: 40; onTriggered: { v.findPair(); if (v.visible) win.crumbs = Backend.crumbsAt(v.index, win.curLine - 1) } }
                // is the cursor inside a call's brackets? (a rough look back, enough to know when the signature tip should go)
                function inCall() {
                    var t = edit.text, depth = 0
                    for (var k = edit.cursorPosition - 1, stop = Math.max(0, k - 3000); k >= stop; k--) {
                        var c = t[k]
                        if (c === ")" || c === "]" || c === "}") depth++
                        else if (c === "(" || c === "[" || c === "{") { if (depth === 0) return c === "("; depth-- }
                    }
                    return false
                }
                // ---- merge conflicts
                property var conflicts: []
                Timer { id: conflictTick; interval: 300; onTriggered: v.conflicts = Backend.conflictsOf(v.index) }
                // ---- sticky scroll: the lines that open the scopes at the top of the view
                property var sticky: []
                readonly property int topLine: lineAt(Math.max(0, Math.floor((scroll.contentY - edit.y + 2) / Math.max(1, edit.cursorRectangle.height))))
                onContentYChanged: { stickyTick.restart(); decoTick.restart(); hintTick.restart() }
                readonly property real contentY: scroll.contentY
                onTopLineChanged: stickyTick.restart()
                Timer { id: stickyTick; interval: 60
                    onTriggered: {
                        v.sticky = v.topLine > 0 && !Backend.wrap && Backend.options.sticky ? Backend.stickyAt(v.index, v.topLine) : [] } }
                function lineRange() {   // the first and last line of the selection (or the cursor's line)
                    var a = edit.selectionStart, b = edit.selectionEnd, t = edit.text
                    var s = t.lastIndexOf("\n", a - 1) + 1
                    var e = t.indexOf("\n", b > a && t.charAt(b - 1) === "\n" ? b - 1 : b); if (e < 0) e = t.length
                    return [s, e]
                }
                function rewriteLines(fn) {
                    var r = lineRange(), old = edit.getText(r[0], r[1]), parts = old.split("\n"), now = fn(parts).join("\n")
                    if (now === old) return
                    edit.remove(r[0], r[1]); edit.insert(r[0], now); edit.select(r[0], r[0] + now.length)
                }
                function indent(out) {
                    rewriteLines(function (ls) { return ls.map(function (l) {
                        if (!out) return l.length ? win.unit + l : l
                        if (l.indexOf(win.unit) === 0) return l.substring(win.unit.length)
                        return l.replace(/^(\t| {1,4})/, "") }) })
                }
                // whole lines at a time (worked out by the backend, made here so Undo takes them back)
                function lineCmd(how) {
                    var r = Backend.lineEdit(v.index, edit.selectionStart, edit.selectionEnd, how)
                    if (r.at === undefined) return
                    if (r.end > r.at) edit.remove(r.at, r.end)
                    if (r.text !== "") edit.insert(r.at, r.text)
                    if (r.a === r.b) edit.cursorPosition = r.a; else edit.select(r.a, r.b)
                }
                function goChange(way) {
                    var n = Backend.changeNear(v.index, v.lineCol()[0], way)
                    if (n < 0) toast.say("Nothing in this file has changed since the last commit.", false); else v.goTo(n, 0)
                }
                function putBack() {
                    var r = Backend.putBack(v.index, v.lineCol()[0])
                    if (r.at === undefined) { toast.say("This line is as it was at the last commit.", false); return }
                    if (r.end > r.at) edit.remove(r.at, r.end)
                    if (r.text !== "") edit.insert(r.at, r.text)
                    v.goTo(r.line, 0)
                }
                function toggleComment() {
                    var c = Backend.status.comment
                    if (!c) { var b = Backend.status.block; if (b && b.length === 2 && edit.selectedText) { var a = edit.selectionStart, t = edit.selectedText; edit.remove(a, edit.selectionEnd); edit.insert(a, b[0] + " " + t + " " + b[1]) } return }
                    rewriteLines(function (ls) {
                        var filled = ls.filter(function (l) { return l.trim().length > 0 })
                        var all = filled.length > 0 && filled.every(function (l) { return l.trim().indexOf(c) === 0 })
                        var ind = Math.min.apply(null, filled.map(function (l) { return /^[ \t]*/.exec(l)[0].length }).concat([9999]))
                        return ls.map(function (l) {
                            if (!l.trim().length) return l
                            if (all) return l.replace(new RegExp("^([ \\t]*)" + c.replace(/[.*+?^${}()|[\]\\\/]/g, "\\$&") + " ?"), "$1")
                            return l.substring(0, ind) + c + " " + l.substring(ind) }) })
                }
                Component.onCompleted: { reload(); conflictTick.start()
                    var at = Backend.placeOf(index)                   // back to where the cursor was the last time this file was open
                    if (at > 0 && at <= edit.length) { edit.cursorPosition = at; Qt.callLater(function () { scroll.centreOn(edit.cursorRectangle) }) }
                    decoTick.restart() }
                // ---- the word under the cursor wherever else it is in view, and a faint line down each level of indentation
                property var occ: ({ len: 0, at: [] })
                property var guides: []
                Timer { id: placeTick; interval: 900; onTriggered: Backend.setPlace(v.index, edit.cursorPosition) }
                Timer { id: decoTick; interval: 90; onTriggered: v.decorate() }
                onVisibleChanged: if (visible) decoTick.restart()
                onHeightChanged: decoTick.restart()
                Connections { target: Backend; function onChanged() { if (v.visible && (!Backend.options.guides && v.guides.length || !Backend.options.occurrences && v.occ.at.length || Backend.options.guides && !v.guides.length)) decoTick.restart() } }
                function decorate() {
                    if (!visible || info.binary) return
                    var lh = Math.max(1, edit.cursorRectangle.height), top = Math.max(0, scroll.contentY - edit.y)
                    var a = edit.positionAt(0, top), b = edit.positionAt(100000, top + scroll.height + lh)
                    if (b - a > 60000) b = a + 60000                   // (a screenful of very long lines: enough is enough)
                    var t = edit.getText(a, b), found = [], word = ""
                    if (Backend.options.occurrences && !extra.length) {
                        var sel = edit.selectedText
                        if (sel.length) { if (/^\w{2,64}$/.test(sel)) word = sel }
                        else { var c = edit.cursorPosition, near = edit.getText(Math.max(0, c - 64), Math.min(edit.length, c + 64)), k = Math.min(64, c)
                            var l = /\w*$/.exec(near.slice(0, k))[0], r = /^\w*/.exec(near.slice(k))[0]
                            if (l.length + r.length >= 2 && l.length + r.length <= 64) word = l + r }
                        if (word && !/^\d+$/.test(word)) { var re = new RegExp("\\b" + word + "\\b", "g"), m
                            while ((m = re.exec(t)) !== null && found.length < 300) found.push(a + m.index) }
                        if (found.length < 2) found = [] }
                    occ = { len: word.length, at: found }
                    var out = []
                    if (Backend.options.guides && !Backend.wrap) {
                        var lines = t.split("\n"), first = Math.round(edit.positionToRectangle(a).y / lh), tw = win.tabW
                        var unit = win.unit === "\t" ? tw : Math.max(1, win.unit.length), ind = [], i, j
                        for (i = 0; i < lines.length; i++) { var s = lines[i], col = 0, blank = true
                            for (j = 0; j < s.length; j++) { var ch = s.charAt(j); if (ch === " ") col++; else if (ch === "\t") col += tw - col % tw; else { blank = false; break } }
                            ind.push(blank ? -1 : col) }
                        for (i = 0; i < ind.length; i++) if (ind[i] < 0) {      // an empty line carries on the lines either side of it
                            var p = i - 1, n = i + 1; while (n < ind.length && ind[n] < 0) n++
                            var before = p >= 0 ? ind[p] : 0, after = n < ind.length ? ind[n] : 0, both = Math.min(before, after)
                            for (j = i; j < n; j++) ind[j] = both; i = n - 1 }
                        var open = {}
                        for (i = 0; i <= ind.length; i++) { var depth = i < ind.length ? Math.ceil(ind[i] / unit) : 0
                            for (var key in open) if (Number(key) >= depth) { out.push({ col: Number(key) * unit, from: first + open[key], to: first + i - 1 }); delete open[key] }
                            for (j = 0; j < depth && j < 24; j++) if (open[j] === undefined) open[j] = i } }
                    guides = out }
                Connections { target: Backend; function onChanged() { if (!v.loading) { v.marks = Backend.marksOf(v.index); v.probs = Backend.problemsOf(v.index); v.bps = Backend.breakpointsOf(v.index) } } }
                Connections { target: win.dbg; function onChanged() { v.bps = Backend.breakpointsOf(v.index) } }

                Text { visible: !!v.info.binary; anchors.centerIn: parent; width: 360; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; color: Theme.t.text_secondary; text: v.info.why || "" }
                // the minimap: the whole file small, with the part on screen marked; click or drag to go there
                Item { id: mm; visible: Backend.minimap && !v.info.binary && edit.lineCount > 40 && v.width > 520
                    anchors { right: parent.right; top: parent.top; bottom: parent.bottom; rightMargin: 8; topMargin: 10; bottomMargin: 10 } width: 92
                    property int ver: 0
                    Timer { id: mmTick; interval: 700; onTriggered: mm.ver++ }
                    readonly property real full: edit.lineCount * 2
                    readonly property real k: Math.min(1, height / Math.max(1, full))
                    Image { id: mmImg; width: parent.width; height: mm.full * mm.k; fillMode: Image.Stretch; smooth: true; cache: false; asynchronous: true
                        source: mm.visible ? "image://minimap/" + v.index + "/" + mm.ver + "_" + edit.lineCount : "" }
                    Rectangle { width: parent.width; radius: 3; color: Qt.alpha(Theme.t.accent, 0.14); border.width: 1; border.color: Qt.alpha(Theme.t.accent, 0.4)
                        y: scroll.contentHeight > 0 ? scroll.contentY / scroll.contentHeight * mmImg.height : 0
                        height: Math.max(12, scroll.contentHeight > 0 ? Math.min(1, scroll.height / scroll.contentHeight) * mmImg.height : 0) }
                    MouseArea { width: parent.width; height: mmImg.height; cursorShape: Qt.PointingHandCursor
                        function go(y) { scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, y / Math.max(1, mmImg.height) * scroll.contentHeight - scroll.height / 2)) }
                        onPressed: function (m) { go(m.y) } onPositionChanged: function (m) { go(m.y) } } }
                Flickable { id: scroll; visible: !v.info.binary; anchors { fill: parent; margins: 2; bottomMargin: findBar.visible && v.visible ? 0 : 2; rightMargin: win.mdPreview && v.info.lang === "Markdown" ? v.width / 2 + 4 : mm.visible ? 104 : 2 } clip: true; boundsBehavior: Flickable.StopAtBounds
                    contentWidth: Backend.wrap ? width : Math.max(width, edit.x + edit.contentWidth + 60); contentHeight: edit.height + height * 0.5
                    function follow(r) {
                        if (r.y + edit.y - 10 < contentY) contentY = Math.max(0, r.y + edit.y - 10); else if (r.y + edit.y + r.height + 40 > contentY + height) contentY = r.y + edit.y + r.height + 40 - height
                        if (Backend.wrap) return
                        var x = edit.x + r.x; if (x - 60 < contentX) contentX = Math.max(0, x - 60); else if (x + 40 > contentX + width) contentX = x + 40 - width }
                    function centreOn(r) { contentY = Math.max(0, Math.min(contentHeight - height, r.y + edit.y - height / 3)); follow(r) }
                    // blame: who changed each line (Ctrl+Alt+B); click one to see that commit
                    Rectangle { id: blameCol; objectName: "blameCol"; visible: win.blameOn && v.blameRows.length > 0 && !Backend.wrap; z: 4; x: scroll.contentX + scroll.width - width - 6; y: edit.y; width: 230
                        height: edit.height; color: Theme.t.dark ? "#E6111317" : "#EEF6F7F9"; radius: 6
                        Text { anchors.fill: parent; anchors.leftMargin: 8; font.family: win.mono; font.pixelSize: Math.max(9, Backend.size - 2); color: Theme.t.text_secondary; elide: Text.ElideRight
                            lineHeight: edit.cursorRectangle.height > 0 ? edit.cursorRectangle.height : 1.0; lineHeightMode: Text.FixedHeight; textFormat: Text.PlainText
                            text: v.blameRows.filter(function (b, k) { return !v.hid.length || !v.isHidden(k) }).map(function (b) { return b.first ? (b.author.split(" ")[0] + ", " + b.when).substring(0, 30) : "" }).join("\n") }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                            onClicked: function (m) { var k = v.lineAt(Math.floor(m.y / Math.max(1, edit.cursorRectangle.height))), b = v.blameRows[k]; if (b && b.sha) win.showCommit(b.sha, b.summary) } } }
                    Text { visible: win.blameOn && !Backend.wrap && v.blameRows.length > 0 && v.blameNow !== null; z: 3; x: edit.x + edit.contentWidth + 40; y: edit.y + edit.cursorRectangle.y
                        height: edit.cursorRectangle.height; verticalAlignment: Text.AlignVCenter; font.family: win.mono; font.pixelSize: Math.max(9, Backend.size - 2); color: win.gutterInk; opacity: 0.8
                        text: v.blameNow ? v.blameNow.author + ", " + v.blameNow.when + (v.blameNow.summary ? " · " + v.blameNow.summary : "") : "" }
                    // the line the cursor is on
                    Rectangle { x: 0; y: edit.y + edit.cursorRectangle.y - 1; width: scroll.contentWidth; height: edit.cursorRectangle.height + 2; color: win.lineGlow; visible: edit.activeFocus || true }
                    // merge conflicts: ours green, theirs blue, with what to keep above each
                    Repeater { model: Backend.wrap ? [] : v.conflicts
                        Item { required property var modelData; required property int index
                            readonly property real lh: edit.cursorRectangle.height
                            Rectangle { x: 0; y: edit.y + v.row(modelData.start) * parent.lh; width: scroll.contentWidth; height: parent.lh; color: Qt.rgba(0.25, 0.73, 0.31, 0.32) }
                            Rectangle { x: 0; y: edit.y + (v.row(modelData.start) + 1) * parent.lh; width: scroll.contentWidth; height: (v.row(modelData.base > 0 ? modelData.base : modelData.mid) - v.row(modelData.start) - 1) * parent.lh; color: Qt.rgba(0.25, 0.73, 0.31, 0.13) }
                            Rectangle { x: 0; y: edit.y + v.row(modelData.mid) * parent.lh; width: scroll.contentWidth; height: parent.lh; color: Qt.rgba(0.5, 0.5, 0.5, 0.2) }
                            Rectangle { x: 0; y: edit.y + (v.row(modelData.mid) + 1) * parent.lh; width: scroll.contentWidth; height: (v.row(modelData.end) - v.row(modelData.mid) - 1) * parent.lh; color: Qt.rgba(0.3, 0.55, 1, 0.13) }
                            Rectangle { x: 0; y: edit.y + v.row(modelData.end) * parent.lh; width: scroll.contentWidth; height: parent.lh; color: Qt.rgba(0.3, 0.55, 1, 0.32) } } }
                    Repeater { model: Backend.wrap ? [] : v.conflicts      // …and what to keep, over the text so it can be clicked
                        Row { required property var modelData; required property int index; objectName: "conflictBar"; z: 8
                            readonly property int which: index
                            x: scroll.contentX + edit.x + 260; y: edit.y + v.row(modelData.start) * edit.cursorRectangle.height; height: edit.cursorRectangle.height; spacing: 10
                            Repeater { model: [["ours", "Keep ours (" + parent.modelData.oursName + ")"], ["theirs", "Keep theirs (" + parent.modelData.theirsName + ")"], ["both", "Keep both"]]
                                Text { required property var modelData; anchors.verticalCenter: parent.verticalCenter; text: modelData[1]; font.pixelSize: Math.max(10, Backend.size - 3); color: Theme.t.accent; font.underline: ma.containsMouse
                                    MouseArea { id: ma; anchors.fill: parent; anchors.margins: -3; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                        onClicked: Backend.resolveConflict(v.index, parent.parent.which, parent.modelData[0]) } } } } }

                    // a faint line down each level of indentation
                    Repeater { model: v.guides
                        Rectangle { required property var modelData; visible: !v.hid.length || !v.isHidden(modelData.from); x: edit.x + modelData.col * widest.advanceWidth; y: edit.y + v.row(modelData.from) * edit.cursorRectangle.height
                            width: 1; height: (v.row(modelData.to) - v.row(modelData.from) + 1) * edit.cursorRectangle.height; color: Qt.alpha(win.codeInk, 0.09) } }
                    // the word under the cursor, wherever else it is in view
                    Repeater { model: v.occ.at
                        Rectangle { required property var modelData; readonly property rect r: edit.positionToRectangle(modelData)
                            x: edit.x + r.x - 1; y: edit.y + r.y; width: v.occ.len * widest.advanceWidth + 2; height: r.height; radius: 3; color: Qt.alpha(Theme.t.text, 0.10) } }
                    // the matching bracket pair
                    Repeater { model: v.index === Backend.current && edit.activeFocus ? v.pair : []
                        Rectangle { required property var modelData; readonly property rect r: edit.positionToRectangle(modelData); readonly property rect r2: edit.positionToRectangle(modelData + 1)
                            x: edit.x + r.x - 1; y: edit.y + r.y; width: Math.max(6, r2.y === r.y ? r2.x - r.x + 2 : widest.advanceWidth + 2); height: r.height; radius: 3
                            color: v.pair.length === 1 ? Qt.alpha(win.delInk, 0.22) : Qt.alpha(Theme.t.accent, 0.14); border.width: 1
                            border.color: v.pair.length === 1 ? win.delInk : Qt.alpha(Theme.t.accent, 0.7) } }
                    // the other cursors and what they've selected
                    Repeater { model: v.extra
                        Item { required property var modelData
                            readonly property rect ra: edit.positionToRectangle(Math.min(modelData.a, modelData.p))
                            readonly property rect rb: edit.positionToRectangle(Math.max(modelData.a, modelData.p))
                            readonly property rect rc: edit.positionToRectangle(modelData.p)
                            Rectangle { visible: parent.ra.y === parent.rb.y && parent.rb.x > parent.ra.x; x: edit.x + parent.ra.x; y: edit.y + parent.ra.y; width: parent.rb.x - parent.ra.x; height: parent.ra.height
                                color: Qt.alpha(Theme.t.accent, 0.35) }
                            Rectangle { x: edit.x + parent.rc.x; y: edit.y + parent.rc.y; width: 2; height: parent.rc.height; color: Theme.t.text } } }
                    // a snippet's places still to fill
                    Repeater { model: v.snip ? v.snip.stops.slice(v.snip.k + 1, v.snip.stops.length - 1) : []
                        Rectangle { required property var modelData; readonly property rect ra: edit.positionToRectangle(modelData[0]); readonly property rect rb: edit.positionToRectangle(modelData[1])
                            x: edit.x + ra.x - 1; y: edit.y + ra.y; width: Math.max(4, rb.x - ra.x + 2); height: ra.height; radius: 3; color: "transparent"; border.width: 1
                            border.color: Qt.alpha(Theme.t.accent, 0.6) } }
                    // a light when the cursor's line has a problem: click it (or Ctrl+.) for fixes
                    Text { objectName: "fixBulb"; visible: !Backend.wrap && v.probs.some(function (p) { return p.line <= win.curLine - 1 && win.curLine - 1 <= p.endLine }) && v.index === Backend.current
                        z: 6; x: 1; y: edit.y + edit.cursorRectangle.y; height: edit.cursorRectangle.height; verticalAlignment: Text.AlignVCenter; text: "💡"; font.pixelSize: Math.max(10, Backend.size - 3)
                        MouseArea { anchors.fill: parent; anchors.margins: -3; cursorShape: Qt.PointingHandCursor; onClicked: v.fixHere() } }
                    // line numbers
                    Text { id: gutter; x: 0; y: edit.y; width: gutterW; horizontalAlignment: Text.AlignRight; rightPadding: 14; color: win.gutterInk; renderType: Text.NativeRendering
                        readonly property int gutterW: (win.zen && Backend.options.zenNoNumbers ? 0 : 34 + String(edit.lineCount).length * Math.ceil(Backend.size * 0.62))
                        visible: !Backend.wrap; font.family: win.mono; font.pixelSize: Backend.size; lineHeight: edit.cursorRectangle.height > 0 ? edit.cursorRectangle.height : 1.0; lineHeightMode: Text.FixedHeight
                        text: { if (win.zen && Backend.options.zenNoNumbers) return ""
                                var n = edit.lineCount + v.hidCount, h = v.hid, all = [], at = 0       // (lineCount is the lines laid out: folded ones aren't)
                                for (var k = 0; k < n; k++) { if (at < h.length && k >= h[at][0]) { k = h[at][1]; at++; continue } all.push(k + 1) }
                                return all.join("\n") } }
                    // folding: an arrow beside each line that has something under it (shown near the pointer, and wherever something is folded)
                    Repeater { model: Backend.wrap || !Backend.options.folding ? [] : v.foldable.filter(function (r) { var y = v.row(r[0]); return !v.isHidden(r[0]) && y >= v.row(v.topLine) - 2 && y <= v.row(v.topLine) + scroll.height / Math.max(1, edit.cursorRectangle.height) + 2 })
                        Text { id: foldArrow; required property var modelData; z: 7
                            readonly property bool shut: { for (var k = 0; k < v.hid.length; k++) if (v.hid[k][0] === modelData[0] + 1) return true; return false }
                            x: gutter.width - 13; y: edit.y + v.row(modelData[0]) * edit.cursorRectangle.height; width: 12; height: edit.cursorRectangle.height
                            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; text: shut ? "▸" : "▾"; font.pixelSize: Math.max(9, Backend.size - 3)
                            color: shut ? Theme.t.accent : win.gutterInk; opacity: shut || gutterHover.hovered || foldMouse.containsMouse ? 1 : 0
                            MouseArea { id: foldMouse; anchors.fill: parent; anchors.margins: -2; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Backend.toggleFold(v.index, foldArrow.modelData[0]) } } }
                    Item { x: 0; y: edit.y; width: gutter.width + 8; height: edit.height; HoverHandler { id: gutterHover } }
                    // …and at the end of a folded line, what stands for the lines under it (click to see them again)
                    Repeater { model: Backend.wrap ? [] : v.hid
                        Rectangle { id: foldMark; required property var modelData; z: 7
                            readonly property rect at: { v.starts; return edit.positionToRectangle(Math.max(0, v.posOf(modelData[0], 0) - 1)) }
                            x: edit.x + at.x + 8; y: edit.y + at.y + 2; width: foldText.width + 12; height: edit.cursorRectangle.height - 4; radius: 5; color: Qt.alpha(Theme.t.accent, 0.18)
                            Text { id: foldText; anchors.centerIn: parent; text: "⋯ " + (foldMark.modelData[1] - foldMark.modelData[0] + 1) + (foldMark.modelData[1] === foldMark.modelData[0] ? " line" : " lines"); color: Theme.t.accent; font.pixelSize: Math.max(9, Backend.size - 3) }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Backend.unfoldAt(v.index, foldMark.modelData[0]) } } }
                    // inlay hints, after the end of their lines
                    Repeater { model: Backend.wrap || !Backend.options.inlay ? [] : v.hints
                        Text { required property var modelData; z: 3; visible: !v.hid.length || !v.isHidden(modelData.line)
                            readonly property rect at: { v.starts; return edit.positionToRectangle(Math.max(0, v.posOf(modelData.line + 1, 0) - 1)) }
                            x: edit.x + at.x + 28; y: edit.y + at.y; height: edit.cursorRectangle.height; verticalAlignment: Text.AlignVCenter
                            text: modelData.text; textFormat: Text.PlainText; font.family: win.mono; font.pixelSize: Math.max(9, Backend.size - 2); font.italic: true; color: win.gutterInk } }
                    // rulers (editor.rulers): a faint line down each column named
                    Repeater { model: Backend.wrap ? [] : Backend.options.rulers
                        Rectangle { required property int modelData; z: 1; x: edit.x + modelData * widest.advanceWidth; y: 0; width: 1; height: Math.max(scroll.contentHeight, scroll.height); color: Qt.alpha(win.codeInk, 0.1) } }
                    // breakpoints: click a line number to set or clear one
                    MouseArea { visible: !Backend.wrap; x: 0; y: edit.y; width: gutter.width - 8; height: edit.height; cursorShape: Qt.PointingHandCursor
                        onClicked: function (m) { Backend.toggleBreakpoint(v.index, v.lineAt(Math.floor(m.y / Math.max(1, edit.cursorRectangle.height)))) } }
                    Repeater { model: Backend.wrap ? [] : v.bps
                        Rectangle { required property int modelData; x: 3; visible: !v.hid.length || !v.isHidden(modelData); y: edit.y + v.row(modelData) * edit.cursorRectangle.height + (edit.cursorRectangle.height - 11) / 2
                            width: 11; height: 11; radius: 5.5; color: "#E5484D"; border.width: 1; border.color: "#33000000" } }
                    // where the debugger stopped
                    Rectangle { visible: win.dbg.whereFile === v.path && win.dbg.whereLine >= 0; x: 0; y: edit.y + v.row(win.dbg.whereLine) * edit.cursorRectangle.height - 1
                        width: scroll.contentWidth; height: edit.cursorRectangle.height + 2; color: Qt.rgba(1, 0.78, 0.2, 0.22)
                        Text { x: 1; anchors.verticalCenter: parent.verticalCenter; text: "➜"; color: "#F5B83D"; font.pixelSize: Backend.size; visible: !Backend.wrap } }
                    // Git's marks beside the numbers
                    Repeater { model: Backend.wrap ? [] : Object.keys(v.marks)
                        Rectangle { required property string modelData; readonly property string kind: v.marks[modelData]
                            x: gutter.width - 6; y: edit.y + (v.row(parseInt(modelData)) * edit.cursorRectangle.height) + (kind === "del" ? edit.cursorRectangle.height - 3 : 0)
                            width: 3; height: kind === "del" ? 5 : edit.cursorRectangle.height; radius: 1.5; color: kind === "add" ? win.addInk : kind === "mod" ? win.modInk : win.delInk } }
                    // problems: a dot by the number and a wavy line under the words
                    Repeater { model: v.probs.slice(0, 300)
                        Item { required property var modelData
                            readonly property rect a: edit.positionToRectangle(v.posOf(modelData.line, modelData.col))
                            readonly property rect b: edit.positionToRectangle(v.posOf(modelData.endLine, Math.max(modelData.endCol, modelData.col + 1)))
                            readonly property color ink: modelData.severity === 1 ? win.delInk : modelData.severity === 2 ? "#E3B341" : win.modInk
                            Rectangle { visible: !Backend.wrap; x: 6; y: edit.y + parent.a.y + parent.a.height / 2 - 4; width: 8; height: 8; radius: 4; color: parent.ink }
                            Rectangle { x: edit.x + parent.a.x; y: edit.y + parent.a.y + parent.a.height - 2; width: Math.max(8, (parent.b.y === parent.a.y ? parent.b.x : edit.contentWidth) - parent.a.x); height: 2; color: parent.ink; opacity: 0.85 } } }
                    TextEdit { id: edit; objectName: "editor"; x: Backend.wrap ? 20 : gutter.width + 6; y: 12
                        width: Backend.wrap ? scroll.width - 40 : Math.max(contentWidth + 20, scroll.width - x - 10)
                        color: win.codeInk; selectionColor: win.themed && win.vsTheme.select ? win.vsTheme.select : Qt.alpha(Theme.t.accent, 0.45); selectedTextColor: win.codeInk
                        font.family: win.mono; font.pixelSize: Backend.size; wrapMode: Backend.wrap ? TextEdit.Wrap : TextEdit.NoWrap; textFormat: TextEdit.PlainText
                        readOnly: !!v.info.readOnly; selectByMouse: true; persistentSelection: true; tabStopDistance: win.tabW * widest.advanceWidth; focus: v.index === Backend.current
                        onActiveFocusChanged: if (activeFocus && win.split && v.index !== Backend.current) { var side = v.side; Backend.select(v.index); win.pane = side }
                        TextMetrics { id: widest; font: edit.font; text: " " }
                        Row { visible: v.ghost !== "" && edit.cursorPosition === v.ghostAt; x: edit.cursorRectangle.x; y: edit.cursorRectangle.y; spacing: 8
                            Text { text: v.ghost.split("\n")[0] === "" && v.ghost.indexOf("\n") >= 0 ? "↵" : v.ghost.split("\n")[0]; font: edit.font; color: Theme.t.text_tertiary; textFormat: Text.PlainText }
                            Rectangle { readonly property int more: v.ghost.split("\n").length - 1; visible: more > 0; anchors.verticalCenter: parent.verticalCenter
                                width: moreL.width + 12; height: 18; radius: 6; color: Qt.alpha(Theme.t.accent, 0.18)
                                Label { id: moreL; anchors.centerIn: parent; text: "+" + parent.more + (parent.more === 1 ? " line" : " lines") + " · Tab"; font.pixelSize: 10; color: Theme.t.accent } } }
                        onTextChanged: {
                            if (v.loading || text === v.known || v.nbOn) return      // colouring touches the text too: only real typing counts (and a notebook's cells own its text)
                            if (v.snip && !v.multiBusy) v.snipShift(length - v.snip.len)
                            if (!v.multiBusy && v.extra.length) v.extra = []
                            conflictTick.restart(); stickyTick.restart(); decoTick.restart(); foldTick.restart(); hintTick.restart()
                            if (v.peekAt) v.peekAt = null
                            v.known = text
                            mmTick.restart()
                            Backend.edit(v.index, text); v.lineStarts()
                            if (win.finding) win.refind()
                            if (win.comp.length) v.filterOffer()
                            v.dropGhost(); if (win.aiInline) ghostTick.restart()
                            var c = getText(Math.max(0, cursorPosition - 1), cursorPosition)
                            if (/[A-Za-z_.]/.test(c)) suggestTimer.restart(); else if (!win.comp.length) suggestTimer.stop()
                        }
                        onCursorPositionChanged: { if (v.visible) { var lc = v.lineCol(); win.curLine = lc[0] + 1; win.curCol = lc[1] + 1 } if (win.tip) win.tip = ""
                            if ((v.ghost !== "" || v.ghostJob >= 0) && cursorPosition !== v.ghostAt) v.dropGhost()
                            if (win.sig && v.visible && !v.inCall()) win.sig = null
                            if (v.visible) { pairTick.restart(); decoTick.restart(); placeTick.restart()
                                if (v.index === Backend.current && !v.loading) win.noteMove(v.info.path, win.curLine - 1, win.curCol - 1) }
                            if (v.snip && !v.multiBusy) Qt.callLater(v.checkSnip)    // after the text has caught up (the cursor moves first)
                            if (win.fixMenu) win.fixMenu = null }
                        TapHandler { acceptedModifiers: Qt.AltModifier; onTapped: function (p) { var at = edit.positionAt(p.position.x, p.position.y); if (!v.taken(at, at)) v.extra = v.extra.concat([{ a: at, p: at }]) } }
                        TapHandler { acceptedModifiers: Qt.NoModifier; onTapped: if (v.extra.length) v.extra = [] }
                        onCursorRectangleChanged: if (v.visible) scroll.follow(cursorRectangle)
                        TapHandler { acceptedModifiers: Qt.ControlModifier; onTapped: function (p) { edit.cursorPosition = edit.positionAt(p.position.x, p.position.y); v.definition() } }
                        Keys.onPressed: function (e) {
                            var ctrl = (e.modifiers & Qt.ControlModifier), shift = (e.modifiers & Qt.ShiftModifier), t = edit.text, at = edit.cursorPosition
                            if (v.ghost !== "" && at === v.ghostAt && !win.comp.length) {
                                if (e.key === Qt.Key_Tab && !ctrl && !shift) { v.acceptGhost(); e.accepted = true; return }
                                if (e.key === Qt.Key_Escape) { v.dropGhost(); e.accepted = true; return }
                            }
                            if (win.comp.length) {
                                if (e.key === Qt.Key_Down) { win.compAt = (win.compAt + 1) % win.comp.length; e.accepted = true; return }
                                if (e.key === Qt.Key_Up) { win.compAt = (win.compAt - 1 + win.comp.length) % win.comp.length; e.accepted = true; return }
                                if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_Tab) { v.accept(win.comp[win.compAt]); e.accepted = true; return }
                                if (e.key === Qt.Key_Escape) { win.comp = []; e.accepted = true; return }
                            }
                            if (win.fixMenu && win.fixMenu.items.length) {
                                if (e.key === Qt.Key_Down) { win.fixMenu = { items: win.fixMenu.items, k: (win.fixMenu.k + 1) % win.fixMenu.items.length }; e.accepted = true; return }
                                if (e.key === Qt.Key_Up) { win.fixMenu = { items: win.fixMenu.items, k: (win.fixMenu.k - 1 + win.fixMenu.items.length) % win.fixMenu.items.length }; e.accepted = true; return }
                                if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { Backend.applyFix(win.fixMenu.k); win.fixMenu = null; e.accepted = true; return }
                                if (e.key === Qt.Key_Escape) { win.fixMenu = null; e.accepted = true; return }
                            }
                            if (readOnly) return
                            var alt = (e.modifiers & Qt.AltModifier)
                            if (alt && !ctrl && (e.key === Qt.Key_Up || e.key === Qt.Key_Down)) { v.lineCmd((shift ? "copy_" : "") + (e.key === Qt.Key_Up ? "up" : "down")); e.accepted = true; return }
                            if (ctrl && shift && e.key === Qt.Key_K) { v.lineCmd("delete"); e.accepted = true; return }
                            if (ctrl && !shift && !alt && e.key === Qt.Key_J) { v.lineCmd("join"); e.accepted = true; return }
                            if (ctrl && !shift && !alt && e.key === Qt.Key_L) { v.lineCmd("select"); e.accepted = true; return }
                            if (ctrl && (e.key === Qt.Key_Return || e.key === Qt.Key_Enter)) { v.lineCmd(shift ? "above" : "below"); e.accepted = true; return }
                            if (e.key === Qt.Key_F7) { v.goChange(shift ? -1 : 1); e.accepted = true; return }
                            if (ctrl && !shift && e.key === Qt.Key_D) { v.addNext(); e.accepted = true; return }
                            if (ctrl && shift && e.key === Qt.Key_L) { v.selectEvery(); e.accepted = true; return }
                            if (ctrl && alt && (e.key === Qt.Key_Down || e.key === Qt.Key_Up)) { v.addVertical(e.key === Qt.Key_Down ? 1 : -1); e.accepted = true; return }
                            if (ctrl && e.key === Qt.Key_Period) { v.fixHere(); e.accepted = true; return }
                            if (v.snip && e.key === Qt.Key_Tab && !shift) { v.nextStop(); e.accepted = true; return }
                            if (v.snip && e.key === Qt.Key_Escape) { v.snip = null; e.accepted = true; return }
                            if (win.sig && (e.key === Qt.Key_Escape || e.text === ")")) win.sig = null
                            if (v.extra.length && v.multiKey(e)) { e.accepted = true; return }
                            if (e.text === "(" || e.text === ",") Qt.callLater(v.askSignature)
                            if (ctrl && e.key === Qt.Key_Space) { v.suggest(); e.accepted = true; return }
                            if (ctrl && (e.key === Qt.Key_Slash || e.key === Qt.Key_Question)) { v.toggleComment(); e.accepted = true; return }
                            if (ctrl && e.key === Qt.Key_I && !shift) { v.hover(); e.accepted = true; return }
                            if (e.key === Qt.Key_F12 && shift) { v.referencesHere(); e.accepted = true; return }
                            if (e.key === Qt.Key_F2) { v.renameHere(); e.accepted = true; return }
                            if (e.key === Qt.Key_F9) { var lc9 = v.lineCol(); Backend.toggleBreakpoint(v.index, lc9[0]); e.accepted = true; return }
                            if (e.key === Qt.Key_F12 && alt) { v.peek(); e.accepted = true; return }
                            if (e.key === Qt.Key_F12) { v.definition(); e.accepted = true; return }
                            if (e.key === Qt.Key_Escape && v.peekAt) { v.peekAt = null; e.accepted = true; return }
                            if (e.key === Qt.Key_Tab && !ctrl) {
                                var em = edit.selectedText === "" ? Backend.emmetAt(v.index, t.substring(t.lastIndexOf("\n", at - 1) + 1, at)) : ({})
                                if (em.body) { v.startSnippet(at - em.back, at, em.body); e.accepted = true; return }
                                if (edit.selectedText.indexOf("\n") >= 0) v.indent(false); else { edit.remove(edit.selectionStart, edit.selectionEnd); edit.insert(edit.cursorPosition, win.unit) }
                                e.accepted = true; return }
                            if (e.key === Qt.Key_Backtab) { v.indent(true); e.accepted = true; return }
                            if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !ctrl && !shift) {
                                var ls = t.lastIndexOf("\n", at - 1) + 1, line = t.substring(ls, at), ind = /^[ \t]*/.exec(line)[0], trimmed = line.replace(/\s+$/, "")
                                var opens = /[:{(\[]$/.test(trimmed), next = t.charAt(at), pair = { "{": "}", "(": ")", "[": "]" }[trimmed.slice(-1)]
                                edit.remove(edit.selectionStart, edit.selectionEnd)
                                if (pair && next === pair) { edit.insert(edit.cursorPosition, "\n" + ind + win.unit + "\n" + ind); edit.cursorPosition = edit.cursorPosition - 1 - ind.length }
                                else edit.insert(edit.cursorPosition, "\n" + ind + (opens ? win.unit : ""))
                                e.accepted = true; return }
                            if (e.key === Qt.Key_Backspace && !ctrl && edit.selectionStart === edit.selectionEnd && at > 0) {
                                var prev = t.charAt(at - 1), nx = t.charAt(at)
                                if (({ "(": ")", "[": "]", "{": "}", "\"": "\"", "'": "'" })[prev] === nx && nx) { edit.remove(at - 1, at + 1); e.accepted = true; return }
                                var before = t.substring(t.lastIndexOf("\n", at - 1) + 1, at)
                                if (before.length && /^ +$/.test(before) && win.unit !== "\t" && before.length % win.unit.length === 0) { edit.remove(at - win.unit.length, at); e.accepted = true; return }
                                return }
                            var ch = e.text
                            if (!ctrl && ch.length === 1) {
                                var closer = ({ "(": ")", "[": "]", "{": "}" })[ch], after = t.charAt(at), prevc = t.charAt(at - 1)
                                if (closer) {
                                    if (edit.selectedText) { var a1 = edit.selectionStart, s1 = edit.selectedText; edit.remove(a1, edit.selectionEnd); edit.insert(a1, ch + s1 + closer); edit.select(a1 + 1, a1 + 1 + s1.length); e.accepted = true; return }
                                    if (!after || /[\s)\]},;:]/.test(after)) { edit.insert(at, ch + closer); edit.cursorPosition = at + 1; e.accepted = true; return }
                                }
                                if ((ch === ")" || ch === "]" || ch === "}") && after === ch) { edit.cursorPosition = at + 1; e.accepted = true; return }
                                if (ch === "\"" || ch === "'" || ch === "`") {
                                    if (after === ch) { edit.cursorPosition = at + 1; e.accepted = true; return }
                                    if (edit.selectedText) { var a2 = edit.selectionStart, s2 = edit.selectedText; edit.remove(a2, edit.selectionEnd); edit.insert(a2, ch + s2 + ch); e.accepted = true; return }
                                    if (!/[A-Za-z0-9_]/.test(prevc) && (!after || /[\s)\]},;:]/.test(after))) { edit.insert(at, ch + ch); edit.cursorPosition = at + 1; e.accepted = true; return }
                                }
                                if (closer === undefined && ch === "}" && /^[ \t]+$/.test(t.substring(t.lastIndexOf("\n", at - 1) + 1, at))) {   // a closing brace on its own line steps back
                                    var ls2 = t.lastIndexOf("\n", at - 1) + 1, sp = t.substring(ls2, at)
                                    var shorter = sp.indexOf(win.unit) === 0 ? sp.substring(win.unit.length) : sp.replace(/^(\t| {1,4})/, "")
                                    edit.remove(ls2, at); edit.insert(ls2, shorter + "}"); e.accepted = true; return }
                            }
                        } }
                    MouseArea { y: edit.y + edit.height; width: scroll.contentWidth; height: Math.max(0, scroll.contentHeight - y); onClicked: { edit.forceActiveFocus(); edit.cursorPosition = edit.length } } }
                Timer { id: suggestTimer; interval: 260; onTriggered: { if (v.visible && edit.activeFocus) { var w = v.wordBefore(), c = edit.getText(Math.max(0, edit.cursorPosition - 1), edit.cursorPosition)
                    if (c === "." || w.length >= 2) v.suggest() } } }
                // the suggestion list, under the cursor
                Rectangle { id: compBox; visible: v.visible && v.index === Backend.current && win.comp.length > 0; z: 5; width: 380; height: Math.min(8, win.comp.length) * 30 + 10; radius: 12
                    color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                    readonly property point at: edit.mapToItem(v, edit.cursorRectangle.x, edit.cursorRectangle.y + edit.cursorRectangle.height)
                    x: Math.min(at.x, v.width - width - 10); y: at.y + height + 6 > v.height ? at.y - edit.cursorRectangle.height - height - 4 : at.y + 4
                    ListView { id: compList; anchors { fill: parent; margins: 5 } clip: true; model: win.comp; currentIndex: win.compAt; highlightMoveDuration: 0
                        onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
                        delegate: Pressable { required property var modelData; required property int index; width: compList.width; height: 30; radius: 7
                            color: index === win.compAt ? Qt.alpha(Theme.t.accent, 0.25) : hovered ? Theme.t.hover : "transparent"
                            onClicked: { v.accept(modelData); edit.forceActiveFocus() }
                            Rectangle { x: 8; anchors.verticalCenter: parent.verticalCenter; width: 16; height: 16; radius: 4
                                color: modelData.kind === 15 ? "#56D4BC" : [2, 3, 4].indexOf(modelData.kind) >= 0 ? "#B392F0" : [5, 6, 10].indexOf(modelData.kind) >= 0 ? "#79B8FF" : [7, 8, 22].indexOf(modelData.kind) >= 0 ? "#F0B72F" : modelData.kind === 14 ? "#F97583" : Theme.t.text_secondary
                                Text { anchors.centerIn: parent; text: modelData.kind === 15 ? "⌁" : [2, 3, 4].indexOf(modelData.kind) >= 0 ? "ƒ" : [5, 6, 10].indexOf(modelData.kind) >= 0 ? "v" : [7, 8, 22].indexOf(modelData.kind) >= 0 ? "C" : modelData.kind === 9 ? "m" : modelData.kind === 14 ? "k" : "a"
                                    font.pixelSize: 10; font.bold: true; color: "#111" } }
                            Text { x: 32; width: parent.width * 0.55; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; font.family: win.mono; font.pixelSize: 12; color: Theme.t.text
                                textFormat: Text.StyledText; text: "<b>" + modelData.label.substring(0, win.compPrefix.length) + "</b>" + modelData.label.substring(win.compPrefix.length) }
                            Label { anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } width: parent.width * 0.38; elide: Text.ElideRight; horizontalAlignment: Text.AlignRight
                                text: modelData.detail; font.pixelSize: 10; secondary: true } } } }
                // sticky scroll: the scopes the top of the view is inside
                Column { objectName: "stickyRows"; visible: v.visible && v.sticky.length > 0 && !v.info.binary; z: 4; x: scroll.x; y: scroll.y; width: scroll.width
                    Repeater { model: v.sticky
                        Rectangle { required property var modelData; width: parent.width; height: edit.cursorRectangle.height + 2; color: win.slab
                            Text { x: 0; width: gutter.width; horizontalAlignment: Text.AlignRight; rightPadding: 14; anchors.verticalCenter: parent.verticalCenter; text: modelData.line + 1
                                font.family: win.mono; font.pixelSize: Backend.size; color: win.gutterInk }
                            Text { x: edit.x - scroll.contentX; anchors.verticalCenter: parent.verticalCenter; text: modelData.text; font.family: win.mono; font.pixelSize: Backend.size; color: win.codeInk; textFormat: Text.PlainText }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: v.goTo(modelData.line, 0) } } }
                    Rectangle { width: parent.width; height: 1; color: Theme.t.islandLine } }
                // what the call being typed wants
                Rectangle { objectName: "sigTip"; visible: v.visible && v.index === Backend.current && win.sig !== null && !win.comp.length; z: 6; radius: 10
                    width: Math.min(v.width - 40, sigText.implicitWidth + 24); height: sigText.height + (sigDoc.visible ? sigDoc.height + 6 : 0) + 16
                    color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                    readonly property point at: edit.mapToItem(v, edit.cursorRectangle.x, edit.cursorRectangle.y)
                    x: Math.max(8, Math.min(at.x - 30, v.width - width - 10)); y: at.y - height - 6 < 0 ? at.y + edit.cursorRectangle.height + 6 : at.y - height - 6
                    function esc(t) { return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
                    Text { id: sigText; x: 12; y: 8; font.family: win.mono; font.pixelSize: 12; color: Theme.t.text; textFormat: Text.StyledText
                        text: !win.sig ? "" : win.sig.a < 0 ? parent.esc(win.sig.label) : parent.esc(win.sig.label.substring(0, win.sig.a)) + "<b><font color='" + Theme.t.accent + "'>"
                              + parent.esc(win.sig.label.substring(win.sig.a, win.sig.b)) + "</font></b>" + parent.esc(win.sig.label.substring(win.sig.b)) }
                    Text { id: sigDoc; visible: !!win.sig && win.sig.doc !== ""; x: 12; y: sigText.height + 12; width: Math.min(520, v.width - 64); wrapMode: Text.Wrap; maximumLineCount: 4; elide: Text.ElideRight
                        font.pixelSize: 11; color: Theme.t.text_secondary; text: win.sig ? win.sig.doc : "" } }
                // quick fixes at the cursor
                Rectangle { objectName: "fixMenu"; visible: v.visible && v.index === Backend.current && win.fixMenu !== null; z: 7; width: 360; height: (win.fixMenu ? win.fixMenu.items.length : 0) * 30 + 10; radius: 12
                    color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                    readonly property point at: edit.mapToItem(v, edit.cursorRectangle.x, edit.cursorRectangle.y + edit.cursorRectangle.height)
                    x: Math.min(at.x, v.width - width - 10); y: at.y + height + 6 > v.height ? at.y - edit.cursorRectangle.height - height - 4 : at.y + 4
                    Column { x: 5; y: 5; width: parent.width - 10
                        Repeater { model: win.fixMenu ? win.fixMenu.items : []
                            Pressable { required property var modelData; required property int index; width: parent.width; height: 30; radius: 7
                                color: win.fixMenu && index === win.fixMenu.k ? Qt.alpha(Theme.t.accent, 0.25) : hovered ? Theme.t.hover : "transparent"
                                onClicked: { Backend.applyFix(index); win.fixMenu = null; edit.forceActiveFocus() }
                                Text { x: 10; anchors.verticalCenter: parent.verticalCenter; text: "💡"; font.pixelSize: 11 }
                                Label { x: 30; width: parent.width - 40; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: modelData.title; font.pixelSize: 12 } } } } }
                // Markdown as it reads, beside its text
                Rectangle { objectName: "mdPreview"; visible: win.mdPreview && v.info.lang === "Markdown"; z: 3; anchors { right: parent.right; top: parent.top; bottom: parent.bottom; margins: 6 }
                    width: parent.width / 2 - 10; radius: 12; color: Theme.t.dark ? "#16181D" : "#FFFFFF"; border.width: 1; border.color: Theme.t.islandLine; clip: true
                    Flickable { id: mdFlick; anchors.fill: parent; anchors.margins: 18; contentHeight: mdText.height + 40; boundsBehavior: Flickable.StopAtBounds; clip: true
                        contentY: scroll.contentHeight > scroll.height ? Math.max(0, Math.min(contentHeight - height, scroll.contentY / (scroll.contentHeight - scroll.height) * (contentHeight - height))) : 0
                        Text { id: mdText; width: mdFlick.width; wrapMode: Text.Wrap; textFormat: Text.MarkdownText; text: edit.text; color: Theme.t.text; font.pixelSize: 14
                            baseUrl: "file://" + v.path; onLinkActivated: function (link) { Qt.openUrlExternally(link) } } } }
                // what the language server says about the word under the cursor
                Rectangle { id: peekBox; objectName: "peekBox"; visible: v.visible && v.peekAt !== null; z: 6; width: Math.min(760, v.width - 60); height: peekCode.contentHeight + 52; radius: 12; clip: true
                    color: win.slab; border.width: 1; border.color: Theme.t.accent
                    readonly property point at: edit.mapToItem(v, 0, edit.cursorRectangle.y + edit.cursorRectangle.height)
                    x: Math.max(20, (v.width - width) / 2); y: at.y + 6 + height > v.height ? Math.max(8, at.y - edit.cursorRectangle.height - height - 6) : at.y + 6
                    Rectangle { width: parent.width; height: 34; radius: 12; color: Qt.alpha(Theme.t.accent, 0.14)
                        Label { x: 14; width: parent.width - 150; elide: Text.ElideMiddle; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; font.weight: Font.DemiBold; color: win.codeInk
                            text: v.peekAt ? v.peekAt.name + "  ·  line " + (v.peekAt.line + 1) : "" }
                        Row { anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } spacing: 2
                            Seg { text: "Open"; tip: "Go there (F12)"; onClicked: { var w = v.peekAt; v.peekAt = null; Backend.openFile(w.path, true, w.line, 0) } }
                            Seg { icon: "x"; onClicked: { v.peekAt = null; v.focusEditor() } } } }
                    Rectangle { visible: v.peekAt !== null; x: 0; y: 40 + (v.peekAt ? (v.peekAt.line - v.peekAt.first) : 0) * (peekCode.contentHeight / Math.max(1, peekCode.lineCount)); width: parent.width; height: peekCode.contentHeight / Math.max(1, peekCode.lineCount); color: win.lineGlow }
                    Text { x: 12; y: 40; width: 44; horizontalAlignment: Text.AlignRight; color: win.gutterInk; font.family: win.mono; font.pixelSize: Math.max(10, Backend.size - 1); textFormat: Text.PlainText
                        text: { if (!v.peekAt) return ""; var n = v.peekAt.text.split("\n").length, a = []; for (var k = 0; k < n; k++) a.push(v.peekAt.first + k + 1); return a.join("\n") } }
                    Text { id: peekCode; x: 68; y: 40; width: parent.width - 80; clip: true; color: win.codeInk; font.family: win.mono; font.pixelSize: Math.max(10, Backend.size - 1); textFormat: Text.PlainText
                        text: v.peekAt ? v.peekAt.text.replace(/\t/g, "    ") : "" } }
                Rectangle { visible: v.visible && win.tip !== ""; z: 6; width: Math.min(560, v.width - 40); height: Math.min(260, tipText.contentHeight + 24); radius: 12; clip: true
                    color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
                    readonly property point at: edit.mapToItem(v, edit.cursorRectangle.x, edit.cursorRectangle.y)
                    x: Math.min(at.x, v.width - width - 10); y: at.y - height - 6 < 0 ? at.y + edit.cursorRectangle.height + 6 : at.y - height - 6
                    Text { id: tipText; x: 12; y: 12; width: parent.width - 24; wrapMode: Text.Wrap; textFormat: Text.MarkdownText; text: win.tip; color: Theme.t.text; font.pixelSize: 12 } }
            } }

        // find and replace, floating at the slab's top right
        Rectangle { id: findBar; objectName: "findBar"; visible: win.finding && Backend.current >= 0; z: 8; anchors { right: parent.right; rightMargin: 14; top: parent.top; topMargin: 10 } width: 430; height: win.replacing ? 84 : 46; radius: 12
            color: Theme.t.menu_bg; border.width: 1; border.color: Theme.t.menu_border
            Row { x: 8; y: 7; spacing: 4
                Rectangle { width: 190; height: 32; radius: 8; color: Theme.t.capsule; border.width: 1; border.color: findBox.activeFocus ? Theme.t.accent : Theme.t.capsule_border
                    TextInput { id: findBox; objectName: "findBox"; x: 8; width: parent.width - 16; anchors.verticalCenter: parent.verticalCenter; color: Theme.t.text; font.pixelSize: 13; clip: true; selectByMouse: true
                        onTextChanged: win.refind()
                        Keys.onPressed: function (e) { if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { win.step((e.modifiers & Qt.ShiftModifier) ? -1 : 1); e.accepted = true } else if (e.key === Qt.Key_Escape) { win.finding = false; win.view().focusEditor(); e.accepted = true } }
                        Text { visible: !findBox.text; text: "Find"; color: Theme.t.text_secondary; font: findBox.font } } }
                Seg { id: matchCase; property bool on2: false; text: "Aa"; on: on2; tip: "Match case"; onClicked: { on2 = !on2; win.refind() } }
                Seg { id: matchWord; property bool on2: false; text: "W"; on: on2; tip: "Whole words"; onClicked: { on2 = !on2; win.refind() } }
                Seg { id: matchRe; property bool on2: false; text: ".*"; on: on2; tip: "Pattern"; onClicked: { on2 = !on2; win.refind() } }
                Label { width: 48; horizontalAlignment: Text.AlignHCenter; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 11; secondary: true
                    text: findBox.text ? (win.matches.length ? (win.matchAt + 1) + "/" + win.matches.length : "none") : "" }
                Seg { icon: "up"; tip: "Previous (Shift+Enter)"; onClicked: win.step(-1) }
                Seg { icon: "down"; tip: "Next (Enter)"; onClicked: win.step(1) } }
            Row { visible: win.replacing; x: 8; y: 46; spacing: 6
                Rectangle { width: 190; height: 30; radius: 8; color: Theme.t.capsule; border.width: 1; border.color: replaceBox.activeFocus ? Theme.t.accent : Theme.t.capsule_border
                    TextInput { id: replaceBox; x: 8; width: parent.width - 16; anchors.verticalCenter: parent.verticalCenter; color: Theme.t.text; font.pixelSize: 13; clip: true; selectByMouse: true
                        Keys.onReturnPressed: win.replaceOne()
                        Text { visible: !replaceBox.text; text: "Replace with"; color: Theme.t.text_secondary; font: replaceBox.font } } }
                Btn { text: "Replace"; onClicked: win.replaceOne() }
                Btn { text: "All"; onClicked: win.replaceEvery() } } }

        // nothing open
        Column { visible: Backend.tabs.length === 0; anchors.centerIn: parent; spacing: 14; width: 420
            Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 76; height: 76; radius: 22; color: Theme.t.accent
                Text { anchors.centerIn: parent; text: "{ }"; color: Theme.t.onAccent; font.family: win.mono; font.pixelSize: 28; font.bold: true } }
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: Backend.root ? Backend.rootName : "Code"; font.pixelSize: 26; font.weight: Font.Bold }
            Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; secondary: true
                text: Backend.root ? "Pick a file on the left, or press Ctrl+P and type part of its name." : "Open a project folder to start. Code reads its files, its Git history and speaks to your language's tools." }
            Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 8
                Btn { visible: !Backend.root; primary: true; text: "Open Folder…"; onClicked: { win.browseAt = Backend.home; win.ask("open") } }
                Btn { text: "New File"; onClicked: win.newFile() }
                Btn { text: "Languages…"; onClicked: win.ask("langs", { mode: "manage" }) } }
            Column { visible: !Backend.root && Backend.recent.length > 0; width: parent.width; spacing: 2; topPadding: 8
                Label { text: "RECENT"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2; secondary: true }
                Repeater { model: Backend.recent.slice(0, 6)
                    Pressable { required property var modelData; width: parent.width; height: 34; radius: 9; color: hovered ? Theme.t.hover : "transparent"; onClicked: Backend.openFolder(modelData.path)
                        Label { x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.weight: Font.DemiBold }
                        Label { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } text: modelData.where; secondary: true; font.pixelSize: 11 } } } }
            Grid { anchors.horizontalCenter: parent.horizontalCenter; columns: 2; columnSpacing: 18; rowSpacing: 6; topPadding: 10
                Repeater { model: ["Ctrl+P", "Go to a file", "Ctrl+Shift+P", "Every command", "Ctrl+Shift+F", "Search the project", "Ctrl+`", "The terminal", "F5", "Run"]
                    Label { required property string modelData; required property int index; text: modelData; font.pixelSize: 12; font.family: index % 2 === 0 ? win.mono : Theme.t.font
                        color: index % 2 === 0 ? Theme.t.accent : Theme.t.text_secondary } } } }
    }

    // ================================================================ the terminal
    Rectangle { visible: win.split; z: 4; x: slab.x + slab.width / 2 - 1; y: slab.y + 8; width: 2; height: slab.height - 16; radius: 1; color: Theme.t.islandLine }
    // the debugger's controls: in the bottom panel's header, or floating at the foot of the editor when the panel is closed
    component DebugButtons: Row { spacing: 2
        Rectangle { width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter; color: win.dbg.state === "stopped" ? "#F5B83D" : "#30A46C" }
        Label { text: win.dbg.state === "stopped" ? "Paused" : win.dbg.state === "starting" ? "Starting…" : "Running"; font.pixelSize: 11; leftPadding: 4; rightPadding: 6; anchors.verticalCenter: parent.verticalCenter }
        Seg { icon: win.dbg.state === "stopped" ? "play" : "pause"; tip: win.dbg.state === "stopped" ? "Continue (F5)" : "Pause (F6)"; onClicked: win.dbg.state === "stopped" ? win.dbg.resume() : win.dbg.pause() }
        Seg { icon: "next"; tip: "Step over (F10)"; enabled: win.dbg.state === "stopped"; opacity: enabled ? 1 : 0.4; onClicked: win.dbg.stepOver() }
        Seg { icon: "down"; tip: "Step into (F11)"; enabled: win.dbg.state === "stopped"; opacity: enabled ? 1 : 0.4; onClicked: win.dbg.stepIn() }
        Seg { icon: "up"; tip: "Step out (Shift+F11)"; enabled: win.dbg.state === "stopped"; opacity: enabled ? 1 : 0.4; onClicked: win.dbg.stepOut() }
        Seg { icon: "refresh"; tip: "Restart"; onClicked: win.dbg.restart() }
        Seg { icon: "stop"; tip: "Stop (Shift+F5)"; danger: true; onClicked: win.dbg.stop() } }
    Rectangle { id: dbgBar; objectName: "dbgBar"; visible: win.dbg.active && !win.term; z: 9; y: slab.y + slab.height - height - 12; x: slab.x + (slab.width - width) / 2; height: 40; width: dbgFloat.width + 14; radius: 16
        color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
        DebugButtons { id: dbgFloat; x: 7; anchors.verticalCenter: parent.verticalCenter } }
    Rectangle { id: termBox; objectName: "termBox"; visible: win.term; x: slab.x; width: slab.width; height: Math.min(280, win.height * 0.34); y: slab.y + slab.height + 10; radius: 16
        color: Theme.t.dark ? "#0B0D10" : "#F7F8FA"; border.width: 1; border.color: Theme.t.islandLine; clip: true
        property var sh: win.term && win.bottom === "terminal" ? Backend.terminal : null
        Row { x: 8; y: 6; spacing: 2; z: 3
            Seg { text: "Terminal"; on: win.bottom === "terminal"; onClicked: { win.bottom = "terminal"; Qt.callLater(function () { termKeys.forceActiveFocus() }) } }
            Seg { text: "Debug" + (win.dbg.active ? " ·" : ""); on: win.bottom === "debug"; onClicked: win.bottom = "debug" }
            Seg { objectName: "buildTab"; text: "Build" + (win.bld.running ? " ·" : win.bld.errors ? " " + win.bld.errors : ""); on: win.bottom === "build"; onClicked: win.bottom = "build" } }
        // ---- build: the project's tasks on the left, the running task's output on the right (a line that names a place opens it)
        Item { id: buildPanel; objectName: "buildPanel"; visible: win.bottom === "build"; anchors { fill: parent; topMargin: 42; leftMargin: 10; rightMargin: 10; bottomMargin: 8 }
            property string hint: ""                                        // what the task under the pointer would run
            readonly property var groupNames: ({ "build": "BUILD", "run": "RUN", "test": "TEST", "package": "PACKAGE", "clean": "CLEAN", "setup": "SET UP" })
            ListView { id: taskList; objectName: "taskList"; width: Math.min(280, parent.width * 0.3); height: parent.height; clip: true; boundsBehavior: Flickable.StopAtBounds; spacing: 1
                model: win.bld.tasks
                section.property: "group"
                section.delegate: Label { required property string section; x: 8; height: 22; verticalAlignment: Text.AlignBottom; text: buildPanel.groupNames[section] || section; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1; secondary: true }
                delegate: Pressable { id: taskRow; required property var modelData; width: taskList.width - 6; height: 30; radius: 8
                    readonly property bool now: win.bld.running && win.bld.taskName === modelData.name
                    color: now ? Qt.alpha(Theme.t.accent, 0.2) : hovered ? Theme.t.hover : "transparent"
                    onClicked: win.runTask(modelData.id)
                    Rectangle { visible: taskRow.modelData.default; x: 4; anchors.verticalCenter: parent.verticalCenter; width: 4; height: 14; radius: 2; color: Theme.t.accent }
                    Label { x: 14; width: parent.width - 44; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: taskRow.modelData.name; font.pixelSize: 12
                        font.weight: taskRow.modelData.default ? Font.DemiBold : Font.Normal; color: taskRow.modelData.group === "setup" && !taskRow.modelData.command ? win.modInk : Theme.t.text }
                    Seg { visible: taskRow.hovered && !taskRow.modelData.default && taskRow.modelData.group === "build" && !!taskRow.modelData.command
                        anchors { right: parent.right; rightMargin: 2; verticalCenter: parent.verticalCenter } icon: "check"; tip: "Make this what Build (Ctrl+Shift+B) runs"; onClicked: win.bld.makeDefault(taskRow.modelData.id) }
                    onHoveredChanged: buildPanel.hint = hovered ? (modelData.detail ? modelData.detail + ":  " : "") + modelData.command : "" }
                footer: Column { width: taskList.width - 6; topPadding: 8; spacing: 2
                    Label { visible: toolRep.count > 0; x: 8; text: "TOOLS"; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1; secondary: true }
                    Repeater { id: toolRep; model: win.bld.packs.filter(function (p) { return !p.ready })
                        Pressable { id: packRow; required property var modelData; width: taskList.width - 6; height: 30; radius: 8; color: hovered ? Theme.t.hover : "transparent"
                            readonly property bool adding: Backend.addingTools.indexOf(modelData.name) >= 0
                            onClicked: if (!adding) Backend.addTools(modelData.name)
                            Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: "plus"; size: 12; ink: Theme.t.text_secondary }
                            Label { x: 30; width: parent.width - 36; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; secondary: packRow.adding; text: packRow.adding ? "Adding " + packRow.modelData.name + "…" : "Add " + packRow.modelData.name }
                            onHoveredChanged: buildPanel.hint = hovered ? modelData.about : "" } } }
                Label { visible: taskList.count === 0; y: 20; width: taskList.width - 12; x: 6; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                    text: Backend.root ? "Nothing to build was found here. Code looks for project.godot, a .uproject, CMakeLists.txt, Cargo.toml, a Makefile, go.mod, package.json, or your own .huginn-tasks.json." : "Open a project folder to see what it can build." } }
            Rectangle { x: taskList.width + 4; width: 1; height: parent.height; color: Theme.t.islandLine }
            Item { x: taskList.width + 14; width: parent.width - x; height: parent.height
                Row { id: buildHead; height: 26; spacing: 6
                    Label { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; font.weight: Font.DemiBold; text: win.bld.taskName || "Build" }
                    Label { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; secondary: true; width: Math.min(implicitWidth, buildOut.width - 260); elide: Text.ElideRight
                        text: !win.bld.running && buildPanel.hint ? buildPanel.hint : win.bld.status }
                    Label { visible: win.bld.errors + win.bld.warnings > 0 && win.bld.running; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; color: win.bld.errors ? win.delInk : "#E3B341"
                        text: (win.bld.errors ? win.bld.errors + (win.bld.errors === 1 ? " error" : " errors") : "") + (win.bld.errors && win.bld.warnings ? ", " : "") + (win.bld.warnings ? win.bld.warnings + (win.bld.warnings === 1 ? " warning" : " warnings") : "") } }
                Row { anchors.right: parent.right; height: 26; spacing: 2
                    Seg { visible: win.bld.running; icon: "stop"; tip: "Stop"; onClicked: win.bld.stop() }
                    Seg { visible: !win.bld.running && !!win.bld.taskName; icon: "refresh"; tip: "Run it again"; onClicked: win.bld.again() }
                    Seg { visible: win.bld.problems.length > 0; icon: "up"; tip: "Previous error (Shift+F8)"; onClicked: win.bld.step(-1) }
                    Seg { visible: win.bld.problems.length > 0; icon: "down"; tip: "Next error (F8)"; onClicked: win.bld.step(1) }
                    Seg { visible: !win.bld.running && buildOut.count > 0; icon: "trash"; tip: "Clear"; onClicked: win.bld.clear() } }
                ListView { id: buildOut; objectName: "buildOut"; y: 30; width: parent.width; height: parent.height - 30; clip: true; boundsBehavior: Flickable.StopAtBounds; model: win.bld.lines; reuseItems: true
                    property bool follow: true                                  // stay at the end while it runs, until you scroll up
                    onCountChanged: if (follow) Qt.callLater(positionViewAtEnd)
                    onMovementEnded: follow = atYEnd
                    delegate: Item { id: outRow; required property int index; required property string text; required property string kind; required property string path
                        width: buildOut.width; height: outText.height
                        Rectangle { anchors.fill: parent; visible: outMouse.containsMouse && !!outRow.path; color: Theme.t.hover; radius: 4 }
                        Text { id: outText; x: 4; width: parent.width - 8; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText; text: outRow.text; font.family: win.mono; font.pixelSize: 12; renderType: Text.NativeRendering
                            font.underline: outMouse.containsMouse && !!outRow.path
                            color: outRow.kind === "error" ? win.delInk : outRow.kind === "warning" ? "#E3B341" : outRow.kind === "command" || outRow.kind === "note" ? Theme.t.text_secondary : outRow.kind === "done" ? win.addInk : Theme.t.text }
                        MouseArea { id: outMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: outRow.path ? Qt.PointingHandCursor : Qt.ArrowCursor; onClicked: if (outRow.path) win.bld.open(outRow.index) } } }
                Label { visible: buildOut.count === 0; anchors.centerIn: parent; width: Math.min(460, parent.width - 20); wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; secondary: true
                    text: "Choose a task, or press Ctrl+Shift+B to build. Errors in the output open the file at the line when clicked; F8 goes to the next one." } } }
        DebugButtons { objectName: "dbgDock"; visible: win.dbg.active; z: 3; y: 6; height: 32; anchors.horizontalCenter: parent.horizontalCenter }
        // ---- the debugger: where it stopped, what things hold, and a console
        Item { id: dbgPanel; visible: win.bottom === "debug"; anchors { fill: parent; topMargin: 42; leftMargin: 10; rightMargin: 10; bottomMargin: 8 }
            Label { visible: !win.dbg.active && win.dbg.output.length === 0; anchors.centerIn: parent; secondary: true; width: 520; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter
                text: "Click beside a line number to set a breakpoint, then press F5. Python uses debugpy; C, C++, Rust and Go use GDB."
                      + (Backend.launches.length ? "\n\nThis project's launch.json:" : "") }
            Flow { visible: !win.dbg.active && win.dbg.output.length === 0 && Backend.launches.length > 0; anchors { horizontalCenter: parent.horizontalCenter; top: parent.verticalCenter; topMargin: 44 } width: Math.min(parent.width - 40, 620); spacing: 6
                Repeater { model: Backend.launches
                    Seg { required property var modelData; text: modelData.name; on: modelData.chosen; opacity: modelData.ok ? 1 : 0.5
                        tip: modelData.ok ? (modelData.chosen ? "What F5 starts" : "Debug with this, and make it what F5 starts") : "Can't be started here: " + modelData.why
                        onClicked: Backend.startLaunch(modelData.name) } } }
            Column { id: stackCol; visible: win.dbg.active; width: parent.width * 0.28; height: parent.height; spacing: 4
                Label { text: "CALL STACK" + (win.dbg.reason ? "  ·  " + win.dbg.reason : ""); secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold; width: parent.width; elide: Text.ElideRight }
                ListView { width: parent.width; height: parent.height - 20; clip: true; model: win.dbg.frames; boundsBehavior: Flickable.StopAtBounds
                    delegate: Pressable { required property var modelData; width: ListView.view.width; height: 24; radius: 6
                        color: win.dbg.frame === modelData.id ? Qt.alpha(Theme.t.accent, 0.2) : (hovered ? Theme.t.hover : "transparent")
                        onClicked: win.dbg.selectFrame(modelData.id)
                        Text { x: 6; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 12; elide: Text.ElideRight; font.family: win.mono; font.pixelSize: 11; color: modelData.file ? Theme.t.text : Theme.t.text_secondary
                            text: modelData.name + "   " + modelData.short + (modelData.file ? ":" + (modelData.line + 1) : "") } } } }
            Column { visible: win.dbg.active; x: stackCol.width + 12; width: parent.width * 0.36; height: parent.height; spacing: 4
                Label { text: "VARIABLES"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold }
                ListView { width: parent.width; height: parent.height - 20; clip: true; model: win.dbg.variables; boundsBehavior: Flickable.StopAtBounds
                    delegate: Item { required property var modelData; width: ListView.view.width; height: 22
                        Text { x: modelData.depth * 14; width: 12; anchors.verticalCenter: parent.verticalCenter; text: modelData.expandable ? (modelData.open ? "▾" : "▸") : ""; color: Theme.t.text_secondary; font.pixelSize: 11 }
                        Text { x: modelData.depth * 14 + 14; width: parent.width - x; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; font.family: win.mono; font.pixelSize: 11; textFormat: Text.PlainText
                            color: modelData.scope ? Theme.t.text_secondary : Theme.t.text; font.weight: modelData.scope ? Font.DemiBold : Font.Normal
                            text: modelData.scope ? modelData.name : modelData.name + " = " + modelData.value + (modelData.type ? "   " + modelData.type : "") }
                        MouseArea { anchors.fill: parent; enabled: modelData.expandable; onClicked: win.dbg.expand(modelData.ref) } } } }
            Column { x: win.dbg.active ? stackCol.width + 12 + parent.width * 0.36 + 12 : 0; width: parent.width - x; height: parent.height; spacing: 4
                visible: win.dbg.active || win.dbg.output.length > 0
                Row { width: parent.width; spacing: 6
                    Label { text: "CONSOLE"; secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                    Label { text: "Clear"; color: Theme.t.accent; font.pixelSize: 10; anchors.verticalCenter: parent.verticalCenter; MouseArea { anchors.fill: parent; onClicked: win.dbg.clearConsole() } } }
                ListView { id: dcon; width: parent.width; height: parent.height - 52; clip: true; model: win.dbg.output; boundsBehavior: Flickable.StopAtBounds; onCountChanged: positionViewAtEnd()
                    delegate: Text { required property var modelData; width: dcon.width; wrapMode: Text.WrapAnywhere; font.family: win.mono; font.pixelSize: 11; textFormat: Text.PlainText; text: modelData.text
                        color: ({ error: win.delInk, info: Theme.t.text_secondary, input: Theme.t.accent, result: win.addInk })[modelData.kind] || Theme.t.text } }
                TextBox { width: parent.width; mono: true; placeholder: win.dbg.state === "stopped" ? "Type an expression to work it out here" : "The console answers while the program is paused"
                    onAccepted: { win.dbg.evaluate(text); text = "" } } } }
        Label { visible: !termBox.sh && win.bottom === "terminal"; anchors.centerIn: parent; secondary: true; text: demo ? "The terminal opens here (Ctrl+`)." : "The terminal needs the “pyte” library." }
        TextMetrics { id: tcell; font: tprobe.font; text: "MMMMMMMMMM" }
        Text { id: tprobe; visible: false; font.family: termBox.sh ? termBox.sh.font : win.mono; font.pixelSize: 13; text: "M" }
        ListView { id: tscreen; visible: win.bottom === "terminal"; anchors { fill: parent; margins: 10; leftMargin: 14; topMargin: 42 } clip: true; model: termBox.sh ? termBox.sh.lines : []; boundsBehavior: Flickable.StopAtBounds
            onWidthChanged: trefit.restart(); onHeightChanged: trefit.restart(); onCountChanged: positionViewAtEnd()
            delegate: Text { required property string modelData; width: tscreen.width; height: tprobe.height; textFormat: Text.RichText; text: modelData; font: tprobe.font; color: Theme.t.text; renderType: Text.NativeRendering }
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.MiddleButton; onClicked: function (m) { termKeys.forceActiveFocus(); if (m.button === Qt.MiddleButton && termBox.sh) termBox.sh.paste() } } }
        Timer { id: trefit; interval: 80; onTriggered: if (termBox.sh) termBox.sh.fit(Math.floor(tscreen.width / (tcell.advanceWidth / 10)), Math.floor(tscreen.height / tprobe.height)) }
        onShChanged: trefit.restart()
        Item { id: termKeys; focus: false
            Keys.onPressed: function (e) {
                if (!termBox.sh) return
                if ((e.modifiers & Qt.ControlModifier) && e.key === Qt.Key_QuoteLeft) { win.toggleTerm(); e.accepted = true; return }
                if ((e.modifiers & Qt.ControlModifier) && (e.modifiers & Qt.ShiftModifier)) { if (e.key === Qt.Key_V) termBox.sh.paste(); else if (e.key === Qt.Key_C) termBox.sh.copyAll(); e.accepted = true; return }
                termBox.sh.key(e.key, e.modifiers, e.text); e.accepted = true } }
        Rectangle { anchors { right: parent.right; top: parent.top; margins: 8 } width: 26; height: 26; radius: 13; color: closeTerm.containsMouse ? Theme.t.hover : "transparent"
            Glyph { anchors.centerIn: parent; name: "x"; size: 11 }
            MouseArea { id: closeTerm; anchors.fill: parent; hoverEnabled: true; onClicked: win.toggleTerm() } } }

    // ================================================================ the status line
    Item { id: statusBar; objectName: "statusBar"; visible: !win.zen; x: slab.x; width: slab.width; y: parent.height - 38; height: 28
        Row { x: 6; spacing: 14; anchors.verticalCenter: parent.verticalCenter
            Pressable { visible: Backend.isGit; width: brRow.width + 12; height: 24; radius: 12; color: hovered ? Theme.t.hover : "transparent"; onClicked: win.ask("branches")
                Row { id: brRow; x: 6; spacing: 5; anchors.verticalCenter: parent.verticalCenter
                    Glyph { name: "route"; size: 12; anchors.verticalCenter: parent.verticalCenter }
                    Label { text: Backend.branch + (Backend.changes.length ? " · " + Backend.changes.length + " changed" : ""); font.pixelSize: 11 } } }
            Pressable { width: prRow.width + 12; height: 24; radius: 12; color: hovered ? Theme.t.hover : "transparent"; onClicked: win.showPanel("problems")
                Row { id: prRow; x: 6; spacing: 5; anchors.verticalCenter: parent.verticalCenter
                    Rectangle { width: 7; height: 7; radius: 4; anchors.verticalCenter: parent.verticalCenter; color: Backend.problems.length ? win.delInk : win.addInk }
                    Label { text: Backend.problems.length ? Backend.problems.length + (Backend.problems.length === 1 ? " problem" : " problems") : "No problems"; font.pixelSize: 11 } } }
            Pressable { objectName: "remotePill"; visible: !!Backend.remote.spec; width: rmRow.width + 12; height: 24; radius: 12; color: hovered ? Theme.t.hover : Qt.alpha(Theme.t.accent, 0.16); onClicked: win.openPalette(">Remote")
                Row { id: rmRow; x: 6; spacing: 5; anchors.verticalCenter: parent.verticalCenter
                    Rectangle { width: 7; height: 7; radius: 4; anchors.verticalCenter: parent.verticalCenter; color: Backend.remote.connected ? win.addInk : win.delInk }
                    Label { font.pixelSize: 11; text: "SSH: " + (Backend.remote.spec || "") + (Backend.remote.connected ? "" : "  (not connected)") } } }
            Pressable { objectName: "containerPill"; visible: !!Backend.container.has && !Backend.remote.spec; width: bxRow.width + 12; height: 24; radius: 12
                color: hovered ? Theme.t.hover : !!Backend.container.running ? Qt.alpha(Theme.t.accent, 0.16) : "transparent"; onClicked: !!Backend.container.running ? win.openPalette(">Container") : win.containerAsk()
                Row { id: bxRow; x: 6; spacing: 5; anchors.verticalCenter: parent.verticalCenter
                    Rectangle { visible: !!Backend.container.running || !!Backend.container.starting; width: 7; height: 7; radius: 4; anchors.verticalCenter: parent.verticalCenter; color: Backend.container.running ? win.addInk : Theme.t.text_secondary }
                    Label { font.pixelSize: 11; text: Backend.container.running ? "Container: " + Backend.container.title : Backend.container.starting ? "Container: starting…" : "Open in Container" } } }
            Pressable { objectName: "buildPill"; visible: win.bld.running || win.bld.errors + win.bld.warnings > 0; width: bpRow.width + 12; height: 24; radius: 12; color: hovered ? Theme.t.hover : "transparent"; onClicked: win.showBuild()
                Row { id: bpRow; x: 6; spacing: 5; anchors.verticalCenter: parent.verticalCenter
                    Rectangle { width: 7; height: 7; radius: 4; anchors.verticalCenter: parent.verticalCenter; color: win.bld.running ? win.modInk : win.bld.errors ? win.delInk : "#E3B341" }
                    Label { font.pixelSize: 11; text: win.bld.running ? "Building…" : win.bld.errors ? win.bld.errors + (win.bld.errors === 1 ? " build error" : " build errors") : win.bld.warnings + (win.bld.warnings === 1 ? " build warning" : " build warnings") } } }
            Row { objectName: "crumbs"; visible: !!win.tab && win.crumbs.length > 0; spacing: 2; anchors.verticalCenter: parent.verticalCenter
                Repeater { model: win.crumbs
                    Pressable { required property var modelData; required property int index; width: crL.width + 12; height: 22; radius: 11; color: hovered ? Theme.t.hover : "transparent"
                        onClicked: { var v = win.view(); if (v) v.goTo(modelData.line, 0) }
                        Label { id: crL; anchors.centerIn: parent; text: (index ? "› " : "") + modelData.name; font.pixelSize: 11; font.family: win.mono; secondary: index < win.crumbs.length - 1 } } } }
            Label { visible: Backend.busy !== ""; anchors.verticalCenter: parent.verticalCenter; text: Backend.busy + "…"; font.pixelSize: 11; secondary: true } }
        Row { visible: !!win.tab; anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter } spacing: 16
            Label { text: "Ln " + win.curLine + ", Col " + win.curCol; font.pixelSize: 11; secondary: true }
            Label { text: (Backend.status.indent || "") + (Backend.status.config ? " · .editorconfig" : ""); font.pixelSize: 11; secondary: true }
            Label { text: Backend.status.encoding || ""; font.pixelSize: 11; secondary: true }
            Label { text: Backend.status.eol || ""; font.pixelSize: 11; secondary: true }
            Pressable { width: wrapL.width + 10; height: 22; radius: 11; color: hovered ? Theme.t.hover : "transparent"; onClicked: Backend.setWrap(!Backend.wrap)
                Label { id: wrapL; anchors.centerIn: parent; text: Backend.wrap ? "Wrap" : "No wrap"; font.pixelSize: 11; secondary: true } }
            Row { spacing: 5
                Rectangle { width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter; color: win.tab ? win.langInk(win.tab.lang) : "transparent" }
                Label { text: (Backend.status.lang || "") + (Backend.status.server ? "  ·  " + Backend.status.server : ""); font.pixelSize: 11; font.weight: Font.DemiBold } } } }
}
