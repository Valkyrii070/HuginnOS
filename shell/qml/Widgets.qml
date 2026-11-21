import QtQuick

// The desktop's widgets, the ones you chose, in your order (Settings.widgets): the weather for your first place in
// Weather, which apps used the camera, microphone, screen or location this week (Privacy Report), what's next in
// Calendar and Reminders, a clock, this month, the computer's processor, memory and drive, what's playing, and a
// photo from Pictures. Their data comes from those apps' own files and the system (Glance in huginn_shell.py, Live for
// what's playing); with nothing there yet, each says how to fill it. A tap opens the app.
// Editing (right-click the desktop › Edit Widgets, or Settings › Desktop & Dock): each gets a button to take it off
// and arrows to move it, and the ones not shown can be added from the list under them.
Column {
    id: wg
    width: 270; spacing: 14
    property bool editing: false
    signal doneEditing()
    // Where each widget is: in the column (this item, on the main screen) until it's dragged somewhere, then wherever
    // it was left on whichever screen (Settings.widgetPlaces: kind -> { s: screen, x, y } as parts of that screen).
    // The shell makes one of these per placed widget (`only`: just that one) on its screen. Dragging happens while
    // editing; `area` is the wallpaper it's on, which positions are measured against.
    property var only: null
    property Item area: null
    property string screenName: ""
    readonly property var places: Settings.widgetPlaces || ({})
    readonly property var shown: only !== null ? only : (Settings.widgets || []).filter(function (k) { return !wg.places[k] })
    readonly property var all: Settings.widgets || []
    function place(kind, screen, fx, fy) {
        var p = JSON.parse(JSON.stringify(places))
        p[kind] = { s: screen, x: Math.round(Math.max(0, Math.min(1, fx)) * 10000) / 10000, y: Math.round(Math.max(0, Math.min(1, fy)) * 10000) / 10000 }
        Settings.set("widgetPlaces", JSON.stringify(p))
    }
    function unplaceAll() { Settings.set("widgetPlaces", "") }
    function dropped(kind, item, dx, dy) {              // let go after a drag: it stays where it is now
        if (!area) return
        var at = item.mapToItem(area, 0, 0)
        place(kind, screenName, (at.x + dx) / Math.max(1, area.width), (at.y + dy) / Math.max(1, area.height))
    }
    function toNextScreen(kind, item) {
        var list = Status.screenList || [], names = list.map(function (sc) { return sc.name }), i = names.indexOf(screenName)
        if (names.length < 2 || !area) return
        var at = item.mapToItem(area, 0, 0)
        place(kind, names[(i + 1) % names.length], at.x / Math.max(1, area.width), at.y / Math.max(1, area.height))
    }
    readonly property var names: ({ weather: "Weather", privacy: "Privacy Report", next: "Up Next", clock: "Clock", month: "Calendar",
                                    system: "System", music: "Now Playing", photo: "Photo" })
    readonly property var blurbs: ({ weather: "The forecast for your first place in Weather", privacy: "Which apps used the camera, microphone or screen",
                                     next: "What's next in Calendar and Reminders", clock: "The time and the date, big", month: "This month, today marked",
                                     system: "Processor, memory and the drive", music: "What's playing, with its controls", photo: "A picture from Pictures, a new one each hour" })
    readonly property var glyphs: ({ weather: "cloudsun", privacy: "shield", next: "calendar", clock: "clock", month: "calendar", system: "cpu", music: "music", photo: "image" })
    readonly property var addable: (Settings.widgetKinds || []).filter(function (k) { return wg.all.indexOf(k) < 0 })
    function save(list) { Settings.set("widgets", list.join(",")) }
    function remove(k) {
        if (places[k]) { var p = JSON.parse(JSON.stringify(places)); delete p[k]; Settings.set("widgetPlaces", JSON.stringify(p)) }
        save(all.filter(function (x) { return x !== k }))
    }
    function add(k) { if (all.length < 8) save(all.concat([k])) }
    function move(k, step) {            // (in the column: among the ones still in it)
        var col = shown, i = col.indexOf(k), j = i + step
        if (i < 0 || j < 0 || j >= col.length) return
        var l = all.slice(), a = l.indexOf(k), b = l.indexOf(col[j])
        l[a] = col[j]; l[b] = k; save(l)
    }

    component Card: Glass { width: parent ? parent.width : 270; radius: 16; wallpaperOnly: true }   // never frosts a window
    component Title: Label { secondary: true; font.pixelSize: 11; font.weight: Font.DemiBold }
    component Tap: MouseArea { property string app: ""; anchors.fill: parent; cursorShape: Qt.PointingHandCursor; enabled: !wg.editing
        onClicked: Apps.launch("python3 /usr/share/huginn-apps/huginn_app.py " + app) }
    component Bar: Item { property real value: 0; property color fill: Theme.t.accent; width: parent ? parent.width : 200; height: 6
        Rectangle { anchors.fill: parent; radius: 3; color: Theme.t.hover }
        Rectangle { width: Math.max(6, parent.width * Math.max(0, Math.min(1, parent.value))); height: parent.height; radius: 3; color: parent.fill } }

    Repeater {
        model: wg.shown
        Item {
            id: slot
            required property string modelData
            required property int index
            width: wg.width; height: body.height
            z: mover.pressed ? 10 : 0
            transform: Translate { x: mover.dx; y: mover.dy }
            // editing: drag it anywhere on this screen (it stays where it's let go)
            MouseArea { id: mover; visible: wg.editing; z: 1; anchors.fill: parent; cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                property real dx: 0
                property real dy: 0
                property point from
                onPressed: function (m) { from = mapToItem(wg.area || wg, m.x, m.y); dx = 0; dy = 0 }
                onPositionChanged: function (m) { if (!pressed) return; var p = mapToItem(wg.area || wg, m.x, m.y); dx = p.x - from.x; dy = p.y - from.y }
                onReleased: { var moved = Math.abs(dx) + Math.abs(dy) > 6, x = dx, y = dy; dx = 0; dy = 0; if (moved) wg.dropped(slot.modelData, slot, x, y) } }
            Loader { id: body; width: parent.width
                sourceComponent: ({ weather: weatherCard, privacy: privacyCard, next: nextCard, clock: clockCard, month: monthCard,
                                    system: systemCard, music: musicCard, photo: photoCard })[slot.modelData] || null }
            // editing: take it off (top left), move it (right)
            Rectangle { visible: wg.editing; z: 2; x: -8; y: -8; width: 24; height: 24; radius: 12; color: "#E5484D"; border.width: 2; border.color: "#FFFFFF"
                objectName: "removeWidget_" + slot.modelData
                Rectangle { anchors.centerIn: parent; width: 10; height: 2; radius: 1; color: "#FFFFFF" }
                MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor; onClicked: wg.remove(slot.modelData) } }
            // editing, more than one screen: send it to the next one
            Rectangle { visible: wg.editing && (Status.screenList || []).length > 1; z: 2; x: 22; y: -8; width: 24; height: 24; radius: 12
                color: Theme.t.dark ? "#CC1A1E23" : "#E6FFFFFF"; border.width: 1; border.color: Theme.t.line
                Glyph { anchors.centerIn: parent; name: "display"; size: 12 }
                MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor; onClicked: wg.toNextScreen(slot.modelData, slot) } }
            Column { visible: wg.editing && wg.only === null; z: 2; anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } spacing: 6
                Repeater { model: [[-1, "up"], [1, "down"]]
                    Rectangle { required property var modelData; width: 26; height: 26; radius: 13; color: Theme.t.dark ? "#CC1A1E23" : "#E6FFFFFF"
                        opacity: (modelData[0] < 0 ? slot.index > 0 : slot.index < wg.shown.length - 1) ? 1 : 0.35
                        Glyph { anchors.centerIn: parent; name: modelData[1]; size: 13 }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: wg.move(slot.modelData, modelData[0]) } } } }
        }
    }

    // editing: what can be added, and Done
    Card {
        visible: wg.editing && wg.only === null; objectName: "widgetGallery"
        height: gallery.height + 24
        Column { id: gallery; x: 12; y: 12; width: parent.width - 24; spacing: 6
            Item { width: parent.width; height: 26
                Title { text: wg.addable.length ? "ADD A WIDGET" : "EVERY WIDGET IS ON THE DESKTOP"; anchors.verticalCenter: parent.verticalCenter }
                Rectangle { anchors { right: parent.right; verticalCenter: parent.verticalCenter } width: doneLabel.width + 24; height: 26; radius: 13; color: Theme.t.accent
                    objectName: "widgetsDone"
                    Label { id: doneLabel; anchors.centerIn: parent; text: "Done"; color: Theme.t.onAccent; font.pixelSize: 12; font.weight: Font.DemiBold }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: wg.doneEditing() } } }
            Repeater { model: wg.addable
                Rectangle { required property string modelData; width: gallery.width; height: 44; radius: Theme.t.radiusCard
                    objectName: "addWidget_" + modelData
                    color: addHit.containsMouse ? Theme.t.hover : "transparent"
                    Rectangle { x: 6; width: 30; height: 30; radius: 9; color: Theme.t.hover; anchors.verticalCenter: parent.verticalCenter
                        Glyph { anchors.centerIn: parent; name: wg.glyphs[modelData] || "apps"; size: 15 } }
                    Column { x: 46; width: parent.width - 46 - 34; anchors.verticalCenter: parent.verticalCenter
                        Label { text: wg.names[modelData] || modelData; font.pixelSize: 12; font.weight: Font.DemiBold }
                        Label { width: parent.width; text: wg.blurbs[modelData] || ""; secondary: true; font.pixelSize: 11; elide: Text.ElideRight } }
                    Glyph { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } name: "plus"; size: 15; ink: Theme.t.accent }
                    MouseArea { id: addHit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: wg.add(modelData) } } }
            Label { visible: wg.all.length >= 8; width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                text: "Eight is the most: take one off to add another." }
            Label { width: parent.width; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 11
                text: "Drag a widget anywhere on the screen" + ((Status.screenList || []).length > 1 ? "; the screen button sends it to the next one." : ".") }
            Rectangle { visible: Object.keys(wg.places).length > 0; width: backLabel.width + 24; height: 26; radius: 13; color: Theme.t.hover
                Label { id: backLabel; anchors.centerIn: parent; text: "Back Into a Column"; font.pixelSize: 12; font.weight: Font.DemiBold }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: wg.unplaceAll() } } }
    }

    // ------------------------------------------------------------------------------------------------- the widgets
    readonly property var w: Glance.weather
    readonly property bool hasWeather: w.temp !== undefined && w.temp !== ""
    Component { id: weatherCard
        Card {
            objectName: "weatherCard"
            height: wg.hasWeather ? (wg.w.days && wg.w.days.length ? 150 : 100) : 86
            Tap { app: "weather" }
            Title { x: 16; y: 16; text: wg.w.place ? wg.w.place.toUpperCase() : "WEATHER" }
            Label { visible: !wg.hasWeather; x: 16; y: 38; width: parent.width - 32; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                text: wg.w.place ? "Open Weather to get the forecast." : "Pick your place in Weather to see its forecast here." }
            Label { visible: wg.hasWeather; x: 16; y: 36; text: wg.w.temp || ""; font.pixelSize: 40; font.weight: Font.Light }
            Label { visible: wg.hasWeather; anchors { right: parent.right; rightMargin: 16 } y: 44; secondary: true; font.pixelSize: 12; horizontalAlignment: Text.AlignRight
                text: (wg.w.words || "") + (wg.w.high ? "\n↑ " + wg.w.high + "  ↓ " + wg.w.low : "") + (wg.w.stale ? "\n" + wg.w.stale : "") }
            Rectangle { visible: wg.hasWeather && wg.w.days && wg.w.days.length > 0; x: 16; y: 98; width: parent.width - 32; height: 1; color: Theme.t.line }
            Row { visible: wg.hasWeather; x: 16; y: 108; width: parent.width - 32
                Repeater { model: wg.hasWeather ? wg.w.days : []
                    Column { required property var modelData; width: parent.width / 3
                        Label { text: modelData.day; secondary: true; font.pixelSize: 12; anchors.horizontalCenter: parent.horizontalCenter }
                        Label { text: modelData.temp; font.weight: Font.DemiBold; font.pixelSize: 12; anchors.horizontalCenter: parent.horizontalCenter } } } }
        }
    }
    Component { id: privacyCard
        Card {
            objectName: "privacyCard"
            height: Math.max(82, privacyLine.height + 54)
            Tap { app: "privacy" }
            Title { x: 16; y: 16; text: "PRIVACY REPORT" }
            Rectangle { x: 16; y: 44; width: 26; height: 26; radius: 13; color: "transparent"; border.width: 2; border.color: Theme.t.accent
                Rectangle { anchors.centerIn: parent; width: 10; height: 10; radius: 5; color: Theme.t.accent } }
            Label { id: privacyLine; x: 56; y: 40; width: parent.width - 72; wrapMode: Text.WordWrap; lineHeight: 1.2; font.pixelSize: 12
                text: Glance.privacy.line || "" }
        }
    }
    Component { id: nextCard
        Card {
            objectName: "nextCard"
            height: 46 + Math.max(1, Glance.upNext.length) * 46
            Title { x: 16; y: 16; text: "UP NEXT" }
            Label { visible: Glance.upNext.length === 0; x: 16; y: 40; width: parent.width - 32; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                text: "Nothing coming up. Events from Calendar and Reminders with a day show here." }
            Column { x: 16; y: 38; width: parent.width - 32; spacing: 6
                Repeater { model: Glance.upNext
                    Rectangle { required property var modelData; width: parent.width; height: 40; radius: Theme.t.radiusCard; color: Theme.t.hover
                        Tap { app: modelData.when.indexOf("Reminders") >= 0 ? "reminders" : "calendar" }
                        Column { x: 10; width: parent.width - 20; anchors.verticalCenter: parent.verticalCenter
                            Label { text: modelData.title; font.pixelSize: 13; width: parent.width; elide: Text.ElideRight }
                            Label { text: modelData.when; secondary: true; font.pixelSize: 11 } } } } }
        }
    }
    Component { id: clockCard
        Card {
            id: ck
            objectName: "clockCard"
            property date now: new Date()
            Timer { interval: 5000; repeat: true; running: true; onTriggered: ck.now = new Date() }
            height: 108
            Tap { app: "clock" }
            Label { x: 16; y: 8; text: Qt.formatTime(ck.now, Settings.clock24 ? "HH:mm" : "h:mm"); font.pixelSize: 54; font.weight: Font.Light }
            Label { visible: !Settings.clock24; anchors { right: parent.right; rightMargin: 16 } y: 22; text: Qt.formatTime(ck.now, "AP"); secondary: true; font.pixelSize: 14 }
            Label { x: 16; y: 76; text: Qt.formatDate(ck.now, "dddd, d MMMM"); secondary: true; font.pixelSize: 12 }
        }
    }
    Component { id: monthCard
        Card {
            id: mc
            objectName: "monthCard"
            property date today: new Date()
            Timer { interval: 600000; repeat: true; running: true; onTriggered: mc.today = new Date() }
            readonly property int first: Qt.locale().firstDayOfWeek % 7                        // 0 Sunday … 6 Saturday
            readonly property int offset: (new Date(today.getFullYear(), today.getMonth(), 1).getDay() - first + 7) % 7
            readonly property int days: new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate()
            readonly property int rows: Math.ceil((offset + days) / 7)
            height: 70 + rows * 26
            Tap { app: "calendar" }
            Title { x: 16; y: 16; text: Qt.formatDate(mc.today, "MMMM yyyy").toUpperCase() }
            Grid { x: 12; y: 38; columns: 7; width: parent.width - 24
                Repeater { model: 7
                    Label { required property int index; width: (mc.width - 24) / 7; height: 20; horizontalAlignment: Text.AlignHCenter
                        text: { var d = (mc.first + index) % 7, n = Qt.locale().dayName(d, Locale.NarrowFormat)
                                return /^\d+$/.test(n) || n === "" ? ["S", "M", "T", "W", "T", "F", "S"][d] : n }   // (a locale without names: "C")
                        secondary: true; font.pixelSize: 10; font.weight: Font.DemiBold } }
                Repeater { model: mc.offset + mc.days
                    Item { required property int index; width: (mc.width - 24) / 7; height: 26
                        readonly property int day: index - mc.offset + 1
                        readonly property bool isToday: day === mc.today.getDate()
                        Rectangle { visible: parent.isToday; anchors.centerIn: parent; width: 22; height: 22; radius: 11; color: Theme.t.accent }
                        Label { visible: parent.day > 0; anchors.centerIn: parent; text: parent.day; font.pixelSize: 11
                            font.weight: parent.isToday ? Font.DemiBold : Font.Normal; color: parent.isToday ? Theme.t.onAccent : Theme.t.text } } } }
        }
    }
    Component { id: systemCard
        Card {
            objectName: "systemCard"
            readonly property var s: Glance.system || ({})
            height: 156
            Tap { app: "monitor" }
            Title { x: 16; y: 16; text: "THIS COMPUTER" }
            Column { x: 16; y: 40; width: parent.width - 32; spacing: 10
                Column { width: parent.width; spacing: 4
                    Row { width: parent.width
                        Label { width: parent.width / 2; text: "Processor"; font.pixelSize: 12 }
                        Label { width: parent.width / 2; horizontalAlignment: Text.AlignRight; text: s.cpu !== undefined ? s.cpu + "%" : "…"; secondary: true; font.pixelSize: 12 } }
                    Bar { value: (s.cpu || 0) / 100; fill: "#4C8DFF" } }
                Column { width: parent.width; spacing: 4
                    Row { width: parent.width
                        Label { width: parent.width / 2; text: "Memory"; font.pixelSize: 12 }
                        Label { width: parent.width / 2; horizontalAlignment: Text.AlignRight; text: s.memTotal ? s.memUsed + " of " + s.memTotal + " GB" : "…"; secondary: true; font.pixelSize: 12 } }
                    Bar { value: s.memTotal ? s.memUsed / s.memTotal : 0; fill: "#B07CFF" } }
                Column { width: parent.width; spacing: 4
                    Row { width: parent.width
                        Label { width: parent.width / 2; text: "Drive"; font.pixelSize: 12 }
                        Label { width: parent.width / 2; horizontalAlignment: Text.AlignRight; text: s.diskTotal ? Math.round(s.diskFree) + " GB free" : "…"; secondary: true; font.pixelSize: 12 } }
                    Bar { value: s.diskTotal ? 1 - s.diskFree / s.diskTotal : 0; fill: "#3DD1C3" } } }
        }
    }
    Component { id: musicCard
        Card {
            id: mu
            objectName: "musicCard"
            readonly property var item: {
                var all = [Live.main].concat(Live.bubbles || [])
                for (var i = 0; i < all.length; i++) if (all[i] && String(all[i].id || "").indexOf("mpris:") === 0) return all[i]
                return null
            }
            height: item ? 96 : 82
            Title { x: 16; y: 16; text: "NOW PLAYING" }
            Label { visible: !mu.item; x: 16; y: 38; width: parent.width - 32; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                text: "Nothing's playing. Music, Podcasts, Spotify and videos in the browser show here while they play." }
            Rectangle { visible: !!mu.item; x: 16; y: 38; width: 44; height: 44; radius: 9; color: Theme.t.hover; clip: true
                Glyph { anchors.centerIn: parent; visible: art.status !== Image.Ready; name: "music"; size: 18 }
                Image { id: art; anchors.fill: parent; source: mu.item && mu.item.art ? mu.item.art : ""; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize: Qt.size(88, 88) } }
            Column { visible: !!mu.item; x: 70; y: 40; width: parent.width - 70 - 104
                Label { width: parent.width; text: mu.item ? mu.item.title : ""; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight }
                Label { width: parent.width; text: mu.item ? mu.item.sub : ""; secondary: true; font.pixelSize: 11; elide: Text.ElideRight } }
            Row { visible: !!mu.item; anchors { right: parent.right; rightMargin: 12 } y: 46; spacing: 4
                Repeater { model: [["prev", "previous"], [mu.item && mu.item.kind === "playing" ? "pause" : "play", "playpause"], ["next", "next"]]
                    Rectangle { required property var modelData; width: 30; height: 30; radius: 15; color: hit.containsMouse ? Theme.t.hover : "transparent"
                        Glyph { anchors.centerIn: parent; name: modelData[0]; size: 15 }
                        MouseArea { id: hit; anchors.fill: parent; hoverEnabled: true; enabled: !wg.editing; cursorShape: Qt.PointingHandCursor
                            onClicked: if (mu.item) Live.act(mu.item.id, modelData[1]) } } } }
        }
    }
    Component { id: photoCard
        Card {
            objectName: "photoCard"
            height: Glance.photo ? 190 : 82
            Tap { app: "photos" }
            Title { visible: !Glance.photo; x: 16; y: 16; text: "PHOTO" }
            Label { visible: !Glance.photo; x: 16; y: 38; width: parent.width - 32; wrapMode: Text.WordWrap; secondary: true; font.pixelSize: 12
                text: "Put pictures in your Pictures folder and one shows here, a new one each hour." }
            Rectangle { visible: !!Glance.photo; anchors.fill: parent; anchors.margins: 6; radius: 12; clip: true; color: "transparent"
                Image { anchors.fill: parent; source: Glance.photo; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize: Qt.size(540, 380) } }
        }
    }
}
