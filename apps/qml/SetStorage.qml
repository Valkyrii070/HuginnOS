import QtQuick

// Storage: how full the drive is (apps, games, the parts apps share, everything else), then every app you installed
// with what it takes, biggest first, each with Uninstall, and Steam's games the same way (huginn_storage.py).
Column {
    id: pg
    objectName: "storagePage"
    width: parent ? parent.width : 600; spacing: 18
    readonly property var d: Backend.storage || ({})
    readonly property var dk: d.disk || ({ total: 0, used: 0, free: 0 })
    readonly property var apps: d.apps || []
    readonly property var games: d.games || []
    readonly property bool loading: (Backend.busy || []).indexOf("storage") >= 0 && apps.length === 0 && dk.total === 0
    readonly property real appBytes: apps.reduce(function (s, a) { return s + a.size + a.data }, 0)
    readonly property real gameBytes: games.reduce(function (s, g) { return s + g.size }, 0)
    readonly property real sharedBytes: d.shared || 0
    readonly property real otherBytes: Math.max(0, dk.used - appBytes - gameBytes - sharedBytes)
    property bool allApps: false

    function size(n) {
        if (n >= 1e12) return (n / 1e12).toFixed(2) + " TB"
        if (n >= 1e9) return (n / 1e9).toFixed(n >= 1e11 ? 0 : 1) + " GB"
        if (n >= 1e6) return Math.round(n / 1e6) + " MB"
        return n > 0 ? Math.max(1, Math.round(n / 1e3)) + " KB" : "0 KB"
    }
    function uninstall(a) {
        var choices = [{ id: "keep", label: "Uninstall " + a.name, sub: "What it saved in your home folder stays, so it's all there if you install it again" }]
        if (a.data > 0)
            choices.push({ id: "drop", label: "Uninstall and delete what it saved", sub: "Frees " + size(a.size + a.data) + " in all: its settings, sign-ins and files it kept" })
        win.pick("Uninstall " + a.name + "?", choices, "", function (v) { Backend.uninstallApp(a.id, v === "drop") })
    }

    // the drive
    SetCard { title: "This computer"
        Item { width: parent.width; height: 118
            Label { x: 16; y: 14; text: pg.dk.total ? pg.size(pg.dk.free) + " free" : (pg.loading ? "Looking…" : ""); font.pixelSize: 22; font.weight: Font.Light }
            Label { x: 16; y: 46; visible: pg.dk.total > 0; text: "of " + pg.size(pg.dk.total) + " · " + pg.size(pg.dk.used) + " used"; secondary: true }
            // the bar: apps, games, shared parts, everything else, then what's free
            Rectangle { id: bar; x: 16; y: 72; width: parent.width - 32; height: 14; radius: 7; color: Theme.t.hover; clip: true
                Row { height: parent.height
                    Repeater {
                        model: [[pg.appBytes, "#4C8DFF"], [pg.gameBytes, "#B07CFF"], [pg.sharedBytes, "#3DD1C3"], [pg.otherBytes, "#A3B1C4"]]
                        Rectangle { required property var modelData; height: bar.height
                            width: pg.dk.total > 0 ? Math.max(modelData[0] > 0 ? 2 : 0, bar.width * modelData[0] / pg.dk.total) : 0; color: modelData[1] } } } }
            Row { x: 16; y: 94; spacing: 16
                Repeater {
                    model: [["Apps", pg.appBytes, "#4C8DFF"], ["Games", pg.gameBytes, "#B07CFF"], ["Shared by apps", pg.sharedBytes, "#3DD1C3"], ["System and your files", pg.otherBytes, "#A3B1C4"]]
                    Row { required property var modelData; spacing: 6; visible: modelData[1] > 0
                        Rectangle { width: 9; height: 9; radius: 3; color: modelData[2]; anchors.verticalCenter: parent.verticalCenter }
                        Label { text: modelData[0] + " " + pg.size(modelData[1]); secondary: true; font.pixelSize: 11 } } } } } }

    // the apps
    SetCard { title: "Apps"
        note: pg.d.flatpak === false ? "" : "Apps you installed from the App Store. What's shown is the app itself plus what it keeps in your home folder. Huginn's own apps are part of the system and stay."
        SetRow { visible: pg.loading; title: "Looking at what each app takes…"; glyph: "apps" }
        SetRow { visible: !pg.loading && pg.apps.length === 0; glyph: "apps"; title: pg.d.flatpak === false ? "Flatpak isn't installed" : "No apps installed yet"
            sub: pg.d.flatpak === false ? "" : "Apps from the App Store show here with the space they take."
            chevron: pg.d.flatpak !== false; onClicked: Backend.openApp("store") }
        Repeater { model: pg.allApps ? pg.apps : pg.apps.slice(0, 12)
            SetRow { required property var modelData
                objectName: "storageApp_" + modelData.id
                title: modelData.name; picture: modelData.icon || ""; glyph: "apps"
                sub: pg.size(modelData.size + modelData.data) + (modelData.data > 0 ? "  ·  the app " + pg.size(modelData.size) + ", what it saved " + pg.size(modelData.data) : "")
                Btn { text: "Uninstall"; onClicked: pg.uninstall(modelData) } } }
        SetRow { visible: pg.apps.length > 12; title: pg.allApps ? "Show fewer" : "Show all " + pg.apps.length; chevron: true; onClicked: pg.allApps = !pg.allApps }
        SetRow { visible: pg.sharedBytes > 0; glyph: "layers"; tile: "#118C7E"; title: "Shared by apps · " + pg.size(pg.sharedBytes)
            sub: "The parts apps are built on (Flatpak runtimes). Ones no app uses any more, left by apps you took off, can go."
            Btn { text: "Remove Unused"; onClicked: Backend.removeUnused() } } }

    // Steam's games
    SetCard { visible: pg.games.length > 0; title: "Games in Steam"
        note: "Steam asks before it takes a game off, and keeps its cloud saves."
        Repeater { model: pg.games
            SetRow { required property var modelData
                title: modelData.name; glyph: "gamepad"; tile: "#7A3FE0"; sub: pg.size(modelData.size)
                Btn { text: "Uninstall"; onClicked: Backend.uninstallGame(modelData.appid) } } } }
}
