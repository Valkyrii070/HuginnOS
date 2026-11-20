import QtQuick

// Appearance: light or dark, the realm (the colour of everything), the wallpaper (a picture, or a live one you made),
// the icons (a theme, or one app's own) and the pointer.
Column {
    id: pg
    width: parent ? parent.width : 600; spacing: 18
    readonly property var look: Backend.look
    function realmLabel(id) { var r = (Theme.t.realms || []).filter(function (x) { return x.id === id }); return r.length ? r[0].label : id }
    Component.onCompleted: { Backend.load("look"); pictures = Backend.recentPictures() }
    function choosePicture() {
        Picker.open("Choose a picture for the desktop", [["Pictures", "*.jpg *.jpeg *.png *.webp *.bmp *.gif *.avif *.heic *.jxl *.JPG *.JPEG *.PNG"]],
                    function (paths) { if (paths.length) Backend.setWallpaper(paths[0]) })
    }
    Row { spacing: 14
        Repeater { model: [["false", "Light", "#F4F5F8", "#DDE1E8", "#14171C"], ["true", "Dark", "#1B1E26", "#0E1015", "#F3F4F6"]]
            Column { required property var modelData; spacing: 8
                Rectangle { width: 200; height: 128; radius: 16; border.width: (Theme.t.dark ? "true" : "false") === modelData[0] ? 3 : 1
                    border.color: (Theme.t.dark ? "true" : "false") === modelData[0] ? Theme.t.accent : Theme.t.separator
                    gradient: Gradient { GradientStop { position: 0; color: modelData[2] } GradientStop { position: 1; color: modelData[3] } }
                    Rectangle { x: 18; y: 22; width: 120; height: 76; radius: 10; color: modelData[0] === "true" ? "#2A2E38" : "#FFFFFF"; border.width: 1; border.color: "#22000000"
                        Row { x: 8; y: 8; spacing: 4; Repeater { model: ["#FF5F57", "#FEBC2E", "#28C840"]; Rectangle { required property string modelData; width: 7; height: 7; radius: 4; color: modelData } } }
                        Rectangle { x: 8; y: 26; width: 70; height: 6; radius: 3; color: Theme.t.accent }
                        Rectangle { x: 8; y: 40; width: 96; height: 5; radius: 3; color: modelData[4]; opacity: 0.25 }
                        Rectangle { x: 8; y: 52; width: 80; height: 5; radius: 3; color: modelData[4]; opacity: 0.25 } }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Theme.setDark(modelData[0] === "true") } }
                Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData[1]; font.weight: (Theme.t.dark ? "true" : "false") === modelData[0] ? Font.DemiBold : Font.Normal } } } }
    SetCard { title: "Realm"; note: "A realm sets the accent colour, the window tint and the wallpaper everywhere at once: each has its own living scene. Each app still keeps its own colour."
        Flow { width: parent.width; padding: 14; spacing: 12
            Repeater { model: Theme.t.realms
                Column { required property var modelData; spacing: 6
                    objectName: "realm-" + modelData.id
                    Rectangle { width: 168; height: 105; radius: Theme.t.radiusTile; clip: true
                        border.width: Theme.t.realm === modelData.id ? 3 : 1; border.color: Theme.t.realm === modelData.id ? Theme.t.accent : Theme.t.separator
                        gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: modelData.a } GradientStop { position: 1; color: modelData.b } }
                        // the realm's own scene (a still of its live wallpaper)
                        Image { anchors.fill: parent; anchors.margins: parent.border.width; visible: status === Image.Ready; fillMode: Image.PreserveAspectCrop
                            source: Theme.t.liveDir ? Theme.t.liveDir + "stills/" + modelData.id + ".jpg" : ""; sourceSize.width: 336; asynchronous: true }
                        Rectangle { visible: pg.look.loginRealm === modelData.id; anchors { left: parent.left; bottom: parent.bottom; margins: 8 }
                            width: signLabel.width + 14; height: 20; radius: 10; color: "#B3101418"
                            Label { id: signLabel; anchors.centerIn: parent; text: "Sign-in screen"; color: "#FFFFFF"; font.pixelSize: 10; font.weight: Font.DemiBold } }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Theme.setRealm(modelData.id) } }
                    Label { text: modelData.label; anchors.horizontalCenter: parent.horizontalCenter; font.weight: Theme.t.realm === modelData.id ? Font.DemiBold : Font.Normal } } } } }
    property var pictures: []
    readonly property bool madeOne: Settings.wallpaper.slice(-15) === "/wallpaper.json"
    readonly property var liveList: pg.look.live || []
    readonly property var usedLive: liveList.filter(function (w) { return w.path === Settings.wallpaper })[0] || null
    property string wallTab: madeOne ? "made" : Settings.wallpaper !== "" ? "picture" : "scene"
    SetCard { title: "Wallpaper"
        note: pg.wallTab === "picture" ? "Your picture is kept in Huginn's own folder, so moving or deleting the original doesn't take it off the desktop. The sign-in screen keeps the realm's scene."
            : pg.wallTab === "made" ? "Make one from a realm's scene in your own colours, a picture or a video, with snow, rain, stars and more moving over it. Share… in the maker saves one as a file to give someone; Add from a file puts one you were given here." : ""
        SetRow { glyph: "image"; tile: "#7C3AED"; title: "On the desktop"
            sub: pg.madeOne ? (pg.usedLive ? pg.usedLive.name : "A live wallpaper you made") : Settings.wallpaper !== "" ? Settings.wallpaper.split("/").pop() : "The realm's living scene"
            SetChoice { objectName: "wallChoice"; each: 112; options: [["scene", "Realm's scene"], ["picture", "A picture"], ["made", "Made by you"]]; value: pg.wallTab
                onPicked: function (v) { pg.wallTab = v; if (v === "scene") Backend.setWallpaper(""); else if (v === "picture" && pg.pictures.length === 0) pg.choosePicture() } } }
        // your pictures
        Flow { visible: pg.wallTab === "picture"; x: 16; width: parent.width - 32; spacing: 8; topPadding: 4; bottomPadding: 12
            Repeater { model: pg.pictures
                Rectangle { required property var modelData; width: 96; height: 60; radius: 8; clip: true; color: Theme.t.hover
                    border.width: !pg.madeOne && Settings.wallpaper.split("/").pop() === modelData.path.split("/").pop() ? 3 : 0; border.color: Theme.t.accent
                    Image { anchors.fill: parent; anchors.margins: parent.border.width; source: modelData.url; sourceSize.width: 192; fillMode: Image.PreserveAspectCrop; asynchronous: true }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Backend.setWallpaper(modelData.path) } } }
            Pressable { width: 96; height: 60; radius: 8; color: hovered ? Theme.t.hover : (Theme.t.dark ? "#14FFFFFF" : "#0C141E28"); onClicked: pg.choosePicture()
                Column { anchors.centerIn: parent; spacing: 2
                    Glyph { anchors.horizontalCenter: parent.horizontalCenter; name: "folder"; size: 16 }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Other…"; font.pixelSize: 11 } } } }
        // live wallpapers you made
        Flow { visible: pg.wallTab === "made"; x: 16; width: parent.width - 32; spacing: 10; topPadding: 4; bottomPadding: 12
            Repeater { model: pg.liveList
                Column { required property var modelData; spacing: 4; objectName: "live-" + modelData.id
                    Rectangle { width: 136; height: 77; radius: 10; clip: true; color: Theme.t.hover
                        border.width: Settings.wallpaper === modelData.path ? 3 : 0; border.color: Theme.t.accent
                        gradient: Gradient { GradientStop { position: 0; color: modelData.spec.colours.tintA } GradientStop { position: 1; color: modelData.spec.colours.glowB } }
                        Image { anchors.fill: parent; anchors.margins: parent.border.width; visible: modelData.still !== ""; source: modelData.still; sourceSize.width: 272
                            fillMode: Image.PreserveAspectCrop; asynchronous: true; cache: false }
                        MouseArea { id: liveHit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Backend.useLiveWallpaper(modelData.id) }
                        Rectangle { visible: liveHit.containsMouse || editHit.containsMouse; anchors { right: parent.right; top: parent.top; margins: 6 } width: 26; height: 26; radius: 13; color: "#B3101418"
                            Glyph { anchors.centerIn: parent; name: "edit"; size: 13; ink: "#FFFFFF" }
                            MouseArea { id: editHit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { win.makerId = modelData.id; win.go("livemaker") } } } }
                    Label { width: 136; text: modelData.name; font.pixelSize: 11; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter
                        font.weight: Settings.wallpaper === modelData.path ? Font.DemiBold : Font.Normal } } }
            Pressable { objectName: "makeLive"; width: 136; height: 77; radius: 10; color: hovered ? Qt.alpha(Theme.t.accent, 0.25) : Qt.alpha(Theme.t.accent, 0.14); border.width: 1; border.color: Qt.alpha(Theme.t.accent, 0.6)
                onClicked: { win.makerId = ""; win.go("livemaker") }
                Column { anchors.centerIn: parent; spacing: 3
                    Glyph { anchors.horizontalCenter: parent.horizontalCenter; name: "plus"; size: 18 }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Make one"; font.pixelSize: 12; font.weight: Font.DemiBold } } }
            Pressable { width: 136; height: 77; radius: 10; color: hovered ? Theme.t.hover : (Theme.t.dark ? "#14FFFFFF" : "#0C141E28")
                onClicked: Picker.open("Add a live wallpaper you were given", [["Huginn wallpapers", "*.huginn-wallpaper"]], function (paths) { if (paths.length) Backend.addLiveWallpaper(paths[0]) })
                Column { anchors.centerIn: parent; spacing: 3
                    Glyph { anchors.horizontalCenter: parent.horizontalCenter; name: "download"; size: 16 }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Add from a file…"; font.pixelSize: 11 } } } }
        SetRow { glyph: "sparkle"; tile: Theme.t.accent; title: "Live wallpaper"
            sub: pg.madeOne ? "It moves on the desktop. It rests while a window fills the screen, and stays still with this off."
               : "The realm's scene keeps moving on the desktop too, slowly. It always moves on the sign-in screen, and comes to rest after you sign in. Uses a little more power."
            enabled: Settings.wallpaper === "" || pg.madeOne; opacity: enabled ? 1 : 0.5
            Toggle { objectName: "liveToggle"; on: Settings.liveWallpaper; enabled: !Settings.reduceMotion && (Settings.wallpaper === "" || pg.madeOne); onToggled: function (v) { Settings.set("liveWallpaper", v ? "true" : "false") } } }
        SetRow { visible: Settings.reduceMotion; glyph: "info"; tile: "#64748B"; title: "Reduce motion is on"; sub: "The wallpaper stays still everywhere, as Accessibility asks." }
        SetRow { glyph: "lock"; tile: "#0EA5E9"; title: "Sign-in screen"; sub: pg.look.loginRealm === Theme.t.realm ? "It wears " + pg.realmLabel(Theme.t.realm) + ", like your desktop."
                                                                                   : "It wears " + pg.realmLabel(pg.look.loginRealm || "aurora") + ". Everyone on this computer sees it."
            Btn { objectName: "useOnLogin"; text: "Use " + pg.realmLabel(Theme.t.realm); visible: pg.look.loginRealm !== Theme.t.realm && pg.look.canChange !== false
                onClicked: Backend.setLoginRealm(Theme.t.realm) } } }

    // ---------------------------------------------------------------- icons
    SetCard { title: "Icons"; note: "Huginn's own puts every app on smoked glass. Another set changes apps' and folders' icons everywhere; some apps show it after they're opened again. Get more from gnome-look.org (a .tar.gz or .tar.xz), then Add from a File."
        Flow { x: 12; width: parent.width - 24; spacing: 10; topPadding: 12; bottomPadding: 6
            Repeater { model: pg.look.iconThemes || []
                Pressable { required property var modelData; objectName: "icons-" + modelData.id; width: 220; height: 92; radius: 12
                    readonly property bool chosen: (pg.look.iconTheme || "Huginn") === modelData.id
                    color: chosen ? Qt.alpha(Theme.t.accent, 0.18) : hovered ? Theme.t.hover : (Theme.t.dark ? "#10FFFFFF" : "#0A141E28")
                    border.width: chosen ? 2 : 1; border.color: chosen ? Theme.t.accent : Theme.t.separator
                    onClicked: Backend.setIconTheme(modelData.id)
                    Row { x: 10; y: 10; spacing: 3
                        Repeater { model: modelData.samples.slice(0, 7)
                            Image { required property string modelData; width: 26; height: 26; source: modelData; sourceSize: Qt.size(52, 52); asynchronous: true; fillMode: Image.PreserveAspectFit; smooth: true } } }
                    Label { x: 12; y: 50; width: parent.width - 50; text: modelData.id === "Huginn" ? "Huginn's own" : modelData.name; font.weight: Font.DemiBold; elide: Text.ElideRight }
                    Label { x: 12; y: 68; width: parent.width - 50; text: modelData.user ? "Added by you" : modelData.id === "Huginn" ? "Every app on smoked glass" : "Came with Huginn OS"; secondary: true; font.pixelSize: 10; elide: Text.ElideRight }
                    Glyph { visible: parent.chosen; anchors { right: parent.right; bottom: parent.bottom; margins: 10 } name: "check"; size: 16; ink: Theme.t.accent }
                    Seg { visible: modelData.user && !parent.chosen; anchors { right: parent.right; bottom: parent.bottom; margins: 6 } icon: "trash"; tip: "Remove"
                        onClicked: { var id = modelData.id, n = modelData.name; win.confirm("Remove “" + n + "”?", "These icons go from this computer. You can add them again from their file.", "Remove", function () { Backend.removeTheme(id) }) } } } } }
        SetRow { title: "Add icons from a file…"; sub: "A theme you downloaded"; chevron: true; onClicked: pg.addTheme()
            Btn { text: "Find More"; onClicked: Backend.findThemes("icons") } }
        SetRow { title: "Change an app's icon…"; sub: "Give any app a picture of your own"; chevron: true
            onClicked: win.pick("Change which app's icon", Backend.iconAppChoices(), "", function (id) { pg.iconFor = id; pg.chooseIcon() }) }
        Repeater { model: pg.look.appIcons || []
            SetRow { required property var modelData; title: modelData.name; sub: "Your icon"; picture: modelData.icon
                Row { spacing: 8
                    Btn { text: "Change"; onClicked: { pg.iconFor = modelData.id; pg.chooseIcon() } }
                    Btn { text: "Its Own Again"; onClicked: Backend.resetAppIcon(modelData.id) } } } }
        SetRow { title: "Put your pictures on Huginn's glass"; sub: "Off: an app's new icon is your picture just as it is"
            Toggle { on: pg.onGlass; onToggled: function (v) { pg.onGlass = v } } }
    }
    property string iconFor: ""
    property bool onGlass: true
    function chooseIcon() {
        Picker.open("Choose a picture for its icon", [["Pictures", "*.png *.svg *.jpg *.jpeg *.webp *.PNG *.SVG *.JPG"]],
                    function (paths) { if (paths.length && pg.iconFor) Backend.setAppIcon(pg.iconFor, paths[0], pg.onGlass) })
    }
    function addTheme() {
        Picker.open("Add icons or pointers from a file", [["Themes", "*.tar.gz *.tgz *.tar.xz *.txz *.tar.bz2 *.tar.zst *.tar *.zip"]],
                    function (paths) { if (paths.length) Backend.addTheme(paths[0]) })
    }

    // ---------------------------------------------------------------- the pointer
    SetCard { title: "Pointer"; note: "The new pointer shows at once over the desktop and Huginn's apps; some other apps show it after they're opened again."
        Flow { x: 12; width: parent.width - 24; spacing: 10; topPadding: 12; bottomPadding: 6
            Repeater { model: pg.look.pointerThemes || []
                Pressable { required property var modelData; objectName: "pointer-" + modelData.id; width: 220; height: 84; radius: 12
                    readonly property bool chosen: (pg.look.pointerTheme || "breeze_cursors") === modelData.id
                    color: chosen ? Qt.alpha(Theme.t.accent, 0.18) : hovered ? Theme.t.hover : (Theme.t.dark ? "#10FFFFFF" : "#0A141E28")
                    border.width: chosen ? 2 : 1; border.color: chosen ? Theme.t.accent : Theme.t.separator
                    onClicked: Backend.setPointerTheme(modelData.id)
                    // shown on a mid grey, so dark pointers and light ones both show
                    Rectangle { x: 8; y: 8; width: parent.width - 16; height: 40; radius: 8; color: "#7A808C"
                        Row { anchors.centerIn: parent; spacing: 10
                            Repeater { model: modelData.previews || []
                                Image { required property string modelData; width: 28; height: 28; source: modelData; sourceSize: Qt.size(32, 32); smooth: true; fillMode: Image.PreserveAspectFit } } } }
                    Label { x: 12; y: 54; width: parent.width - 56; text: modelData.name; font.weight: Font.DemiBold; elide: Text.ElideRight }
                    Glyph { visible: parent.chosen; anchors { right: parent.right; bottom: parent.bottom; margins: 10 } name: "check"; size: 16; ink: Theme.t.accent }
                    Seg { visible: modelData.user && !parent.chosen; anchors { right: parent.right; bottom: parent.bottom; margins: 6 } icon: "trash"; tip: "Remove"
                        onClicked: { var id = modelData.id, n = modelData.name; win.confirm("Remove “" + n + "”?", "This pointer goes from this computer. You can add it again from its file.", "Remove", function () { Backend.removeTheme(id) }) } } } } }
        SetRow { title: "Size"
            SetChoice { each: 54; options: [["24", "S"], ["32", "M"], ["48", "L"], ["64", "XL"], ["96", "XXL"]]; value: String(pg.look.pointerSize || 24)
                onPicked: function (v) { Backend.setPointerSize(Number(v)) } } }
        SetRow { title: "Add a pointer from a file…"; sub: "A pointer theme you downloaded"; chevron: true; onClicked: pg.addTheme()
            Btn { text: "Find More"; onClicked: Backend.findThemes("pointers") } }
    }
}
