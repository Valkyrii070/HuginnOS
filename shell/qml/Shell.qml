import QtQuick
import QtQuick.Window
import org.kde.layershell 1.0 as LayerShell

// Session shell: every piece is its own Wayland layer-shell surface on KWin.
// The root is a plain object, not an Item: windows nested in an Item that has no window of its own never map.
QtObject {
    id: shell
    property string open: ""
    property string layoutsFor: ""         // Layouts (Super+Z): the window it's for
    property bool editWidgets: false       // the desktop's widgets being added, taken off and moved (Widgets.qml)
    property var deskMenuAt: null          // the desktop's menu, open: {x, y, screen} where it was right-clicked
    property bool settled: !arriving       // after the arrival from the sign-in screen, the desktop's pieces come in
    // every screen's wallpaper has been drawn (a frame with something real in it): signing in, the desktop is shown
    // from behind the sign-in screen once it's drawn (huginn_shell.py, ShellReady)
    property int wallsDrawn: 0
    readonly property bool drawnIn: wallsDrawn > 0 && wallsDrawn >= walls.count && (!arriving || arriveWin.drawn)
    onDrawnInChanged: if (drawnIn && typeof ShellReady !== "undefined" && ShellReady) ShellReady.drawn()
    property bool tabsOpen: false
    property string searchText: ""
    property var dockIsland: null              // the app whose island is open over the dock
    property real dockIslandX: 0
    // the live island, opened: after a moment of pointing at it (and while the pointer stays on it or the opened
    // island), or by itself while a call or an alarm rings
    readonly property int barH: Settings.barStyle === "islands" ? 44 : 30      // the top bar: islands want air round them
    readonly property bool liveTop: Settings.liveAt === "top" && Settings.barStyle === "islands"
    property bool liveOpen: false
    property string liveFocus: ""
    readonly property bool liveShown: (liveOpen || Live.ringing) && Live.active && shell.open === "" && shell.dockIsland === null   // (dockIsland alone is the AppIsland's id)
    property Timer liveShow: Timer { interval: 300; onTriggered: shell.liveOpen = true }
    property Timer liveHide: Timer { interval: 350; onTriggered: { shell.liveOpen = false; shell.liveFocus = "" } }
    function livePointer(inside) { if (inside) { liveHide.stop(); if (!liveOpen) liveShow.start() } else { liveShow.stop(); liveHide.restart() } }
    // an app's windows above its dock tile (pointing at it for a moment, or clicking an app with several)
    property var winApp: null
    property real winX: 0
    property bool winPinned: false
    property Timer winHide: Timer { interval: 300; onTriggered: if (!shell.winPinned) shell.winApp = null }
    function windowsWanted(app, x, show, pinned) {
        if (show) { winHide.stop(); winApp = app; winX = x; winPinned = pinned; dock.tipText = ""; return }
        winHide.restart()
    }
    // where the dock's tiles are on the screen, and how windows hide into them (Huginn's compositor draws that)
    property Timer dockReport: Timer {
        interval: 400; running: true; repeat: true
        property string last: ""
        onTriggered: {
            if (!Status.ownCompositor) { stop(); return }
            var sw = dockWin.screen ? dockWin.screen.width : 0, sh = dockWin.screen ? dockWin.screen.height : 0
            if (!sw) return
            var tiles = dock.tileRects(), out = {}, x0 = (sw - dock.width) / 2, y0 = sh - dockWin.full
            for (var k in tiles) out[k] = [x0 + tiles[k][0], y0 + tiles[k][1], tiles[k][2], tiles[k][3]]
            var text = JSON.stringify({ tiles: out, style: Theme.t.openMs > 0 ? Settings.hideStyle : "none", glow: Theme.t.glowA.toString(), gaps: Settings.snapGaps,
                                       dark: Theme.t.dark, frost: !Settings.reduceTransparency && !Settings.contrast,
                                       remember: Settings.rememberPlaces, vrr: Settings.adaptiveSync, x11sharp: Settings.sharpX11, tearing: Settings.allowTearing, gamemode: Settings.gameMode,
                                       keepSnapped: Settings.keepSnapped, spacesAllScreens: Settings.spacesAllScreens, glass: Settings.glass,
                                       liftApps: Settings.barStyle === "islands" ? Status.liftApps : [] })
            if (text !== last) { last = text; Status.dockLayout(text) }
        }
    }
    // notifications wait quietly while something has the whole screen or the screen is shared
    readonly property bool busyScreen: !!Live.privacy.screen || Status.windows.some(function (w) { return w.active && w.full })
    onBusyScreenChanged: Status.setBusyScreen(busyScreen)
    onOpenChanged: if (open === "cc") Status.notesSeen()
    // the app's menu, out of its name in the bar ("" the one menu; a group's name: the row-of-menus way)
    property string menuGroup: ""
    function appMenu(group) {
        if (shell.open === "menu" && menuGroup === group) { shell.open = ""; return }
        menuGroup = group
        if (group === "") Status.loadMenus()
        shell.open = "menu"
    }
    property Connections menuSource: Connections {
        target: Status
        function onActiveChanged() { if (topBar.rowMenus) Status.loadMenus() }
        function onTourWanted() { shell.startTour("first") }
    }
    // the Welcome tour (TourHost: full-screen pages, then the island on the desktop)
    property bool touring: false
    // With "Make room for windows" the dock reserves no strip of the screen, so the surfaces over the work area reach
    // the bottom edge: what they place just above the dock moves up by its height.
    readonly property int dockRoom: Settings.dockMakeRoom ? dockWin.full : 0
    function startTour(kind) { touring = true; open = ""; tour.start(kind || "first") }
    // the first time (or after a big update): once the desktop has come in, and not over the installer
    property Timer tourAuto: Timer {
        interval: 1600; repeat: true
        running: shell.settled && Tour.due !== "" && !shell.touring
        onTriggered: {
            if (Status.windows.some(function (w) { return /install/i.test(w.appId) || /installer/i.test(w.name) })) return
            stop(); shell.startTour(Tour.due)
        }
    }
    // ---------------------------------------------------------------- screens
    // The main screen (Settings › Displays › Make Main) has the top bar and the dock; Qt on its own would put them on
    // whichever screen the compositor named first.
    function screenNamed(name) { var l = Status.screenList; for (var i = 0; i < l.length; i++) if (l[i].name === name) return l[i]; return null }
    readonly property var mainScreen: screenNamed(Status.primaryScreen) || (Status.screenList.length ? Status.screenList[0] : null)
    // Settings › Desktop & Dock › "Moves to the screen you're using": resting the pointer at the bottom of another
    // screen brings the dock there (the compositor says when the pointer reaches a screen's bottom edge).
    property string dockScreenName: ""
    readonly property var dockScreen: ((Settings.dockFollows || Settings.dockEverywhere) && screenNamed(dockScreenName)) || mainScreen
    // Settings › Desktop & Dock › "On every screen": the other screens show the dock too. There is still one real dock
    // (its islands, the live island and the stacks open over it); the others are stand-ins, and the real one changes
    // places with a stand-in the moment the pointer reaches it. `dockShownOn` trails the real dock's screen by a
    // moment, so the stand-in stays until the real one has been drawn there.
    property string dockShownOn: dockScreen ? dockScreen.name : ""
    property Timer dockTrail: Timer { interval: 320; onTriggered: shell.dockShownOn = shell.dockScreen ? shell.dockScreen.name : "" }
    property Instantiator moreDocks: Instantiator {
        model: Settings.dockEverywhere && shell.settled ? Status.screenList.filter(function (sc) { return sc.name !== shell.dockShownOn }) : []
        delegate: Window {
            id: standIn
            required property var modelData
            visible: true; width: standDock.width + 40; height: dockWin.full; color: "transparent"
            LayerShell.Window.screen: modelData
            LayerShell.Window.wantsToBeOnActiveScreen: false
            LayerShell.Window.scope: "huginn-dock-more"
            LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
            LayerShell.Window.layer: LayerShell.Window.LayerTop
            LayerShell.Window.anchors: LayerShell.Window.AnchorBottom
            LayerShell.Window.exclusionZone: Settings.dockMakeRoom ? 0 : dockWin.full
            Dock { id: standDock; inlineTips: false; anchors { horizontalCenter: parent.horizontalCenter; top: parent.top }
                activate: function (app) { return Status.activateApp(app) } }
            HoverHandler { onHoveredChanged: if (hovered) shell.dockScreenName = standIn.modelData.name }
        }
    }
    property string edgeAt: ""
    property Timer edgeRest: Timer { interval: 450; onTriggered: if (Settings.dockFollows && shell.edgeAt !== "") shell.dockScreenName = shell.edgeAt }
    function pointerAtEdge(name) {
        edgeAt = name
        var dockOn = dockWin.placedOn || (dockWin.screen ? dockWin.screen.name : "")
        if (name !== "" && name !== dockOn && Settings.dockFollows && Status.screenList.length > 1) edgeRest.restart(); else edgeRest.stop()
    }
    // A layer surface stays on the screen it was made on: to move one, it's made again on the other.
    function moveTo(win, screen) {
        if (!screen || win.placedOn === screen.name) return
        win.placedOn = screen.name
        win.LayerShell.Window.screen = screen
        if (win.visible) { win.visible = false; Qt.callLater(function () { win.visible = true }) }
    }
    onMainScreenChanged: moveTo(topBarWin, mainScreen)
    onDockScreenChanged: { moveTo(dockWin, dockScreen); moveTo(launcherWin, dockScreen); dockTrail.restart() }
    // the frame-time display (Super+Alt+F, Settings › Displays): each screen's frames over the last second
    property var frameStats: ({})
    property Timer frameTick: Timer {
        interval: 500; repeat: true; running: Settings.frameTimes; triggeredOnStart: true
        onTriggered: { var m = {}; try { JSON.parse(Status.frameStats()).forEach(function (r) { m[r.screen] = r }) } catch (e) {} shell.frameStats = m }
    }
    property Instantiator frameIslands: Instantiator {
        model: Settings.frameTimes ? Status.screenList : []
        delegate: Window {
            required property var modelData
            readonly property var st: shell.frameStats[modelData.name] || null
            visible: true; width: fcol.width + 40; height: fcol.height + 56; color: "transparent"     // (room above it for the top bar)
            flags: Qt.WindowTransparentForInput
            LayerShell.Window.screen: modelData
            LayerShell.Window.wantsToBeOnActiveScreen: false
            LayerShell.Window.scope: "huginn-frames"
            LayerShell.Window.layer: LayerShell.Window.LayerOverlay
            LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorRight
            LayerShell.Window.exclusionZone: -1
            LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
            Rectangle {
                x: 0; y: 38; width: parent.width - 12; height: parent.height - 38; radius: 12; color: Qt.rgba(0.04, 0.05, 0.07, 0.82); border.width: 1
                border.color: st && st.late > 0 ? "#E5484D" : Qt.rgba(1, 1, 1, 0.14)
                Column {
                    id: fcol; x: 14; y: 9; spacing: 2
                    Text { text: modelData.name + (st && st.hz ? "  ·  " + Math.round(st.hz) + " Hz" : ""); color: "#B9C2CC"; font.pixelSize: 11; font.family: Theme.t.font }
                    Text { text: !st || st.fps === 0 ? "Resting: nothing new to draw" : st.fps + " frames a second"
                           color: "#F5F7FA"; font.pixelSize: 15; font.weight: Font.DemiBold; font.family: Theme.t.font }
                    Text { visible: !!st && st.fps > 1; text: st ? "Between frames " + st.frameMs.toFixed(1) + " ms, longest " + st.worstMs.toFixed(1) + " ms" : ""
                           color: "#D5DAE0"; font.pixelSize: 11; font.family: Theme.t.font }
                    Text { visible: !!st && st.fps > 0; text: st ? "Drawing " + st.drawMs.toFixed(2) + " ms, longest " + st.drawWorstMs.toFixed(2) + " ms" : ""
                           color: "#D5DAE0"; font.pixelSize: 11; font.family: Theme.t.font }
                    Text { visible: !!st && st.late > 0; text: st ? st.late + (st.late === 1 ? " frame came late" : " frames came late") : ""
                           color: "#FF8A8D"; font.pixelSize: 11; font.family: Theme.t.font }
                }
            }
        }
    }
    // the game stats overlay (Super+Alt+G, Settings › Desktop & Dock): the game's own frame rate (its window's frames,
    // counted by the compositor), the graphics card and processor, top left of the screen the game fills (else the
    // screen of the window in front). Takes no clicks; read once a second only while it shows.
    property var gameStats: ({})
    // a game has the screen: the shell's JavaScript lets go of its garbage too (huginn_system.py: trimMemory)
    property Connections gameRoom: Connections { target: Status; function onGamePlayingChanged() { if (Status.gamePlaying) gc() } }
    property string gameBarOn: ""               // the screen the game bar opened on
    property Timer gameTick: Timer {
        interval: 1000; repeat: true; running: Settings.gameStats || shell.open === "gamebar"; triggeredOnStart: true
        onTriggered: { try { shell.gameStats = JSON.parse(Status.gameStats()) } catch (e) { shell.gameStats = ({}) } }
    }
    function gameScreen() {     // where the overlay goes: a screen a window fills, else the one with the window in front
        var w = shell.gameStats.windows || []
        for (var i = 0; i < w.length; i++) if (w[i].full) return w[i].screen
        for (var k = 0; k < w.length; k++) if (w[k].app) return w[k].screen
        return shell.mainScreen ? shell.mainScreen.name : ""
    }
    property Instantiator gameIslands: Instantiator {
        model: Settings.gameStats ? Status.screenList : []
        delegate: Window {
            id: gwin
            required property var modelData
            readonly property var win: (shell.gameStats.windows || []).filter(function (r) { return r.screen === gwin.modelData.name })[0] || null
            readonly property var gpu: shell.gameStats.gpu || ({})
            readonly property var cpu: shell.gameStats.cpu || ({})
            readonly property bool here: shell.gameScreen() === modelData.name
            function hot(t) { return t >= 90 ? "#FF8A8D" : t >= 80 ? "#F5C46B" : "#D5DAE0" }
            visible: here; width: gcol.width + 36; height: gcol.height + 30 + (win && win.full ? 0 : 38); color: "transparent"
            flags: Qt.WindowTransparentForInput
            LayerShell.Window.screen: modelData
            LayerShell.Window.wantsToBeOnActiveScreen: false
            LayerShell.Window.scope: "huginn-gamestats"
            LayerShell.Window.layer: LayerShell.Window.LayerOverlay
            LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft
            LayerShell.Window.exclusionZone: -1
            LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
            Rectangle {
                x: 12; y: gwin.win && gwin.win.full ? 12 : 50; width: gcol.width + 24; height: gcol.height + 16; radius: 12
                color: Qt.rgba(0.04, 0.05, 0.07, 0.78); border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.12)
                Column {
                    id: gcol; x: 12; y: 8; spacing: 3
                    Text { visible: !!gwin.win && !!gwin.win.app; text: gwin.win ? gwin.win.app : ""; color: "#B9C2CC"; font.pixelSize: 11; font.family: Theme.t.font
                        width: Math.min(implicitWidth, 260); elide: Text.ElideRight }
                    Row { spacing: 8
                        Text { text: gwin.win && gwin.win.fps > 0 ? gwin.win.fps : "\u2013"; color: "#F5F7FA"; font.pixelSize: 26; font.weight: Font.DemiBold; font.family: Theme.t.font }
                        Column { anchors.verticalCenter: parent.verticalCenter
                            Text { text: "frames a second"; color: "#B9C2CC"; font.pixelSize: 10; font.family: Theme.t.font }
                            Text { visible: !!gwin.win && gwin.win.fps > 1; text: gwin.win ? gwin.win.frameMs.toFixed(1) + " ms, longest " + gwin.win.worstMs.toFixed(1) : ""
                                color: gwin.win && gwin.win.worstMs > 3 * Math.max(1, gwin.win.frameMs) ? "#F5C46B" : "#D5DAE0"; font.pixelSize: 10; font.family: Theme.t.font } } }
                    Text { visible: gwin.gpu.load !== undefined || gwin.gpu.temp !== undefined; color: "#D5DAE0"; font.pixelSize: 12; font.family: Theme.t.font; textFormat: Text.StyledText
                        text: "<b>GPU</b>  " + [gwin.gpu.load !== undefined ? gwin.gpu.load + "%" : "",
                                                gwin.gpu.temp !== undefined ? "<font color='" + gwin.hot(gwin.gpu.hot || gwin.gpu.temp) + "'>" + gwin.gpu.temp + "\u00b0C" + (gwin.gpu.hot ? " (hot spot " + gwin.gpu.hot + ")" : "") + "</font>" : "",
                                                gwin.gpu.ghz ? gwin.gpu.ghz.toFixed(2) + " GHz" : "", gwin.gpu.watts ? gwin.gpu.watts + " W" : ""].filter(Boolean).join("  \u00b7  ") }
                    Text { visible: gwin.gpu.memTotal !== undefined; color: "#D5DAE0"; font.pixelSize: 12; font.family: Theme.t.font; textFormat: Text.StyledText
                        text: "<b>VRAM</b>  " + gwin.gpu.memUsed + " of " + gwin.gpu.memTotal + " GB" + (gwin.gpu.fan !== undefined ? "  \u00b7  fan " + gwin.gpu.fan + " rpm" : "") }
                    Text { visible: gwin.cpu.load !== undefined || gwin.cpu.temp !== undefined; color: "#D5DAE0"; font.pixelSize: 12; font.family: Theme.t.font; textFormat: Text.StyledText
                        text: "<b>CPU</b>  " + [gwin.cpu.load !== undefined ? gwin.cpu.load + "%" : "",
                                                gwin.cpu.temp !== undefined ? "<font color='" + gwin.hot(gwin.cpu.temp) + "'>" + gwin.cpu.temp + "\u00b0C</font>" : "",
                                                gwin.cpu.memTotal ? "RAM " + gwin.cpu.memUsed + " of " + gwin.cpu.memTotal + " GB" : ""].filter(Boolean).join("  \u00b7  ") }
                }
            }
        }
    }
    // Settings › Displays › Identify: each screen's name over it for a few seconds
    property var identify: ({})
    property Timer identifyEnd: Timer { interval: 3500; onTriggered: shell.identify = ({}) }
    property Instantiator identities: Instantiator {
        model: Object.keys(shell.identify).length ? Status.screenList : []
        delegate: Window {
            required property var modelData
            readonly property var info: shell.identify[modelData.name] || { label: modelData.name }
            visible: true; width: idCard.width + 40; height: idCard.height + 40; color: "transparent"
            flags: Qt.WindowTransparentForInput
            LayerShell.Window.screen: modelData
            LayerShell.Window.wantsToBeOnActiveScreen: false
            LayerShell.Window.scope: "huginn-identify"
            LayerShell.Window.layer: LayerShell.Window.LayerOverlay
            LayerShell.Window.anchors: LayerShell.Window.AnchorNone
            LayerShell.Window.exclusionZone: -1
            LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
            Rectangle {
                id: idCard; anchors.centerIn: parent
                width: Math.max(260, idCol.width + 64); height: idCol.height + 44; radius: 28
                color: Qt.rgba(0.05, 0.06, 0.08, 0.82); border.width: 2; border.color: Theme.t.accent
                Column {
                    id: idCol; anchors.centerIn: parent; spacing: 6
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: info.label; color: "#F5F7FA"; font.pixelSize: 40; font.weight: Font.DemiBold; font.family: Theme.t.font }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: (info.size || "") + (modelData.name === Status.primaryScreen ? (info.size ? "  ·  " : "") + "Main screen" : ""); visible: text !== ""; color: "#B9C2CC"; font.pixelSize: 16; font.family: Theme.t.font }
                }
            }
        }
    }
    // A window on the space in view covers (nearly) all of this screen: its wallpaper can rest (it's hidden anyway).
    function filled(sc) {
        if (!sc) return false
        var g = sc.geometry, cur = (Status.spaces || {}).current || 0                        // (a QScreen: its geometry)
        if (!g) return false
        var sx = g.x, sy = g.y, sw = g.width, sh = g.height
        return (Status.windows || []).some(function (w) {
            if (w.minimised || (w.space || 0) !== cur) return false
            var ix = Math.min(w.x + w.w, sx + sw) - Math.max(w.x, sx), iy = Math.min(w.y + w.h, sy + sh) - Math.max(w.y, sy)
            return ix > 0 && iy > 0 && ix * iy >= 0.88 * sw * sh })
    }
    function frontWindow() { var a = Status.windows.filter(function (w) { return w.active && !w.minimised }); return a.length ? a[0] : null }
    // a stack opened over its dock tile
    property string stackFolder: ""
    property real stackX: 0
    property bool stackMenu: false
    property Timer tabsShow: Timer { interval: 350; onTriggered: { Tabs.refresh(); shell.tabsOpen = true } }
    property Timer tabsHide: Timer { interval: 350; onTriggered: shell.tabsOpen = false }
    property Connections keys: Connections {
        target: Status
        function onLauncherWanted() { shell.open = shell.open === "launcher" ? "" : "launcher" }
        function onSearchWanted(text) { shell.searchText = text; shell.open = shell.open === "search" && !text ? "" : "search" }
        function onKeyWanted(what) {
            if (what === "today") shell.open = shell.open === "today" ? "" : "today"
            else if (what === "clipboard") shell.open = shell.open === "clipboard" ? "" : "clipboard"
            else if (what === "emoji") shell.open = shell.open === "emoji" ? "" : "emoji"
            else if (what === "layouts") {    // for the window in front now (it stays the one, whatever takes focus)
                if (shell.open === "layouts") { shell.open = ""; return }
                var ws = Status.windows || [], front = ""
                for (var wi = 0; wi < ws.length; wi++) if (ws[wi].active && !ws[wi].minimised) front = ws[wi].id
                shell.layoutsFor = front; shell.open = "layouts" }
            else if (what === "menu") shell.appMenu("")
            else if (what === "saver") shell.saverOn = Settings.saver !== "off"
            else if (what === "saver-now") shell.saverOn = true
            else if (what === "saver-off") shell.saverOn = false
            else if (what === "keys-show") { if (Settings.keySheet && !shell.touring) { shell.keysShown = true; keysLonger.restart() } }
            else if (what === "keys-hide") shell.keysShown = false
            else if (what === "captions") Settings.set("captions", Settings.captions ? "false" : "true")
            else if (what.indexOf("run:") === 0) shell.runKey(what.slice(4))
            else if (what.indexOf("edge:") === 0) shell.pointerAtEdge(what.slice(5))
            else if (what === "frames") Settings.set("frameTimes", Settings.frameTimes ? "false" : "true")
            else if (what === "gamestats") Settings.set("gameStats", Settings.gameStats ? "false" : "true")
            else if (what === "gamebar") {      // on the screen the game fills: read where that is first
                if (shell.open !== "gamebar") { try { shell.gameStats = JSON.parse(Status.gameStats()) } catch (e) {} shell.gameBarOn = shell.gameScreen() }
                shell.open = shell.open === "gamebar" ? "" : "gamebar" }
            else if (what === "layout") Status.readLayouts()
            else if (what === "reader") Status.toggleReader()
            else if (what === "bell") Status.playEffect("bell")     // an app's bell (the compositor flashes the screen itself, if Settings says)
            else if (what.indexOf("identify:") === 0) { try { shell.identify = JSON.parse(what.slice(9)) } catch (e) { shell.identify = ({}) } identifyEnd.restart() }
        }
    }
    // A shortcut that opens something (Settings › Keyboard shortcuts): "open:files" (one of Huginn's apps by name),
    // "app:<desktop id>" (any app), or a command of the person's own.
    function runKey(what) {
        var id = what.indexOf("open:") === 0 ? "huginn-" + what.slice(5) : what.indexOf("app:") === 0 ? what.slice(4).replace(/\.desktop$/, "") : ""
        if (id) {
            var app = Apps.all.filter(function (a) { return a.id === id })[0]
            if (app && app.exec) Apps.launch(app.exec)
            return
        }
        Apps.launch(what)
    }
    // The wallpaper, on every screen (screens plugged in later get one too); the widgets on the main screen, with the
    // bar and the dock.
    property Instantiator walls: Instantiator {
        model: Status.screenList
        delegate: Window {
            id: wall
            required property var modelData
            readonly property bool main: modelData.name === Status.primaryScreen || Status.primaryScreen === ""
            visible: true; color: "black"
            property bool drawn: false
            onFrameSwapped: if (!drawn && paperHere.drawn) { drawn = true; shell.wallsDrawn += 1 }
            LayerShell.Window.screen: modelData                 // each on its own screen (else they all land on one)
            LayerShell.Window.wantsToBeOnActiveScreen: false
            LayerShell.Window.scope: "huginn-wallpaper"
            LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
            LayerShell.Window.layer: LayerShell.Window.LayerBackground
            LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
            LayerShell.Window.exclusionZone: -1
            Wallpaper { id: paperHere; anchors.fill: parent; covered: shell.filled(wall.modelData) }
            // right-click the desktop: a small menu (Edit Widgets, the wallpaper, the desktop's settings), over everything
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.RightButton
                onClicked: function (m) { shell.deskMenuAt = { x: m.x, y: m.y, screen: wall.modelData } } }
            // the Desktop folder's files, on the main screen (Settings › Desktop & Dock)
            Loader { anchors.fill: parent; active: wall.main && Settings.desktopFiles
                opacity: shell.settled ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } }
                sourceComponent: DesktopIcons { onMenuWanted: function (file, x, y) { shell.deskMenuAt = { x: x, y: y, screen: wall.modelData, file: file } } } }
            Widgets { visible: wall.main; x: 22; y: 52; opacity: shell.settled ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } }
                area: wall.contentItem; screenName: wall.modelData.name
                editing: shell.editWidgets; onDoneEditing: shell.editWidgets = false }
            // the widgets dragged out of the column, each where it was left on this screen (one whose screen is gone
            // waits on the main one)
            Repeater {
                model: (Settings.widgets || []).filter(function (k) { var p = (Settings.widgetPlaces || {})[k]
                    return !!p && (p.s === wall.modelData.name || (wall.main && !shell.screenNamed(p.s))) })
                Widgets { required property string modelData
                    readonly property var at: (Settings.widgetPlaces || {})[modelData] || ({ x: 0.5, y: 0.5 })
                    only: [modelData]; area: wall.contentItem; screenName: wall.modelData.name
                    x: Math.max(8, Math.min(wall.width - width - 8, at.x * wall.width)); y: Math.max(38, Math.min(wall.height - height - 8, at.y * wall.height))
                    opacity: shell.settled ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } }
                    editing: shell.editWidgets; onDoneEditing: shell.editWidgets = false } }
        }
    }
    // Settings › Desktop & Dock › Top bar › "On every screen": the others get a bar of their own. Its buttons open the
    // same panels, on the screen the pointer is on (the compositor puts a panel with no screen of its own there).
    // the Overview on the other screens: their windows' chips (the compositor spreads each screen's windows on it)
    property Instantiator moreOverviews: Instantiator {
        model: overview.visible && Status.screenList.length > 1 ? Status.screenList.filter(function (sc) { return sc.name !== (Status.overview.screen || "") }) : []
        delegate: Window {
            required property var modelData
            visible: true; color: "transparent"
            LayerShell.Window.screen: modelData
            LayerShell.Window.wantsToBeOnActiveScreen: false
            LayerShell.Window.scope: "huginn-overview-more"
            LayerShell.Window.layer: LayerShell.Window.LayerOverlay
            LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
            LayerShell.Window.exclusionZone: -1
            LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
            OverviewOverlay { anchors.fill: parent; main: false; screenName: modelData.name; query: overview.query }
        }
    }
    property Instantiator moreBars: Instantiator {
        model: Settings.barEverywhere && shell.mainScreen ? Status.screenList.filter(function (sc) { return sc.name !== shell.mainScreen.name }) : []
        delegate: Window {
            required property var modelData
            visible: true; height: shell.barH; color: "transparent"
            LayerShell.Window.screen: modelData
            LayerShell.Window.wantsToBeOnActiveScreen: false
            LayerShell.Window.scope: "huginn-topbar-more"
            LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
            LayerShell.Window.layer: LayerShell.Window.LayerTop
            LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
            LayerShell.Window.exclusionZone: shell.barH
            TopBar { id: moreBar; width: parent.width; appName: Status.active.name || "Huginn"; solid: Status.active.maximized
                function fit() { if (islands) Status.setInputRects(moreBar.Window.window, rects); else Status.setInputRegion(moreBar.Window.window, 0, 0, 0, 0) }
                onRectsChanged: fit(); onIslandsChanged: fit(); Component.onCompleted: fit()
                onWindowAction: function (action) { Status.windowAction(action) }
                opacity: shell.settled ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
                onControlCentre: shell.open = shell.open === "cc" ? "" : "cc"; onLauncher: shell.open = shell.open === "launcher" ? "" : "launcher"
                onSearch: shell.open = shell.open === "search" ? "" : "search"
                todayOpen: shell.open === "today"; onToday: shell.open = shell.open === "today" ? "" : "today"
                menuOpen: false; onAppMenu: function (group) { shell.appMenu(group) } }
        }
    }
    property list<QtObject> surfaces: [
    Window {   // arriving from the sign-in screen: its island carries on for a moment, then fades (takes no input)
        id: arriveWin
        objectName: "arrival"
        visible: arrival.visible; color: "transparent"
        property bool drawn: false
        onFrameSwapped: if (!drawn) drawn = true
        flags: Qt.WindowTransparentForInput
        LayerShell.Window.scope: "huginn-arrival"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        Arrival { id: arrival; anchors.fill: parent; playing: arriving && onScreen.shown; opacity: arriving ? 1 : 0; onLeaving: shell.settled = true }
    },
    Window {   // top bar
        id: topBarWin
        // Grows while the dropdown menu list is open; the reserved strip (exclusionZone) stays 30 px.
        visible: true; height: shell.barH; color: "transparent"
        property string placedOn: ""
        LayerShell.Window.screen: shell.mainScreen
        Component.onCompleted: placedOn = shell.mainScreen ? shell.mainScreen.name : ""
        LayerShell.Window.scope: "huginn-topbar"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: shell.barH
        TopBar { id: topBar; width: parent.width; appName: Status.active.name || "Huginn"; solid: Status.active.maximized
            onWindowAction: function (action) { Status.windowAction(action) }
            opacity: shell.settled ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } } onControlCentre: shell.open = shell.open === "cc" ? "" : "cc"; onLauncher: shell.open = shell.open === "launcher" ? "" : "launcher"
            onSearch: shell.open = shell.open === "search" ? "" : "search"
            todayOpen: shell.open === "today"; onToday: shell.open = shell.open === "today" ? "" : "today"
            menuOpen: shell.open === "menu"; menuGroup: shell.menuGroup
            onAppMenu: function (group) { shell.appMenu(group) }
            live: true
            onLiveHover: function (inside) { shell.livePointer(inside) }
            onLiveFocus: function (id) { shell.liveFocus = id; shell.liveHide.stop(); shell.liveOpen = true }
            onLiveOpen: function (app) { dock.openApp(app) }
            onLiveIsland: function (name) { var app = dock.appNamed(name); if (app) dock.islandWanted(app, dock.restWidth / 2) }
            // islands: only they take the pointer; and a filled app of Huginn's own is told where they end
            function fit() { if (islands) Status.setInputRects(topBarWin, rects); else Status.setInputRegion(topBarWin, 0, 0, 0, 0) }
            onRectsChanged: fit(); onIslandsChanged: fit(); Component.onCompleted: fit()
            readonly property string insets: JSON.stringify({ h: islands ? shell.barH : 0, ih: islandH, left: Math.round(leftEnd), right: Math.round(rightStart),
                screens: Settings.barEverywhere ? Status.screenList.map(function (sc) { return sc.name }) : (shell.mainScreen ? [shell.mainScreen.name] : []) })
            onInsetsChanged: Status.setBarInsets(insets) }
    },
    Window {   // dock. Wider than the dock, so the live island can grow and shrink without the surface changing size
        id: dockWin
        visible: true; color: "transparent"
        // (never wider than the screen: a surface that is gets cut at the right and its middle is no longer the screen's)
        width: Math.min(dockWin.screen ? dockWin.screen.width : 100000, Math.max(dock.width, dock.restWidth + 780))
        property string placedOn: ""
        LayerShell.Window.screen: shell.dockScreen
        Component.onCompleted: placedOn = shell.dockScreen ? shell.dockScreen.name : ""
        readonly property int full: dock.tile + 34
        // Settings › Desktop & Dock › "Make room for windows": while a window covers the dock's place (filled, full
        // screen, or just big), the dock slides down out of the way and its surface shrinks to a strip along the
        // bottom edge; pointing there brings it back over the window. Nothing it opened (an app's island, its
        // windows, a stack, the start menu) is left without it.
        readonly property bool covered: {
            var sh = dockWin.screen ? dockWin.screen.height : 0, sw = dockWin.screen ? dockWin.screen.width : 0
            if (!sh) return false
            var g = shell.dockScreen ? shell.dockScreen.geometry : null, gx = g ? g.x : 0, gy = g ? g.y : 0
            var top = gy + sh - full, left = gx + (sw - dock.restWidth) / 2, right = left + dock.restWidth, cur = Status.spaces.current || 0
            return Status.windows.some(function (w) {
                return !w.minimised && (w.space || 0) === cur && w.w > 0 && (w.full || (w.y + w.h > top + 6 && w.x < right && w.x + w.w > left))
            })
        }
        property bool peek: false
        readonly property bool busy: shell.open === "launcher" || shell.dockIsland !== null || shell.winApp !== null || shell.stackFolder !== ""
                                     || (shell.liveShown && !shell.liveTop) || shell.tabsOpen || shell.touring || !shell.settled
        readonly property bool away: Settings.dockMakeRoom && covered && !peek && !busy
        property bool shrunk: false
        onAwayChanged: if (away) shrink.restart(); else { shrink.stop(); shrunk = false }
        Timer { id: shrink; interval: Theme.t.openMs > 0 ? 300 : 0; onTriggered: dockWin.shrunk = true }
        HoverHandler { id: dockHover; onHoveredChanged: if (hovered) { unpeek.stop(); dockWin.peek = true } else unpeek.restart() }
        Timer { id: unpeek; interval: 700; onTriggered: dockWin.peek = false }
        height: shrunk ? 3 : full
        LayerShell.Window.scope: "huginn-dock"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorBottom
        LayerShell.Window.exclusionZone: Settings.dockMakeRoom ? 0 : full     // making room: windows may use the whole height
        Dock {
            id: dock; inlineTips: false; anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: !shell.settled ? 24 : dockWin.away ? dockWin.full + 12 : 0 }
            opacity: shell.settled ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
            Behavior on anchors.topMargin { NumberAnimation { duration: shell.settled ? Theme.t.openMs > 0 ? 280 : 0 : 550; easing.type: Easing.OutCubic } }
            onLauncher: shell.open = shell.open === "launcher" ? "" : "launcher"
            onControlCentre: shell.open = shell.open === "cc" ? "" : "cc"
            activate: function (app) { return Status.activateApp(app) }   // a running app's window comes forward (KWin)
            menuOpen: shell.open === "launcher"
            onIslandWanted: function (app, x) { shell.open = ""; shell.dockIslandX = x; shell.dockIsland = app }
            onTabsWanted: function (show) { if (show) { shell.tabsHide.stop(); shell.tabsShow.start() } else { shell.tabsShow.stop(); shell.tabsHide.restart() } }
            onLiveHover: function (inside) { shell.livePointer(inside) }
            onLiveFocus: function (id) { shell.liveFocus = id; shell.liveHide.stop(); shell.liveOpen = true }
            onWindowsWanted: function (app, x, show, pinned) { shell.windowsWanted(app, x, show, pinned) }
            onStackWanted: function (folder, x, menu) { shell.open = ""; shell.winApp = null; shell.stackMenu = menu; shell.stackX = x; shell.stackFolder = shell.stackFolder === folder && !menu ? "" : folder }
        }
    },
    Window {   // the live island, opened: just above the dock, lined up with the island's right edge; or, when the
        id: liveWin   // island is kept in the top bar, hanging under it, centred on it
        readonly property bool top: shell.liveTop
        visible: shell.liveShown || livePanel.visible; width: top ? topBarWin.width : dockWin.width
        height: livePanel.height + 60 + (top ? 0 : shell.dockRoom); color: "transparent"
        LayerShell.Window.scope: "huginn-live"
        LayerShell.Window.screen: top ? shell.mainScreen : shell.dockScreen
        // When the dock makes room it keeps no strip of its own, so this reaches down over it: the panel sits above
        // the dock as it always did, and the strip over the dock leaves the pointer to the dock
        function fitInput() {
            if (top) Status.setInputRegion(liveWin, livePanel.x, 0, livePanel.width, livePanel.height + 12)   // the rest stays the windows'
            else Status.setInputRegion(liveWin, 0, 0, width, height - shell.dockRoom)
        }
        onHeightChanged: fitInput(); onWidthChanged: fitInput(); onVisibleChanged: if (visible) fitInput(); onTopChanged: fitInput()
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: top ? LayerShell.Window.AnchorTop : LayerShell.Window.AnchorBottom
        LivePanel {
            id: livePanel
            shown: shell.liveShown; focusId: shell.liveFocus; fromTop: liveWin.top
            readonly property real dockX: (liveWin.width - dock.width) / 2
            x: liveWin.top ? Math.max(8, Math.min(liveWin.width - width - 8, topBar.liveCentre - width / 2))
                           : Math.max(8, Math.min(liveWin.width - width - 8, dockX + dock.liveRight - width))
            y: liveWin.top ? 6 : liveWin.height - shell.dockRoom - height - 10
            originX: liveWin.top ? topBar.liveCentre - x : dockX + dock.liveCentre - x
            onXChanged: liveWin.fitInput()
            onPointer: function (inside) { shell.livePointer(inside) }
            onOpenWanted: function (app) { dock.openApp(app) }
        }
    },
    Window {   // an app's windows, above its tile
        id: winsWin
        visible: shell.winApp !== null; width: dockWin.width; height: appWins.height + 12 + shell.dockRoom; color: "transparent"
        LayerShell.Window.scope: "huginn-app-windows"
        LayerShell.Window.screen: shell.dockScreen
        function fitInput() { Status.setInputRegion(winsWin, 0, 0, width, height - shell.dockRoom) }    // (as the live panel's)
        onHeightChanged: fitInput(); onWidthChanged: fitInput(); onVisibleChanged: if (visible) fitInput()
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorBottom
        AppWindows {
            id: appWins
            app: shell.winApp
            x: Math.max(8, Math.min(winsWin.width - width - 8, (winsWin.width - dock.width) / 2 + shell.winX - width / 2)); y: 4
            onHoverChanged: function (inside) { if (inside) shell.winHide.stop(); else shell.winHide.restart() }
            onPicked: { shell.winPinned = false; shell.winApp = null }
            onNewWindow: { var a = shell.winApp; shell.winPinned = false; shell.winApp = null; if (a) dock.start(a) }
        }
        // a click beside a shown-by-click island closes it
        Connections { target: Status; function onActiveChanged() { if (shell.winPinned) { shell.winPinned = false; shell.winApp = null } } }
    },
    Window {   // a stack, opened: over the work area, so a click beside it closes it
        id: stackWin
        visible: shell.stackFolder !== ""; color: "transparent"
        LayerShell.Window.scope: "huginn-stack"
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.keyboardInteractivity: shell.stackFolder !== "" ? LayerShell.Window.KeyboardInteractivityOnDemand : LayerShell.Window.KeyboardInteractivityNone
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: shell.stackFolder = "" }
        StackIsland {
            id: stackIsland
            folder: shell.stackFolder; startWithMenu: shell.stackMenu
            visible: shell.stackFolder !== ""; focus: true
            x: Math.max(8, Math.min(stackWin.width - width - 8, (stackWin.width - dock.width) / 2 + shell.stackX - width / 2))
            y: stackWin.height - shell.dockRoom - height - 8
            onDone: shell.stackFolder = ""
        }
    },
    Window {   // a file that just landed in a stack flies into it, from the window in front (takes no input)
        id: flightWin
        visible: flight.running; color: "transparent"
        flags: Qt.WindowTransparentForInput
        LayerShell.Window.scope: "huginn-stack-flight"
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        property point from: Qt.point(0, 0)
        property point to: Qt.point(0, 0)
        property real t: 0
        property string folder: ""
        FileArt {
            id: flyer
            size: 46 - 10 * flightWin.t
            // a curve up and over, then down into the pile
            readonly property point mid: Qt.point((flightWin.from.x + flightWin.to.x) / 2, Math.min(flightWin.from.y, flightWin.to.y) - 160)
            x: (1 - flightWin.t) * (1 - flightWin.t) * flightWin.from.x + 2 * (1 - flightWin.t) * flightWin.t * mid.x + flightWin.t * flightWin.t * flightWin.to.x - width / 2
            y: (1 - flightWin.t) * (1 - flightWin.t) * flightWin.from.y + 2 * (1 - flightWin.t) * flightWin.t * mid.y + flightWin.t * flightWin.t * flightWin.to.y - height / 2
            rotation: 18 * Math.sin(flightWin.t * Math.PI)
        }
        NumberAnimation {
            id: flight; target: flightWin; property: "t"; from: 0; to: 1; duration: 640; easing.type: Easing.InOutCubic
            onFinished: dock.stackLanded(flightWin.folder)
        }
        Connections {
            target: Stacks
            function onLanded(folder, name, kind) {
                var st = Stacks.stacks.filter(function (s) { return s.folder === folder })[0]
                if (!st || Theme.t.openMs === 0 || !shell.settled) { dock.stackLanded(folder); return }
                flyer.file = st.items.filter(function (i) { return i.name === name })[0] || { kind: kind }
                var w = Status.windows.filter(function (w) { return w.active && !w.minimised })[0]
                var sw = flightWin.screen ? flightWin.screen.width : 1280, sh = flightWin.screen ? flightWin.screen.height : 800
                flightWin.from = w && w.w > 0 ? Qt.point(w.x + w.w / 2, w.y + w.h / 2) : Qt.point(sw / 2, sh / 2)
                flightWin.to = Qt.point((sw - dock.width) / 2 + dock.stackX(folder), sh - dockWin.full + 32)
                flightWin.folder = folder
                flight.restart()
            }
        }
    },
    Window {   // the name of the dock item under the pointer; never takes clicks
        visible: dock.tipText !== "" && shell.winApp === null; width: dock.width; height: 34 + shell.dockRoom; color: "transparent"
        flags: Qt.WindowTransparentForInput
        LayerShell.Window.scope: "huginn-dock-tip"
        LayerShell.Window.screen: shell.dockScreen
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorBottom
        Glass {
            popup: true; radius: Theme.t.radiusControl; width: tipLabel.width + 16; height: 26
            x: Math.max(0, Math.min(parent.width - width, dock.tipX - width / 2)); y: 2
            Label { id: tipLabel; anchors.centerIn: parent; text: dock.tipText; font.pixelSize: 12 }
        }
    },
    Window {   // Huginn's tab stack. As wide as the dock and centred like it, so dock x positions line up.
        id: tabsWin
        visible: shell.tabsOpen; width: dock.width; height: 620 + shell.dockRoom; color: "transparent"
        LayerShell.Window.scope: "huginn-tabs"
        LayerShell.Window.screen: shell.dockScreen
        function fitInput() { Status.setInputRegion(tabsWin, 0, 0, width, height - shell.dockRoom) }    // (as the live panel's)
        onHeightChanged: fitInput(); onWidthChanged: fitInput(); onVisibleChanged: if (visible) fitInput()
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorBottom
        MouseArea { anchors.fill: parent; onClicked: shell.tabsOpen = false }
        TabStack {
            x: Math.max(0, Math.min(parent.width - width, dock.tabsX - width / 2))
            anchors { bottom: parent.bottom; bottomMargin: 6 + shell.dockRoom }
            onHoverChanged: function (inside) { if (inside) shell.tabsHide.stop(); else shell.tabsHide.restart() }
            onPicked: shell.tabsOpen = false
        }
    },
    Window {   // Today: under the bar (the work area, so a click beside its islands closes it)
        id: todayWin
        Component.onCompleted: Status.glassWindow(todayWin, "huginn-today")      // only its glass is blurred behind it
        visible: shell.open === "today" || todayIslands.visible; color: "transparent"
        LayerShell.Window.scope: "huginn-today"
        LayerShell.Window.wantsToBeOnActiveScreen: true          // the screen the pointer is on
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.keyboardInteractivity: shell.open === "today" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: shell.open = "" }
        TodayIslands {
            id: todayIslands
            x: Math.max(10, topBar.dateLeft); y: 8; focus: true
            width: 652; height: parent.height - 16
            shown: shell.open === "today"
            origin: Qt.point(30, -16)
            onDone: shell.open = ""
        }
    },
    Window {   // the app's menu, under its name (the work area, so a click beside it closes it)
        id: menuWin
        Component.onCompleted: Status.glassWindow(menuWin, "huginn-app-menu")      // only its glass is blurred behind it
        visible: shell.open === "menu"; color: "transparent"
        LayerShell.Window.scope: "huginn-app-menu"
        LayerShell.Window.wantsToBeOnActiveScreen: true          // the screen the pointer is on
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.keyboardInteractivity: shell.open === "menu" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: shell.open = "" }
        AppMenuIsland {
            id: appMenuIsland
            shown: shell.open === "menu"; only: shell.menuGroup; focus: true
            x: Math.max(6, (shell.menuGroup === "" ? topBar.nameLeft : topBar.groupLeft(shell.menuGroup)) - 6); y: 3
            onDone: shell.open = ""
        }
    },
    Window {   // control centre: slides in from the right edge, and back out. Over the whole work area, so a click
               // anywhere beside it (on a window, the desktop) closes it, as Today's and the menus' do.
        id: ccWin
        Component.onCompleted: Status.glassWindow(ccWin, "huginn-control-centre")      // only its glass is blurred behind it
        visible: shell.open === "cc" || ccPanel.x < width - 1; color: "transparent"
        LayerShell.Window.scope: "huginn-control-centre"
        LayerShell.Window.wantsToBeOnActiveScreen: true          // the screen the pointer is on
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityOnDemand
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; enabled: shell.open === "cc"; onClicked: shell.open = ""
                    onWheel: function (w) { w.accepted = true } }
        MouseArea { x: ccPanel.x; y: ccPanel.y; width: ccPanel.width; height: ccPanel.height; acceptedButtons: Qt.AllButtons }   // clicks on the panel stay there
        Item { focus: shell.open === "cc"; Keys.onEscapePressed: shell.open = "" }
        ControlCentre {
            id: ccPanel
            onDone: { shell.open = ""; editTiles = false }
            onSaverWanted: shell.saverOn = true
            y: 10; width: 344; height: Math.min(parent.height - 20, implicitHeight)
            x: shell.open === "cc" ? parent.width - width - 10 : parent.width
            opacity: shell.open === "cc" ? 1 : 0
            Behavior on x { NumberAnimation { duration: Theme.t.openMs ? 260 : 0; easing.type: Easing.OutCubic } }
            Behavior on opacity { NumberAnimation { duration: Theme.t.openMs ? 200 : 0 } }
        }
    },
    Window {   // the desktop's menu (right-click the desktop): over everything, so windows don't hide it; a click
               // anywhere beside it closes it
        id: deskMenuWin
        visible: shell.deskMenuAt !== null; color: "transparent"
        LayerShell.Window.scope: "huginn-desktop-menu"
        LayerShell.Window.wantsToBeOnActiveScreen: true          // the screen the pointer is on: the one right-clicked
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1                      // the whole screen, as the wallpaper: the click's place is the same
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityOnDemand
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: shell.deskMenuAt = null }
        Item { focus: shell.deskMenuAt !== null; Keys.onEscapePressed: shell.deskMenuAt = null }
        Glass {
            id: deskMenu
            objectName: "desktopMenu"
            popup: true; dense: true; radius: 12; width: 230; height: deskCol.height + 12
            x: shell.deskMenuAt ? Math.max(8, Math.min(shell.deskMenuAt.x, deskMenuWin.width - width - 8)) : 0
            y: shell.deskMenuAt ? Math.max(8, Math.min(shell.deskMenuAt.y, deskMenuWin.height - height - 8)) : 0
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
            Column { id: deskCol; x: 6; y: 6; width: parent.width - 12
                Repeater { model: shell.deskMenuAt && shell.deskMenuAt.file
                                  ? [["Open", "open", "expand"], ["Show in Files", "show", "folder"], ["Move to Trash", "trash", "trash"]]
                                  : (Settings.desktopFiles ? [["New Folder", "folder", "folder"]] : []).concat(
                                    [[shell.editWidgets ? "Done Editing Widgets" : "Edit Widgets…", "widgets", "grid"], ["Change Wallpaper…", "wallpaper", "image"],
                                     ["Desktop & Dock Settings…", "desktop", "desktop"]])
                    Rectangle { required property var modelData; width: deskCol.width; height: 32; radius: 8; color: dh.containsMouse ? Theme.t.hover : "transparent"
                        Glyph { x: 10; anchors.verticalCenter: parent.verticalCenter; name: modelData[2]; size: 14 }
                        Label { x: 34; anchors.verticalCenter: parent.verticalCenter; text: modelData[0]; font.pixelSize: 13 }
                        MouseArea { id: dh; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                var file = shell.deskMenuAt ? shell.deskMenuAt.file : null, what = modelData[1]
                                shell.deskMenuAt = null
                                if (what === "open") Stacks.open(file.path)
                                else if (what === "show") Stacks.showInFiles(file.path)
                                else if (what === "trash") Stacks.trash(file.path)
                                else if (what === "folder") Stacks.newDesktopFolder()
                                else if (what === "widgets") shell.editWidgets = !shell.editWidgets
                                else Status.openSettings(modelData[1] === "wallpaper" ? "appearance" : "desktop")
                            } } } } }
        }
    },
    Window {   // launcher: the whole work area (between the bar and the dock), so a click beside it closes it
        id: launcherWin
        Component.onCompleted: Status.glassWindow(launcherWin, "huginn-launcher")      // only its glass is blurred behind it
        visible: shell.open === "launcher" || launcher.visible; color: "transparent"
        LayerShell.Window.scope: "huginn-launcher"
        // On the screen the dock is on: the menu grows out of the dock's orb. (Left to itself a layer surface goes to
        // whichever screen the compositor fancies, which with several screens was often one with no dock at all.)
        property string placedOn: ""
        LayerShell.Window.screen: shell.dockScreen
        LayerShell.Window.wantsToBeOnActiveScreen: false
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.keyboardInteractivity: shell.open === "launcher" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        Rectangle { anchors.fill: parent; color: "black"; opacity: launcher.presence * 0.22 }
        MouseArea { anchors.fill: parent; onClicked: shell.open = "" }
        Launcher {
            id: launcher; shown: shell.open === "launcher"; onDone: shell.open = ""
            onSearchEverything: function (text) { shell.searchText = text; shell.open = "search" }
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 10 + shell.dockRoom }
            height: Math.min(660, parent.height - 20 - shell.dockRoom)
            // the dock's orb (its window sits just below this one): where the menu grows from
            orb: Qt.point((launcherWin.width - dock.width) / 2 + dock.lead + 32 - x, launcherWin.height - shell.dockRoom + 32 - y)
        }
    },
    Window {   // Search everything: over the whole screen, bar and dock included
        visible: shell.open === "search" || search.visible; color: "transparent"
        LayerShell.Window.scope: "huginn-search"
        LayerShell.Window.wantsToBeOnActiveScreen: true          // the screen the pointer is on
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: shell.open === "search" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        Rectangle { anchors.fill: parent; color: "black"; opacity: search.presence * 0.4 }
        Search { id: search; anchors.fill: parent; shown: shell.open === "search"; startText: shell.searchText; onDone: { shell.open = ""; shell.searchText = "" } }
    },
    Window {   // the game bar (Super+G): over the game, at the top of the screen it fills (GameBar.qml)
        visible: shell.open === "gamebar" || gameBar.visible; color: "transparent"
        LayerShell.Window.scope: "huginn-gamebar"
        LayerShell.Window.screen: shell.screenNamed(shell.gameBarOn) || shell.mainScreen
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: shell.open === "gamebar" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        Rectangle { anchors.fill: parent; color: "black"; opacity: gameBar.presence * 0.18 }
        GameBar { id: gameBar; anchors.fill: parent; shown: shell.open === "gamebar"; stats: shell.gameStats; screenName: shell.gameBarOn; onDone: shell.open = "" }
    },
    Window {   // clipboard history (Super+V): over everything, in the middle
        visible: shell.open === "clipboard" || clipPanel.visible; color: "transparent"
        LayerShell.Window.scope: "huginn-clipboard"
        LayerShell.Window.wantsToBeOnActiveScreen: true          // the screen the pointer is on
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: shell.open === "clipboard" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        Rectangle { anchors.fill: parent; color: "black"; opacity: clipPanel.presence * 0.25 }
        ClipPanel { id: clipPanel; anchors.fill: parent; shown: shell.open === "clipboard"; onDone: shell.open = "" }
    },
    Window {   // the emoji picker (Super+.): like clipboard history, over everything in the middle
        visible: shell.open === "emoji" || emojiPanel.visible; color: "transparent"
        LayerShell.Window.scope: "huginn-emoji"
        LayerShell.Window.wantsToBeOnActiveScreen: true
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: shell.open === "emoji" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        Rectangle { anchors.fill: parent; color: "black"; opacity: emojiPanel.presence * 0.18 }
        EmojiPanel { id: emojiPanel; anchors.fill: parent; shown: shell.open === "emoji"; onDone: shell.open = "" }
    },
    Window {   // Layouts and window sets (Super+Z): over the screen the pointer is on
        id: layoutsWin
        Component.onCompleted: Status.glassWindow(layoutsWin, "huginn-layouts")      // only its glass is blurred behind it
        visible: shell.open === "layouts" || layoutsPanel.visible; color: "transparent"
        LayerShell.Window.scope: "huginn-layouts"
        LayerShell.Window.wantsToBeOnActiveScreen: true
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: shell.open === "layouts" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        Rectangle { anchors.fill: parent; color: "black"; opacity: layoutsPanel.presence * 0.25 }
        Layouts { id: layoutsPanel; anchors.fill: parent; shown: shell.open === "layouts"; forId: shell.layoutsFor; onDone: shell.open = "" }
    },
    Window {   // live captions (Super+Ctrl+L): over everything on the screen the pointer was on; only the bar takes the pointer
        id: captionsWin
        visible: typeof Captions !== "undefined" && Captions !== null && Captions.state !== "off"; color: "transparent"
        LayerShell.Window.scope: "huginn-captions"
        LayerShell.Window.wantsToBeOnActiveScreen: true
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        onVisibleChanged: if (visible) Qt.callLater(function () { if (captionBar.item) captionBar.item.region() })
        Loader { id: captionBar; anchors.fill: parent; active: captionsWin.visible
            sourceComponent: CaptionBar { host: captionsWin } }
    },
    Window {   // hold Super: every shortcut, over the screen the pointer is on; it takes no clicks and no keys
        id: keysWin
        Component.onCompleted: Status.glassWindow(keysWin, "huginn-keys")
        visible: shell.keysShown || keysSheet.visible; color: "transparent"
        flags: Qt.WindowTransparentForInput
        LayerShell.Window.scope: "huginn-keys"
        LayerShell.Window.wantsToBeOnActiveScreen: true
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        Rectangle { anchors.fill: parent; color: "black"; opacity: keysSheet.shown ? 0.18 : 0; Behavior on opacity { NumberAnimation { duration: Theme.t.openMs } } }
        KeysSheet { id: keysSheet; anchors.fill: parent; shown: shell.keysShown }
    },
    Window {   // an app's island, from the dock (right-click or a long press on its tile)
        id: islandWin
        visible: shell.dockIsland !== null; color: "transparent"
        LayerShell.Window.scope: "huginn-app-island"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.keyboardInteractivity: shell.dockIsland ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: shell.dockIsland = null }
        AppIsland {
            id: dockIsland
            visible: shell.dockIsland !== null
            x: Math.max(8, Math.min(islandWin.width - width - 8, (islandWin.width - dock.width) / 2 + shell.dockIslandX - width / 2))
            y: islandWin.height - shell.dockRoom - height - 8
            onDone: shell.dockIsland = null
        }
        onVisibleChanged: if (visible) dockIsland.open(shell.dockIsland)
    }
    ,
    Window {   // the Welcome tour: over everything; it takes clicks only on its island (and on its full-screen pages)
        id: tourWin
        visible: tour.running; color: "transparent"
        LayerShell.Window.scope: "huginn-tour"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: !tour.running ? LayerShell.Window.KeyboardInteractivityNone : tour.phase === "pages" ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityOnDemand
        TourHost {
            id: tour
            anchors.fill: parent; focus: true
            appName: topBar.appName
            todayOpen: shell.open === "today"; menuOpen: shell.open === "menu"
            windowCount: Status.windows.length
            snapped: { var w = shell.frontWindow(); return !!w && w.x <= 24 && w.w < tourWin.width * 0.62 && w.h > tourWin.height * 0.55 }
            target: function (name) {
                var W = tourWin.width, H = tourWin.height, dx = (W - dock.width) / 2 + dock.lead
                var isl = dock.tile + 20, top = H - dockWin.full
                if (name === "dock") return Qt.rect(dx, top, dock.restWidth, isl)
                if (name === "orb") return Qt.rect(dx, top, isl, isl)
                if (name === "date") return Qt.rect(topBar.dateLeft, (shell.barH - 22) / 2, topBar.dateWidth, 22)
                if (name === "name") return Qt.rect(topBar.nameLeft, (shell.barH - 22) / 2, topBar.nameWidth, 22)
                if (name === "window") { var w = shell.frontWindow(); if (w && w.w > 0) return Qt.rect(w.x, w.y, w.w, w.h) }
                return Qt.rect(W / 2 - 1, H / 2 - 1, 2, 2)
            }
            onMaskChanged: function (r) { Tour.setMask(tourWin, r.x, r.y, r.width, r.height) }
            onCloseOpenThings: if (shell.open === "today" || shell.open === "menu") shell.open = ""
            onInstallWanted: Apps.launch("python3 /usr/share/huginn-apps/huginn_app.py installer")
            onWindowWanted: dock.openApp("Files")
            onFinished: shell.touring = false
        }
    }
    ,
    Window {   // the Overview's words and controls (Huginn's compositor spreads the windows under it)
        id: overviewWin
        visible: overview.visible; color: "transparent"
        LayerShell.Window.scope: "huginn-overview"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: overview.open ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
        OverviewOverlay { id: overview; anchors.fill: parent; focus: true; onSearchWanted: function (text) { shell.searchText = text; shell.open = "search" } }
    },
    Window {   // snapping: where a dragged window will land (takes no input), and filling the other half
        id: snapWin
        visible: snapGlass.previewing || snapGlass.assisting; color: "transparent"
        flags: snapGlass.assisting ? 0 : Qt.WindowTransparentForInput
        LayerShell.Window.scope: "huginn-snap"
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        SnapGlass { id: snapGlass; anchors.fill: parent }
    },
    Window {   // Alt+Tab: the windows while Alt is held (Huginn's compositor goes through them)
        id: switchWin
        visible: Status.switcher.windows !== undefined && Status.switcher.windows.length > 1; color: "transparent"
        flags: Qt.WindowTransparentForInput
        width: switchWin.screen ? switchWin.screen.width : 1280; height: 190   // across the screen, in the middle (the island centres in it)
        LayerShell.Window.anchors: LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.exclusionZone: -1
        LayerShell.Window.scope: "huginn-switcher"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        Switcher {
            id: switcher
            anchors.centerIn: parent
            showing: switchWin.visible
            index: Status.switcher.at || 0
            windows: (Status.switcher.windows || []).map(function (w) {
                var a = overview.appFor(w.app), known = Status.windows.filter(function (x) { return x.id === w.id })[0]
                var g = a && a.colours && a.colours.length ? a.colours[0] : Theme.t.accent
                return { app: a || { name: w.title }, title: w.title, minimised: known ? known.minimised : false, glow: Qt.color(g) }
            })
        }
    },
    Window {   // the space's name, for a moment, after switching
        id: spaceWin
        visible: spaceName.opacity > 0; color: "transparent"
        flags: Qt.WindowTransparentForInput
        width: spaceName.width + 20; height: 60
        LayerShell.Window.scope: "huginn-space-name"
        LayerShell.Window.layer: LayerShell.Window.LayerOverlay
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        Glass {
            id: spaceName
            popup: true; dense: true; radius: 18; x: 10; y: 12
            width: spaceLabel.width + 40; height: 40; opacity: 0
            property int last: -1
            Label { id: spaceLabel; anchors.centerIn: parent; text: (Status.spaces.names || [])[Status.spaces.current] || ""; font.pixelSize: 14; font.weight: Font.DemiBold }
            Connections {
                target: Status
                function onWindowsChanged() {
                    var cur = Status.spaces.current
                    if (spaceName.last >= 0 && cur !== spaceName.last && !overview.open) flash.restart()
                    spaceName.last = cur
                }
            }
            SequentialAnimation {
                id: flash
                NumberAnimation { target: spaceName; property: "opacity"; to: 1; duration: 120 }
                PauseAnimation { duration: 1100 }
                NumberAnimation { target: spaceName; property: "opacity"; to: 0; duration: 300 }
            }
        }
    }
    ]
    // Screen corners (Settings › Desktop & Dock): pushing the pointer into one does what it's set to. Only the outer
    // corners of all the screens together, so moving from one screen to the next never sets one off.
    function cornerDo(what) {
        if (what === "overview") Status.overviewDo("toggle")
        else if (what === "desktop") Status.overviewDo("desktop")
        else if (what === "launcher") shell.open = shell.open === "launcher" ? "" : "launcher"
        else if (what === "control") shell.open = shell.open === "cc" ? "" : "cc"
        else if (what === "today") shell.open = shell.open === "today" ? "" : "today"
        else if (what === "search") { shell.searchText = ""; shell.open = shell.open === "search" ? "" : "search" }
        else if (what === "lookup") Apps.launch("python3 /usr/share/huginn-apps/huginn_app.py lens")
        else if (what === "saver") shell.saverOn = true
        else if (what === "lock") Status.power("lock")
    }
    function outerCorner(sc, right, bottom) {
        var all = Status.screenList, g = sc.geometry
        var cx = right ? g.x + g.width : g.x - 1, cy = bottom ? g.y + g.height - 1 : g.y      // just beside it
        var vx = right ? g.x + g.width - 1 : g.x, vy = bottom ? g.y + g.height : g.y - 1       // just above or below it
        for (var i = 0; i < all.length; i++) {
            if (all[i] === sc) continue
            var o = all[i].geometry
            if ((cx >= o.x && cx < o.x + o.width && cy >= o.y && cy < o.y + o.height) || (vx >= o.x && vx < o.x + o.width && vy >= o.y && vy < o.y + o.height)) return false
        }
        return true
    }
    property Instantiator corners: Instantiator {
        model: {
            var out = [], all = Status.screenList, names = [["cornerTL", false, false], ["cornerTR", true, false], ["cornerBL", false, true], ["cornerBR", true, true]]
            for (var i = 0; i < all.length; i++)
                for (var k = 0; k < 4; k++)
                    if (Settings[names[k][0]] !== "" && shell.outerCorner(all[i], names[k][1], names[k][2]))
                        out.push({ screen: all[i], what: Settings[names[k][0]], right: names[k][1], bottom: names[k][2] })
            return out
        }
        delegate: Window {
            required property var modelData
            visible: true; width: 2; height: 2; color: "transparent"
            LayerShell.Window.screen: modelData.screen
            LayerShell.Window.wantsToBeOnActiveScreen: false
            LayerShell.Window.scope: "huginn-hot-corner"
            LayerShell.Window.layer: LayerShell.Window.LayerOverlay
            LayerShell.Window.anchors: (modelData.bottom ? LayerShell.Window.AnchorBottom : LayerShell.Window.AnchorTop) | (modelData.right ? LayerShell.Window.AnchorRight : LayerShell.Window.AnchorLeft)
            LayerShell.Window.exclusionZone: -1
            LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
            MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: shell.cornerDo(modelData.what) }
        }
    }
    // The screen saver (Saver.qml), on every screen: the session daemon starts it (org.huginn.Shell.Key "saver") after
    // Settings' time left alone; a corner or Settings' Preview can too. Any key or movement ends it.
    property bool saverOn: false
    // hold Super: every shortcut (KeysSheet.qml), until the compositor says Super was let go (or a minute, if that's lost)
    property bool keysShown: false
    property Timer keysLonger: Timer { interval: 60000; onTriggered: shell.keysShown = false }
    property var saverPhotos: []
    onSaverOnChanged: if (saverOn && Settings.saver === "photos") saverPhotos = Status.saverPhotos()
    property Instantiator savers: Instantiator {
        model: shell.saverOn ? Status.screenList : []
        delegate: Window {
            id: saverWin
            required property var modelData
            readonly property bool main: modelData.name === Status.primaryScreen || (Status.primaryScreen === "" && Status.screenList[0] === modelData)
            property real since: Date.now()
            visible: true; color: "black"
            LayerShell.Window.screen: modelData
            LayerShell.Window.wantsToBeOnActiveScreen: false
            LayerShell.Window.scope: "huginn-screen-saver"
            LayerShell.Window.layer: LayerShell.Window.LayerOverlay
            LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
            LayerShell.Window.exclusionZone: -1
            LayerShell.Window.keyboardInteractivity: saverWin.main ? LayerShell.Window.KeyboardInteractivityExclusive : LayerShell.Window.KeyboardInteractivityNone
            Saver { id: saverItem; anchors.fill: parent; mode: Settings.saver === "off" ? "clock" : Settings.saver; photos: shell.saverPhotos; main: saverWin.main
                opacity: 0; NumberAnimation on opacity { to: 1; duration: 900; easing.type: Easing.OutCubic }
                focus: true; Keys.onPressed: function (e) { shell.saverOn = false; e.accepted = true } }
            MouseArea { anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.AllButtons
                property point first: Qt.point(-1, -1)
                // (appearing under the pointer counts as no movement: a small shift or a click ends it)
                onPositionChanged: function (m) { if (first.x < 0) { first = Qt.point(m.x, m.y); return }
                    if (Date.now() - saverWin.since > 800 && Math.abs(m.x - first.x) + Math.abs(m.y - first.y) > 6) shell.saverOn = false }
                onPressed: shell.saverOn = false
                onWheel: shell.saverOn = false }
            Component.onCompleted: if (main) saverItem.forceActiveFocus()
        }
    }
}
