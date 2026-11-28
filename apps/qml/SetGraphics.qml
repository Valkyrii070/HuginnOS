import QtQuick

// Graphics: the graphics card, what it's doing now (read once a second while this page shows: load, clocks,
// temperatures, power against its limit, the fan, video memory) and, on AMD cards, its performance level
// (Automatic, Highest clocks, Lowest clocks), kept for the next start. Game stats over games: Super+Alt+G; the
// game bar: Super+G.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var g: Backend.graphics
    property var now: ({})
    Timer { interval: 1000; repeat: true; running: pg.visible && pg.g.available === true; triggeredOnStart: true
        onTriggered: pg.now = Backend.gpuNow() }
    function hot(t) { return t >= 95 ? "#E5484D" : t >= 85 ? "#E0A33A" : Theme.t.text }

    SetCard { visible: pg.g.available === false
        SetRow { title: "No graphics card to show"; sub: "This computer's graphics didn't answer."; glyph: "display" } }
    SetCard { visible: pg.g.available === true; title: pg.g.name || "Graphics card"
        note: [pg.g.driver ? "Driver: " + pg.g.driver : "", pg.g.mesa ? "Mesa " + pg.g.mesa : "", pg.g.memTotal ? pg.g.memTotal + " GB of video memory" : ""].filter(Boolean).join("  ·  ")
        Grid {
            id: tiles; columns: 3; spacing: 10; width: parent.width
            readonly property real w: (width - 20) / 3
            Reading { width: tiles.w; big: pg.now.load !== undefined ? pg.now.load + "%" : "–"; small: "busy"
                line: pg.now.coreMhz ? pg.now.coreMhz + " MHz" : (pg.now.ghz ? pg.now.ghz.toFixed(2) + " GHz" : "") }
            Reading { width: tiles.w; big: pg.now.temp !== undefined ? pg.now.temp + "°C" : "–"; small: "temperature"; tint: pg.hot(pg.now.hot || pg.now.temp || 0)
                line: [pg.now.hot !== undefined ? "hot spot " + pg.now.hot + "°C" : "", pg.now.memTemp !== undefined ? "memory " + pg.now.memTemp + "°C" : ""].filter(Boolean).join(" · ") }
            Reading { width: tiles.w; big: pg.now.watts !== undefined ? pg.now.watts + " W" : "–"; small: "power"
                line: pg.now.capWatts ? "limit " + pg.now.capWatts + " W" + (pg.g.capMaxWatts && pg.g.capMaxWatts !== pg.now.capWatts ? " (up to " + pg.g.capMaxWatts + ")" : "") : "" }
            Reading { width: tiles.w; big: pg.now.memTotal !== undefined ? pg.now.memUsed + " GB" : "–"; small: "video memory in use"
                line: pg.now.memTotal !== undefined ? "of " + pg.now.memTotal + " GB" + (pg.now.memMhz ? " · " + pg.now.memMhz + " MHz" : "") : "" }
            Reading { width: tiles.w; big: pg.now.fan !== undefined ? pg.now.fan + "" : "–"; small: "fan, turns a minute"
                line: pg.now.fanPercent !== undefined ? pg.now.fanPercent + "% of its speed" + (pg.now.fan === 0 ? " (resting while cool)" : "") : "" }
            Reading { width: tiles.w; big: pg.levelName(pg.now.level || pg.g.level); small: "performance"; line: "chosen below" }
        } }
    function levelName(l) { return l === "high" ? "Highest" : l === "low" ? "Lowest" : l === "auto" ? "Automatic" : l ? l : "–" }
    SetCard { visible: pg.g.amd === true; title: "Performance"
        note: "Automatic suits nearly everything: the card speeds up for games and rests otherwise. Highest keeps it at its top clocks (the most steady frame times in some games, more heat, power and fan); Lowest keeps it quiet and cool. Kept when the computer starts again."
        SetRow { title: "Clocks"
            SetChoice { objectName: "gpuLevel"; each: 96; options: [["auto", "Automatic"], ["high", "Highest"], ["low", "Lowest"]]; value: pg.now.level || pg.g.level || "auto"
                onPicked: function (v) { Backend.setGpuLevel(v) } } } }
    SetCard { visible: pg.g.available === true; title: "In games"
        SetRow { title: "Game bar"; sub: "Stats, Do Not Disturb, the microphone and a screenshot, over the game"; Label { text: "Super+G"; secondary: true; font.pixelSize: 12 } }
        SetRow { title: "Game stats in the corner"; sub: "The game's frame rate, the card and the processor while you play"; Label { text: "Super+Alt+G"; secondary: true; font.pixelSize: 12 } }
        SetRow { title: "Game mode, FreeSync and tearing"; sub: "In Desktop & Dock"; chevron: true; onClicked: win.page = "desktop" } }

    component Reading: Rectangle {
        property string big: ""
        property string small: ""
        property string line: ""
        property color tint: Theme.t.text
        height: 86; radius: 14; color: Theme.t.hover
        Column { x: 14; y: 11; width: parent.width - 28; spacing: 1
            Label { text: parent.parent.big; font.pixelSize: 24; font.weight: Font.DemiBold; color: parent.parent.tint }
            Label { text: parent.parent.small; font.pixelSize: 11; secondary: true }
            Label { width: parent.width; text: parent.parent.line; font.pixelSize: 11; secondary: true; elide: Text.ElideRight } }
    }
}
