import QtQuick

// The desktop's wallpaper: the realm's live scene (the same one the sign-in screen shows), in the light or dark
// appearance. Just after signing in it is still moving, carried over from the sign-in screen, and it eases to rest;
// with Settings › Appearance › "Live wallpaper" it keeps moving (not with Reduce motion). Where the live wallpapers
// aren't installed or can't load, the realm's painted sky below stands in.
Item {
    id: paper
    property bool comingIn: typeof arriving !== "undefined" && arriving      // `arriving`: the shell was just started by signing in
    readonly property bool live: scene.status === Loader.Ready
    // something real is drawn: the picture, the scene (or its still), or the painted sky in their place
    readonly property bool drawn: made ? madeScene.status !== Loader.Loading
                                       : picture.status === Image.Loading ? false
                                       : live ? scene.item.shown !== false : true
    Timer { running: paper.comingIn; interval: 2600; onTriggered: paper.comingIn = false }
    // A window fills this screen (a game, a film, a filled window): nothing behind it needs to move (Shell.qml)
    property bool covered: false
    property bool forceMoving: false                      // the screen saver's scene moves whatever the desktop's does
    readonly property bool moving: !covered && (forceMoving || paper.comingIn || (Settings.liveWallpaper && !Settings.reduceMotion))
    // Settings › Appearance › Wallpaper: a live wallpaper someone made (CustomWallpaper.qml, next to the realms' scenes)
    readonly property bool made: Settings.wallpaper.slice(-15) === "/wallpaper.json"
    Loader {
        id: madeScene
        anchors.fill: parent
        z: 3
        active: paper.made && Theme.t.liveDir !== ""
        source: active ? Theme.t.liveDir + "CustomWallpaper.qml" : ""
        onLoaded: {
            item.spec = Qt.binding(function () { return Settings.wallpaperSpec })
            item.folder = Qt.binding(function () { return Settings.wallpaperSpec.folder || "" })
            item.moving = Qt.binding(function () { return paper.moving })
        }
    }
    // a picture of your own, over the realm's scene (which then isn't drawn)
    readonly property bool own: (Settings.wallpaper !== "" && !made && picture.status !== Image.Error) || (made && madeScene.status === Loader.Ready)
    Image {
        id: picture
        anchors.fill: parent
        z: 2
        visible: Settings.wallpaper !== "" && !paper.made && status === Image.Ready
        source: Settings.wallpaper && !paper.made ? "file://" + Settings.wallpaper : ""
        fillMode: Image.PreserveAspectCrop
        asynchronous: true; cache: false; smooth: true; mipmap: true
        sourceSize: Qt.size(paper.width * 2, paper.height * 2)
    }
    Loader {
        id: scene
        anchors.fill: parent
        z: 1
        active: Theme.t.liveDir !== "" && !(paper.own && (picture.status === Image.Ready || paper.made))
        source: Theme.t.liveDir ? Theme.t.liveDir + "LiveWallpaper.qml" : ""
        onLoaded: {
            item.realm = Qt.binding(function () { return Theme.t.realm })
            item.day = Qt.binding(function () { return Theme.t.dark ? 0 : 1 })
            item.tintA = Qt.binding(function () { return Theme.t.tintA })
            item.tintB = Qt.binding(function () { return Theme.t.tintB })
            item.glowA = Qt.binding(function () { return Theme.t.glowA })
            item.glowB = Qt.binding(function () { return Theme.t.glowB })
            item.pace = 0.6
            item.moving = Qt.binding(function () { return paper.moving })
        }
    }
    Rectangle {
        visible: !paper.live && !picture.visible && !paper.made
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0; color: Theme.t.tintA }
            GradientStop { position: 0.6; color: Theme.t.dark ? "#0C1014" : "#E9EEF1" }
            GradientStop { position: 1; color: Theme.t.tintB }
        }
    }
    Canvas {
        id: sky
        visible: !paper.live && !picture.visible && !paper.made
        anchors.fill: parent
        property string key: [Theme.t.dark, Theme.t.realm, Theme.t.glowA, Theme.t.tintA, Theme.t.tintB].join()   // what it's painted from
        onKeyChanged: requestPaint()
        onPaint: {
            var c = getContext("2d"), w = width, h = height
            c.clearRect(0, 0, w, h)
            var g = c.createRadialGradient(w * 0.2, h * 0.15, 0, w * 0.2, h * 0.15, w * 0.45)
            g.addColorStop(0, Qt.rgba(0.24, 0.84, 0.71, Theme.t.dark ? 0.30 : 0.45)); g.addColorStop(1, "transparent")
            c.fillStyle = g; c.fillRect(0, 0, w, h)
            // The arc: concentric strokes fading out from the glow pair.
            var cx = w * 1.02, cy = h * 0.42, r = h * 0.95
            for (var i = 0; i < 60; i++) {
                var t = i / 59
                c.beginPath(); c.arc(cx, cy, r + (t - 0.5) * 150, 0, Math.PI * 2)
                var a = Math.sin(t * Math.PI); a = a * a * (Theme.t.dark ? 0.16 : 0.13)
                c.strokeStyle = Qt.tint(Theme.t.glowA, Qt.rgba(0.48, 0.38, 1, t)); c.globalAlpha = a
                c.lineWidth = 6; c.stroke()
            }
            c.globalAlpha = Theme.t.dark ? 0.5 : 0.35
            c.fillStyle = Theme.t.dark ? "#0C1014" : "#DDE5EA"
            c.beginPath(); c.moveTo(0, h)
            var pts = [0.74, 0.60, 0.70, 0.52, 0.72, 0.58, 0.66, 0.50, 0.63, 0.70, 0.56, 0.68, 0.61, 0.72]
            for (var k = 0; k < pts.length; k++) c.lineTo(w * k / (pts.length - 1), h * pts[k] + h * 0.2)
            c.lineTo(w, h); c.closePath(); c.fill()
        }
    }
}
