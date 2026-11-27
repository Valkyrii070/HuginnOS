import QtQuick

// One widget on the sign-in screen (GreeterView.qml): frosted glass, its name small at the top and what it says at the
// bottom. What it shows is what the desktop last saw (huginn_signin_widgets.py). A widget its owner keeps private
// until they've signed in shows its name and a lock, nothing more.
Rectangle {
    id: tile
    property var widget: ({})
    property date now: new Date()
    property int battery: -1
    property real k: 1
    property Item behind: null
    property bool liveBehind: false
    property bool locking: false                     // the lock screen: you're signed in, it's locked
    readonly property var d: widget.data || ({})
    readonly property bool tall: height > 200 * k
    readonly property bool wide: width > 400 * k
    readonly property color ink: "#F5F7FA"
    readonly property color soft: Qt.rgba(0.96, 0.97, 0.98, 0.76)
    radius: Math.round(24 * k)
    color: Qt.rgba(0.08, 0.08, 0.13, frost.status === Loader.Ready ? 0.42 : 0.62)
    border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.16)
    Loader { id: frost; z: -1; anchors.fill: parent; active: tile.liveBehind && tile.behind !== null
        source: "GreeterFrost.qml"
        onLoaded: { item.behind = tile.behind; item.radius = Qt.binding(function () { return tile.radius })
            item.area = Qt.binding(function () { return Qt.rect(tile.parent.x + tile.x, tile.parent.y + tile.y, tile.width, tile.height) }) } }

    // ------------------------------------------------------------------------------------------------ what it says
    function hhmm(t) { return t ? t : "" }
    function ago(at) { return at > 0 ? (now.getTime() / 1000 - at) : 1e9 }
    function dayWord(iso) {
        var t = new Date(now.getFullYear(), now.getMonth(), now.getDate())
        var p = iso.split("-"); var d0 = new Date(+p[0], +p[1] - 1, +p[2])
        var n = Math.round((d0 - t) / 86400000)
        return n === 0 ? "" : n === 1 ? "Tomorrow" : Qt.formatDate(d0, "ddd")
    }
    readonly property var events: {
        var out = [], list = d.events || [], today = Qt.formatDate(now, "yyyy-MM-dd"), hm = Qt.formatTime(now, "HH:mm")
        for (var i = 0; i < list.length; i++) {
            var e = list[i]
            if (!e.date || e.date < today || (e.date === today && e.time && e.time < hm)) continue      // over already
            out.push(e)
        }
        return out
    }
    function eventWhen(e) { var w = dayWord(e.date); return (w ? w + " " : "") + (e.time || (w ? "" : "Today")) }
    function inMinutes(e) {
        if (!e.time || e.date !== Qt.formatDate(now, "yyyy-MM-dd")) return eventWhen(e)
        var p = e.time.split(":"), m = (+p[0]) * 60 + (+p[1]) - (now.getHours() * 60 + now.getMinutes())
        return e.time + (m < 60 ? " · in " + m + " minute" + (m === 1 ? "" : "s") : "")
    }
    readonly property var pcLines: {
        var l = []
        if (d.update) l.push(d.update)
        if ((d.downloads || 0) > 0 && ago(d.at) < 86400) l.push(d.downloads + (d.downloads === 1 ? " download" : " downloads") + " finished")
        if (battery >= 0) l.push("Battery " + battery + "%")
        return l
    }
    readonly property string label: {
        if (widget.private) return (widget.name || "").toUpperCase()
        if (widget.kind === "weather") return (d.place || "Weather").toUpperCase()
        if (widget.kind === "music") return "LAST PLAYED"
        return (widget.name || "").toUpperCase()
    }
    readonly property string big: {
        if (widget.private) return ""
        switch (widget.kind) {
        case "today": return events.length ? events[0].title : "Nothing coming up"
        case "weather": return !d.temp || ago(d.at) > 86400 ? "No recent forecast" : d.temp + (d.words ? " and " + d.words.toLowerCase() : "")
        case "pc": return pcLines.length ? pcLines[0] : "All quiet"
        case "music": return d.title || "Nothing played yet"
        }
        return ""
    }
    readonly property string small: {
        if (widget.private) return locking ? "Private while locked" : "Private until you sign in"
        switch (widget.kind) {
        case "today": return events.length ? inMinutes(events[0]) : "in Calendar or Reminders"
        case "weather":
            if (!d.temp || ago(d.at) > 86400) return "Weather updates it once you're signed in"
            var hi = d.high ? "High of " + d.high : ""
            return ago(d.at) > 3 * 3600 ? "As of " + Qt.formatTime(new Date(d.at * 1000), "h:mm ap") + (hi ? " · " + hi : "") : (hi || d.place)
        case "pc": return pcLines.length > 1 ? pcLines.slice(1).join(" · ") : (pcLines.length ? "" : "Nothing needs you")
        case "music": return d.sub || ""
        }
        return ""
    }

    // --------------------------------------------------------------------------------------------------- the layout
    Text { id: name; x: 22 * k; y: 20 * k; width: parent.width - 44 * k; elide: Text.ElideRight; text: tile.label; color: tile.soft
        font { family: "Inter"; pixelSize: Math.round(12 * k); weight: Font.DemiBold; letterSpacing: 2 } }

    // a list (Today, when it has room): when and what, a line each
    Column {
        visible: !widget.private && widget.kind === "today" && (tile.wide || tile.tall) && tile.events.length > 0
        x: 22 * k; y: name.y + name.height + 14 * k; width: parent.width - 44 * k; spacing: 6 * k
        Repeater { model: tile.events.slice(0, tile.tall ? (tile.wide ? 8 : 6) : 3)
            Row { required property var modelData; spacing: 14 * k; width: parent.width
                Text { width: 86 * k; text: tile.eventWhen(modelData); color: tile.soft; elide: Text.ElideRight
                    font { family: "Inter"; pixelSize: Math.round(15 * k) } }
                Text { width: parent.width - 100 * k; text: modelData.title; color: tile.ink; elide: Text.ElideRight
                    font { family: "Inter"; pixelSize: Math.round(15 * k); weight: Font.Medium } } } }
    }
    // the rest: one big line and one small one, at the bottom
    Column {
        visible: widget.private || !(widget.kind === "today" && (tile.wide || tile.tall) && tile.events.length > 0)
        x: 22 * k; width: parent.width - 44 * k; spacing: 4 * k
        anchors { bottom: parent.bottom; bottomMargin: 20 * k }
        Text { visible: tile.big !== ""; width: parent.width; text: tile.big; color: tile.ink; elide: Text.ElideRight; maximumLineCount: tile.tall ? 3 : 1; wrapMode: Text.Wrap
            font { family: "Inter"; pixelSize: Math.round(26 * k); weight: Font.Medium; letterSpacing: -0.3 } }
        Row { spacing: 8 * k; width: parent.width
            Canvas { id: lock; visible: tile.widget.private === true; width: 16 * k; height: 16 * k; anchors.verticalCenter: parent.verticalCenter
                onPaint: { var c = getContext("2d"), s = width / 24; c.reset(); c.scale(s, s); c.strokeStyle = tile.soft; c.lineWidth = 2; c.lineJoin = "round"
                    c.beginPath(); c.roundedRect(5, 11, 14, 10, 2, 2); c.moveTo(8, 11); c.lineTo(8, 8); c.arc(12, 8, 4, Math.PI, 0); c.lineTo(16, 11); c.stroke() } }
            Text { width: parent.width - (lock.visible ? lock.width + 8 * k : 0); text: tile.small; color: tile.soft; elide: Text.ElideRight
                font { family: "Inter"; pixelSize: Math.round(13 * k) } } }
    }
}
