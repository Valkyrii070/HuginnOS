import QtQuick

// Make a live wallpaper of your own (Appearance › Wallpaper › Make one): a realm's scene in your own colours, a
// picture of yours drifting, or a video of yours, with snow, rain, stars, fireflies, lights, leaves or embers on top.
// What it'll look like plays at the top as you go. CustomWallpaper.qml draws it here and on the desktop.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var scenes: [["aurora", "Aurora"], ["bifrost", "Bifröst"], ["muspelheim", "Muspelheim"], ["niflheim", "Niflheim"]]
    readonly property var sceneColours: ({
        aurora: { tintA: "#0F2624", tintB: "#17192C", glowA: "#3DD6B5", glowB: "#7B61FF" },
        bifrost: { tintA: "#1D1932", tintB: "#2A1727", glowA: "#8E7BFF", glowB: "#FF7AB8" },
        muspelheim: { tintA: "#2C1912", tintB: "#1F1718", glowA: "#FF8A4C", glowB: "#FFC857" },
        niflheim: { tintA: "#12212F", tintB: "#171A20", glowA: "#7CC4FF", glowB: "#CFEAFF" } })
    readonly property var effectNames: [["snow", "Snow"], ["rain", "Rain"], ["stars", "Stars"], ["fireflies", "Fireflies"], ["lights", "Lights"], ["leaves", "Leaves"], ["embers", "Embers"]]
    readonly property var palette: ["#0B0F1A", "#12212F", "#0F2624", "#17192C", "#1D1932", "#2A1727", "#2C1912", "#1F2A14",
                                    "#3DD6B5", "#2EC4F0", "#7CC4FF", "#4C6FFF", "#7B61FF", "#B07CFF", "#FF7AB8", "#FF5A6E",
                                    "#FF8A4C", "#FFC857", "#F2E86D", "#9BE15D", "#FFFFFF", "#CFEAFF", "#E8833A", "#D8FF6E"]
    readonly property var ideas: [
        { label: "Snowy night", spec: { base: "scene", scene: "niflheim", effects: ["snow", "stars"], amount: 0.55, pace: 0.8 } },
        { label: "Summer evening", spec: { base: "scene", scene: "muspelheim", effects: ["fireflies", "stars"], amount: 0.5, pace: 0.9 } },
        { label: "Rainy window", spec: { base: "scene", scene: "niflheim", colours: { tintA: "#0B0F1A", tintB: "#12212F", glowA: "#4C6FFF", glowB: "#2EC4F0" }, effects: ["rain", "lights"], amount: 0.6, pace: 1 } },
        { label: "Autumn", spec: { base: "scene", scene: "bifrost", colours: { tintA: "#2C1912", tintB: "#1F1718", glowA: "#E8833A", glowB: "#FFC857" }, effects: ["leaves"], amount: 0.45, pace: 0.9 } },
        { label: "Campfire", spec: { base: "scene", scene: "muspelheim", effects: ["embers", "stars"], amount: 0.6, pace: 1.1 } } ]

    // what's being made: an existing one's (win.makerId) or a new one's
    property string ident: win.makerId
    readonly property var existing: ((Backend.look || {}).live || []).filter(function (w) { return w.id === pg.ident })[0] || null
    property var spec: existing ? JSON.parse(JSON.stringify(existing.spec)) : { name: "", base: "scene", scene: "niflheim", colours: sceneColours.niflheim,
                                                                                motion: "drift", effects: ["snow", "stars"], amount: 0.5, pace: 0.9, shade: 0, effectColour: "" }
    property string media: ""                 // a picture or video just chosen (copied in when it's saved)
    property string colourSlot: ""            // the colour being chosen: tintA, tintB, glowA, glowB or effect
    function set(k, v) { var s = JSON.parse(JSON.stringify(spec)); s[k] = v; spec = s }
    function setColour(k, v) { var c = JSON.parse(JSON.stringify(spec.colours || {})); c[k] = v; set("colours", c) }
    function toggle(e) { var l = (spec.effects || []).slice(); var i = l.indexOf(e); if (i >= 0) l.splice(i, 1); else l.push(e); set("effects", l) }
    function idea(i) { var s = JSON.parse(JSON.stringify(ideas[i].spec)); s.colours = s.colours || sceneColours[s.scene]; s.motion = "drift"; s.shade = 0; s.effectColour = ""
                       var named = spec.name && !ideas.some(function (d) { return d.label === spec.name })      // a name of their own stays
                       s.name = named ? spec.name : ideas[i].label; media = ""; spec = s }
    function base(name) { return String(name || "").split("/").pop() }
    function folderOf(path) { return "file://" + String(path).substring(0, String(path).lastIndexOf("/") + 1) }
    readonly property var shown: { var s = JSON.parse(JSON.stringify(spec)); if (media) s.file = base(media); return s }
    readonly property string shownFolder: media ? folderOf(media) : existing ? existing.folder : ""
    readonly property bool needsMedia: spec.base !== "scene" && !media && !(existing && existing.spec.base === spec.base && existing.spec.file)
    function save(use) {
        var s = JSON.parse(JSON.stringify(spec))
        if (!s.name || !s.name.trim()) s.name = s.base === "scene" ? (scenes.filter(function (x) { return x[0] === s.scene })[0] || ["", "My"])[1] + " of my own" : "My wallpaper"
        var id = Backend.saveLiveWallpaper(pg.ident, s, pg.media, use)
        if (!id) return
        var path = Backend.liveStillPath(id)
        stage.grabToImage(function (result) { if (path) result.saveToFile(path); win.makerId = ""; win.go("appearance") }, Qt.size(640, 360))
    }

    // ---------------------------------------------------------------- the preview
    Rectangle {
        id: frame
        width: parent.width; height: Math.round(width * 9 / 16); radius: 16; clip: true; color: "#000000"
        border.width: 1; border.color: Theme.t.separator
        Item {
            id: stage
            anchors.fill: parent; anchors.margins: 1
            Loader {
                anchors.fill: parent
                source: Theme.t.liveDir ? Theme.t.liveDir + "CustomWallpaper.qml" : ""
                onLoaded: {
                    item.spec = Qt.binding(function () { return pg.shown })
                    item.folder = Qt.binding(function () { return pg.shownFolder })
                    item.moving = Qt.binding(function () { return pg.visible && win.visible })
                }
            }
        }
        Rectangle { anchors { left: parent.left; top: parent.top; margins: 12 } width: tag.width + 18; height: 24; radius: 12; color: "#99000000"
            Label { id: tag; anchors.centerIn: parent; text: pg.needsMedia ? "Choose a " + (pg.spec.base === "picture" ? "picture" : "video") + " below" : "Preview"; color: "#FFFFFF"; font.pixelSize: 11; font.weight: Font.DemiBold } }
    }
    Row { spacing: 6
        Label { text: "Ideas"; secondary: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; rightPadding: 4 }
        Repeater { model: pg.ideas; Seg { required property var modelData; required property int index; text: modelData.label; onClicked: pg.idea(index) } } }

    // ---------------------------------------------------------------- what it starts from
    SetCard { title: "Start from"
        SetRow { title: "Behind it all"
            SetChoice { objectName: "baseChoice"; each: 104; options: [["scene", "A scene"], ["picture", "A picture"], ["video", "A video"]]; value: pg.spec.base
                onPicked: function (v) { pg.set("base", v); pg.media = "" } } }
        Flow { visible: pg.spec.base === "scene"; x: 16; width: parent.width - 32; spacing: 10; topPadding: 4; bottomPadding: 10
            Repeater { model: pg.scenes
                Column { required property var modelData; spacing: 4
                    Rectangle { width: 128; height: 72; radius: 10; clip: true; color: Theme.t.hover
                        border.width: pg.spec.scene === modelData[0] ? 3 : 0; border.color: Theme.t.accent
                        Image { anchors.fill: parent; anchors.margins: parent.border.width; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 256
                            source: Theme.t.liveDir ? Theme.t.liveDir + "stills/" + modelData[0] + ".jpg" : "" }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: { pg.set("scene", modelData[0]); pg.set("colours", pg.sceneColours[modelData[0]]) } } }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData[1]; font.pixelSize: 12 } } } }
        SetRow { visible: pg.spec.base === "scene"; title: "Colours"; sub: "Click one, then pick its colour"
            Row { spacing: 8
                Repeater { model: [["tintA", "Sky"], ["tintB", "Deep"], ["glowA", "Light"], ["glowB", "Second light"]]
                    Column { required property var modelData; spacing: 2
                        Rectangle { width: 34; height: 34; radius: 17; color: (pg.spec.colours || {})[modelData[0]] || "#000"; anchors.horizontalCenter: parent.horizontalCenter
                            border.width: pg.colourSlot === modelData[0] ? 3 : 1; border.color: pg.colourSlot === modelData[0] ? Theme.t.accent : Theme.t.separator
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: pg.colourSlot = pg.colourSlot === modelData[0] ? "" : modelData[0] } }
                        Label { text: modelData[1]; font.pixelSize: 10; secondary: true; anchors.horizontalCenter: parent.horizontalCenter } } } } }
        SetRow { visible: pg.spec.base !== "scene"; title: pg.spec.base === "picture" ? "Picture" : "Video"
            sub: pg.media ? pg.base(pg.media) : pg.existing && pg.existing.spec.base === pg.spec.base && pg.existing.spec.file ? "The one it has" : "None yet"
            Btn { text: pg.spec.base === "picture" ? "Choose a Picture…" : "Choose a Video…"
                onClicked: Picker.open(pg.spec.base === "picture" ? "Choose a picture" : "Choose a video",
                                       pg.spec.base === "picture" ? [["Pictures", "*.jpg *.jpeg *.png *.webp *.bmp *.gif *.avif *.heic *.jxl *.JPG *.JPEG *.PNG"]]
                                                                  : [["Videos", "*.mp4 *.webm *.mkv *.mov *.m4v *.ogv *.avi *.MP4 *.MOV"]],
                                       function (paths) { if (paths.length) pg.media = paths[0] }) } }
        SetRow { visible: pg.spec.base === "picture"; title: "Movement"
            SetChoice { each: 90; options: [["drift", "Drift"], ["breathe", "Breathe"], ["still", "Still"]]; value: pg.spec.motion || "drift"; onPicked: function (v) { pg.set("motion", v) } } }
        SetRow { visible: pg.spec.base === "video"; title: "It plays without sound, over and over"; sub: "And rests while a window fills the screen. A short, quiet clip works best." }
        SetRow { visible: pg.spec.base !== "scene"; title: "Darken it"; sub: "So the effects and your windows stand out"
            SetSlider { width: 220; value: (pg.spec.shade || 0) / 0.6; lowText: "None"; highText: "More"; onMoved: function (v) { pg.set("shade", Math.round(v * 60) / 100) } } }
    }

    // ---------------------------------------------------------------- what moves over it
    SetCard { title: "Effects"; note: "Any of them together. They rest where they are when the desktop shouldn't move (Reduce Motion, or a window filling the screen)."
        Flow { x: 16; width: parent.width - 32; spacing: 6; topPadding: 12; bottomPadding: 8
            Repeater { model: pg.effectNames
                Seg { required property var modelData; objectName: "fx-" + modelData[0]; text: modelData[1]; on: (pg.spec.effects || []).indexOf(modelData[0]) >= 0; onClicked: pg.toggle(modelData[0]) } } }
        SetRow { title: "How many"
            SetSlider { width: 240; value: pg.spec.amount === undefined ? 0.5 : pg.spec.amount; lowText: "Few"; highText: "Lots"; onMoved: function (v) { pg.set("amount", Math.round(v * 100) / 100) } } }
        SetRow { title: "Their colour"; sub: pg.spec.effectColour ? "Your colour" : "Each its own (snow white, embers orange…)"
            Row { spacing: 8
                Btn { text: "Their Own"; enabled: !!pg.spec.effectColour; onClicked: { pg.set("effectColour", ""); if (pg.colourSlot === "effect") pg.colourSlot = "" } }
                Rectangle { width: 30; height: 30; radius: 15; anchors.verticalCenter: parent.verticalCenter; color: pg.spec.effectColour || "#FFFFFF"
                    border.width: pg.colourSlot === "effect" ? 3 : 1; border.color: pg.colourSlot === "effect" ? Theme.t.accent : Theme.t.separator
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: pg.colourSlot = pg.colourSlot === "effect" ? "" : "effect" } } } }
        SetRow { title: "Speed"
            SetSlider { width: 240; value: Math.log((pg.spec.pace || 1) / 0.25) / Math.log(12); lowText: "Slow"; highText: "Fast"
                onMoved: function (v) { pg.set("pace", Math.round(0.25 * Math.pow(12, v) * 100) / 100) } } }
    }
    // the colours to choose from, under whichever is being chosen
    Rectangle { visible: pg.colourSlot !== ""; width: parent.width; height: pal.height + 24; radius: Theme.t.radiusCard; color: Theme.t.group; border.width: 1; border.color: Theme.t.accent
        Flow { id: pal; x: 12; y: 12; width: parent.width - 24; spacing: 8
            Repeater { model: pg.palette
                Rectangle { required property string modelData; width: 30; height: 30; radius: 15; color: modelData; border.width: 1; border.color: Theme.t.separator
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: { if (pg.colourSlot === "effect") pg.set("effectColour", modelData); else pg.setColour(pg.colourSlot, modelData) } } } }
            TextBox { width: 120; placeholder: "#RRGGBB"
                onAccepted: { var t = text.trim(); if (/^#?[0-9a-fA-F]{6}$/.test(t)) { t = (t[0] === "#" ? t : "#" + t).toUpperCase(); if (pg.colourSlot === "effect") pg.set("effectColour", t); else pg.setColour(pg.colourSlot, t) } } }
            Btn { text: "Done"; onClicked: pg.colourSlot = "" } } }

    // ---------------------------------------------------------------- name and save
    SetCard { title: "Name"
        Item { width: parent.width; height: 56
            TextBox { id: nameBox; x: 16; width: parent.width - 32; anchors.verticalCenter: parent.verticalCenter; placeholder: "What to call it"; text: pg.spec.name || ""
                onTextChanged: if (text !== (pg.spec.name || "")) pg.set("name", text) } } }
    Row { spacing: 8
        Btn { objectName: "saveUse"; primary: true; text: "Save and Use"; enabled: !pg.needsMedia; onClicked: pg.save(true) }
        Btn { objectName: "saveOnly"; text: "Save"; enabled: !pg.needsMedia; onClicked: pg.save(false) }
        Btn { text: "Cancel"; onClicked: { win.makerId = ""; win.go("appearance") } }
        Item { width: 20; height: 1 }
        Btn { visible: !!pg.existing; text: "Share…"; onClicked: Backend.shareLiveWallpaper(pg.ident) }
        Btn { visible: !!pg.existing; danger: true; text: "Delete"
            onClicked: { var id = pg.ident; win.confirm("Delete “" + (pg.existing ? pg.existing.name : "") + "”?", "It goes for good. A file you shared of it stays.", "Delete",
                                                        function () { Backend.deleteLiveWallpaper(id); win.makerId = ""; win.go("appearance") }) } } }
}
