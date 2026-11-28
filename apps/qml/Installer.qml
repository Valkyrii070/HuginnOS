import QtQuick
import QtQuick.Window

// Install Huginn OS: the dock path. The installer fills the screen with the night sky; its own top bar says what it
// is and what the computer is doing (the network, the power, help seeing and typing); the step sits in a glass card in
// the middle; and the steps are islands in a dock at the bottom, each keeping its answer, the one you're on raised and
// lit, and the orb at the end installs (after everything is shown once more). Nothing is touched until then. Then the
// screen becomes the installation: what's done, what's being done, the line of light, and what's waiting.
Window {
    id: win
    title: "Install Huginn OS"; visible: true; color: "#0B0D10"
    width: 1280; height: 800; minimumWidth: 1000; minimumHeight: 680
    visibility: demo ? Window.Windowed : Window.FullScreen
    readonly property string stepId: Backend.steps[Backend.step].id
    readonly property bool setup: Backend.state === "setup"
    readonly property var acc: Backend.access
    readonly property color teal: "#43D9B8"
    readonly property color amber: "#FFC46B"
    readonly property color ink2: acc.contrast ? "#DCE1E6" : "#9AA3AD"
    readonly property color glassC: Qt.rgba(20 / 255, 24 / 255, 29 / 255, acc.contrast ? 0.94 : 0.78)
    readonly property color edge: Qt.rgba(1, 1, 1, acc.contrast ? 0.28 : 0.10)
    readonly property real big: acc.bigger ? 1.16 : 1
    readonly property int still: acc.motion ? 0 : 1
    property string langFilter: ""
    property string layoutFilter: ""
    property string openWifi: ""
    property bool wifiOpen: false
    property bool showLog: false
    property bool showAccess: false
    property string encOne: ""
    property string encTwo: ""
    Connections { target: Backend; function onSaid(text, bad) { toast.say(text, bad) } }
    property string tpmPin: ""
    function pushEncryption() { Backend.setEncrypt(Backend.encrypt, win.encOne === win.encTwo ? win.encOne : "") }
    function indexOf(id) { for (var i = 0; i < Backend.steps.length; i++) if (Backend.steps[i].id === id) return i; return -1 }

    // ================================================================ the sky
    Image { anchors.fill: parent; source: Backend.sky; fillMode: Image.PreserveAspectCrop; asynchronous: true; cache: true }
    Rectangle { anchors.fill: parent
        gradient: Gradient { GradientStop { position: 0; color: Qt.rgba(0.03, 0.04, 0.055, 0.40) } GradientStop { position: 0.42; color: Qt.rgba(0.03, 0.04, 0.055, 0.18) }
                             GradientStop { position: 1; color: Qt.rgba(0.03, 0.04, 0.055, 0.74) } } }

    // a glass pill (the top bar's, the dock's islands)
    component Pill: Rectangle { radius: height / 2; color: win.glassC; border.width: 1; border.color: win.edge }
    // a switch with its words: on the welcome step, in Extras, in Safety
    component Switch: Item {
        id: sw
        property string title: ""
        property string line: ""
        property bool on: false
        property bool enabled_: true
        signal flipped(bool v)
        width: parent ? parent.width : 300; height: Math.max(46, swText.height + 16); opacity: enabled_ ? 1 : 0.5
        Toggle { id: swT; anchors.verticalCenter: parent.verticalCenter; on: sw.on; enabled: sw.enabled_; onToggled: function (v) { sw.flipped(v) } }
        Column { id: swText; anchors { left: swT.right; leftMargin: 12; right: parent.right; verticalCenter: parent.verticalCenter } spacing: 2
            Label { width: parent.width; text: sw.title; font.weight: Font.DemiBold; wrapMode: Text.WordWrap }
            Label { visible: sw.line !== ""; width: parent.width; text: sw.line; color: win.ink2; font.pixelSize: 12; wrapMode: Text.WordWrap } } }
    // a choice of one of several (the media formats, encryption, Windows' copy or link)
    component Choice: Rectangle {
        id: ch
        property string title: ""
        property string line: ""
        property bool on: false
        signal picked()
        width: parent ? parent.width : 300; height: chCol.height + 22; radius: 13
        color: on ? Qt.rgba(67 / 255, 217 / 255, 184 / 255, 0.13) : (chHit.containsMouse ? Qt.rgba(1, 1, 1, 0.07) : Qt.rgba(1, 1, 1, 0.04))
        border.width: on ? 1.5 : 1; border.color: on ? win.teal : win.edge
        Rectangle { id: chDot; x: 13; y: 13; width: 18; height: 18; radius: 9; color: "transparent"; border.width: ch.on ? 5.5 : 1.5; border.color: ch.on ? win.teal : win.ink2 }
        Column { id: chCol; x: 42; y: 11; width: parent.width - 56; spacing: 2
            Label { width: parent.width; text: ch.title; font.weight: Font.DemiBold; wrapMode: Text.WordWrap }
            Label { visible: ch.line !== ""; width: parent.width; text: ch.line; color: win.ink2; font.pixelSize: 12; wrapMode: Text.WordWrap } }
        MouseArea { id: chHit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: ch.picked() } }
    // a heading inside a step
    component Small: Label { font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1.1; font.capitalization: Font.AllUppercase; color: win.ink2 }

    // ================================================================ the top bar: what this is, and the computer now
    Pill { x: 12; y: 12; height: 34; width: nameRow.width + 26
        Row { id: nameRow; x: 9; anchors.verticalCenter: parent.verticalCenter; spacing: 9
            Rectangle { width: 20; height: 20; radius: 10; anchors.verticalCenter: parent.verticalCenter
                gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: "#7BF0D6" } GradientStop { position: 1; color: "#7B61FF" } } }
            Label { text: "Install Huginn OS"; font.pixelSize: 13; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter } } }
    Pill { id: statusPill; anchors { right: parent.right; rightMargin: 12 } y: 12; height: 34; width: statusRow.width + 28
        Row { id: statusRow; x: 14; anchors.verticalCenter: parent.verticalCenter; spacing: 14
            Item { width: netRow.width; height: 26; anchors.verticalCenter: parent.verticalCenter
                Row { id: netRow; spacing: 6; anchors.verticalCenter: parent.verticalCenter
                    Glyph { name: Backend.wifi.wired ? "ethernet" : (Backend.wifi.connected ? "wifi" : "wifioff"); size: 14; anchors.verticalCenter: parent.verticalCenter }
                    Label { text: Backend.wifi.wired ? "Cable" : (Backend.wifi.connected || "Offline"); font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter } }
                MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.PointingHandCursor; onClicked: { win.wifiOpen = true; Backend.goTo(win.indexOf("check")); Backend.refreshWifi() } } }
            Row { spacing: 6; anchors.verticalCenter: parent.verticalCenter; visible: Backend.check.some(function (r) { return r.key === "power" })
                Glyph { name: "battery"; size: 14; anchors.verticalCenter: parent.verticalCenter }
                Label { font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter
                    text: { var r = Backend.check.filter(function (x) { return x.key === "power" })[0]; return r ? (r.state === "ok" ? "Plugged in" : "On battery") : "" } } }
            Rectangle { objectName: "accessButton"; width: 26; height: 26; radius: 13; anchors.verticalCenter: parent.verticalCenter
                color: win.showAccess ? Qt.rgba(67 / 255, 217 / 255, 184 / 255, 0.25) : "transparent"
                Glyph { anchors.centerIn: parent; name: "user"; size: 15 }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: win.showAccess = !win.showAccess } } } }
    // help seeing, hearing and typing, from the top bar at any step
    Rectangle { id: accessPanel; objectName: "accessPanel"; visible: win.showAccess; z: 30; anchors { right: parent.right; rightMargin: 12 } y: 54; width: 330
        height: accCol.height + 26; radius: 18; color: win.glassC; border.width: 1; border.color: win.edge
        Column { id: accCol; x: 14; y: 13; width: parent.width - 28; spacing: 2
            Small { text: "Help seeing, hearing and typing"; bottomPadding: 6 }
            Switch { visible: win.acc.hasReader; title: "Read the screen aloud"; on: win.acc.reader; onFlipped: function (v) { Backend.setAccess("reader", v) } }
            Switch { title: "Everything bigger"; on: win.acc.bigger; onFlipped: function (v) { Backend.setAccess("bigger", v) } }
            Switch { title: "Stronger contrast"; line: "Here, while installing"; on: win.acc.contrast; onFlipped: function (v) { Backend.setAccess("contrast", v) } }
            Switch { title: "Less motion"; on: win.acc.motion; onFlipped: function (v) { Backend.setAccess("motion", v) } }
            Switch { visible: win.acc.hasOsk; title: "On-screen keyboard"; on: win.acc.osk; onFlipped: function (v) { Backend.setAccess("osk", v) } }
            Label { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; color: win.ink2; topPadding: 6
                text: "What's turned on here stays on in Huginn once it's installed. Super + Alt + S reads the screen at any point." } } }

    // ================================================================ the step, in its glass card
    Rectangle {
        id: card; objectName: "card"
        visible: win.setup
        width: Math.min(980, win.width - 180); height: win.height - 72 - 150
        x: (win.width - width) / 2; y: 72; radius: 22; color: win.glassC; border.width: 1; border.color: win.edge
        scale: win.big; transformOrigin: Item.Top
        Rectangle { anchors.fill: parent; radius: parent.radius; color: "transparent"; border.width: 0
            gradient: Gradient { GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0.035) } GradientStop { position: 0.3; color: "transparent" } } }
        Item {
            id: page
            x: 34; y: 26; width: parent.width - 68; height: parent.height - 26 - 70
            readonly property var headings: ({
                welcome: ["Welcome to Huginn OS", "Velkommen · Bienvenue · Willkommen · Bienvenido · ようこそ"],
                keyboard: ["Keyboard", "Pick the layout printed on your keys, then try it below."],
                check: ["Is this computer ready?", "Huginn looked it over before asking you anything else."],
                disk: ["Where should Huginn live?", "Nothing changes until you press Install."],
                extras: ["Make it play, open and run everything", "Some of this can't ship inside Huginn, but you can add it now in one go."],
                apps: ["What should come with it?", "Pick what you'll use. The rest stays in the App Store, one click away."],
                windows: ["Bring your things from Windows", "Windows keeps everything; Huginn gets a copy."],
                you: ["Who will use this computer?", "You can add more people later in Settings › Users."],
                time: ["Time zone", "The clock and calendar follow it. It changes by itself when you travel, if you like, later."],
                safety: ["Keep it safe", "If this computer is lost or stolen, nobody can read what's on it."],
                ready: ["Ready to install", "Look this over. Installing takes about ten minutes; you can keep trying Huginn meanwhile."] })
            Label { id: stepNo; visible: win.stepId !== "welcome"; text: win.stepId === "ready" ? "Last look" : "Step " + Backend.step + " of " + (Backend.steps.length - 2)
                font.pixelSize: 12; font.weight: Font.DemiBold; font.letterSpacing: 1; font.capitalization: Font.AllUppercase; color: win.teal }
            Label { id: heading; objectName: "heading"; anchors { top: stepNo.visible ? stepNo.bottom : parent.top; topMargin: 6 } text: page.headings[win.stepId][0]; font.pixelSize: 30; font.weight: Font.Light }
            Label { id: subheading; anchors { top: heading.bottom; topMargin: 4 } width: parent.width; text: page.headings[win.stepId][1]; color: win.ink2; font.pixelSize: 14; wrapMode: Text.WordWrap }
            Item { id: body; anchors { top: subheading.bottom; topMargin: 20; left: parent.left; right: parent.right; bottom: parent.bottom }

                // ---------------------------------------------------- welcome: the language, try or install, help from the first second
                Item { visible: win.stepId === "welcome"; anchors.fill: parent
                    Item { id: langBox; width: parent.width * 0.48; height: parent.height
                        TextBox { id: langSearch; width: parent.width; placeholder: "Search languages"; onEdited: win.langFilter = text.toLowerCase() }
                        Rectangle { anchors { top: langSearch.bottom; topMargin: 10; left: parent.left; right: parent.right; bottom: parent.bottom }
                            radius: 14; color: Qt.rgba(0, 0, 0, 0.22); border.width: 1; border.color: win.edge; clip: true
                            ListView { id: langList; anchors.fill: parent; anchors.margins: 6; spacing: 2; clip: true
                                Connections { target: Backend; function onLangChanged() { var i = langList.model.findIndex(function (l) { return l.id === Backend.language }); if (i >= 0) langList.positionViewAtIndex(i, ListView.Contain) } }
                                model: Backend.languages.filter(function (l) { return !win.langFilter || l.label.toLowerCase().indexOf(win.langFilter) >= 0 || l.id.toLowerCase().indexOf(win.langFilter) >= 0 })
                                delegate: Rectangle { required property var modelData; width: langList.width; height: 36; radius: 10
                                    objectName: "lang-" + modelData.id
                                    color: modelData.id === Backend.language ? Qt.rgba(67 / 255, 217 / 255, 184 / 255, 0.22) : (lh.containsMouse ? Qt.rgba(1, 1, 1, 0.07) : "transparent")
                                    border.width: modelData.id === Backend.language ? 1 : 0; border.color: win.teal
                                    Label { x: 14; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; font.weight: modelData.id === Backend.language ? Font.DemiBold : Font.Normal }
                                    MouseArea { id: lh; anchors.fill: parent; hoverEnabled: true; onClicked: Backend.setLanguage(modelData.id) } } } } }
                    Column { x: langBox.width + 22; width: parent.width - x; spacing: 12
                        Repeater { model: [{ id: "try", glyph: "eye", title: "Try it first", line: "Use Huginn from this drive. Nothing on the computer changes. Install whenever you like, from the dock." },
                                           { id: "install", glyph: "download", title: "Install Huginn OS", line: "About nine short questions, then it puts itself in place while you wait or keep trying it." }]
                            Rectangle { required property var modelData
                                objectName: "choose-" + modelData.id
                                width: parent.width; height: 92; radius: 18
                                color: modelData.id === "install" ? Qt.rgba(67 / 255, 217 / 255, 184 / 255, wc.containsMouse ? 0.24 : 0.15) : (wc.containsMouse ? Qt.rgba(1, 1, 1, 0.08) : Qt.rgba(1, 1, 1, 0.04))
                                border.width: modelData.id === "install" ? 1.5 : 1; border.color: modelData.id === "install" ? win.teal : win.edge
                                Row { x: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 14
                                    Rectangle { width: 44; height: 44; radius: 14; anchors.verticalCenter: parent.verticalCenter
                                        color: modelData.id === "install" ? win.teal : Qt.rgba(1, 1, 1, 0.08)
                                        Glyph { anchors.centerIn: parent; name: modelData.glyph; size: 22; ink: modelData.id === "install" ? "#06231D" : Theme.t.icon } }
                                    Column { width: parent.parent.width - 96; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                                        Label { text: modelData.title; font.pixelSize: 16; font.weight: Font.DemiBold }
                                        Label { width: parent.width; text: modelData.line; color: win.ink2; wrapMode: Text.WordWrap; font.pixelSize: 12 } } }
                                MouseArea { id: wc; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: modelData.id === "try" ? Qt.quit() : Backend.next() } } }
                        Rectangle { width: parent.width; height: helpCol.height + 24; radius: 16; color: Qt.rgba(0, 0, 0, 0.2); border.width: 1; border.color: win.edge
                            Column { id: helpCol; x: 14; y: 12; width: parent.width - 28; spacing: 6
                                Label { text: "Help seeing, hearing and typing, before anything else"; font.weight: Font.DemiBold }
                                Label { text: "Stays on in Huginn once it's installed"; color: win.ink2; font.pixelSize: 12 }
                                Flow { objectName: "helpChips"; width: parent.width; spacing: 6; topPadding: 4
                                    Repeater { model: [["reader", "Read the screen aloud"], ["bigger", "Everything bigger"], ["contrast", "Stronger contrast"], ["motion", "Less motion"], ["osk", "On-screen keyboard"]]
                                        Rectangle { required property var modelData
                                            visible: (modelData[0] !== "reader" || win.acc.hasReader) && (modelData[0] !== "osk" || win.acc.hasOsk)
                                            readonly property bool on: !!win.acc[modelData[0]]
                                            width: chipL.width + 24; height: 30; radius: 15
                                            color: on ? Qt.rgba(67 / 255, 217 / 255, 184 / 255, 0.2) : Qt.rgba(1, 1, 1, 0.07); border.width: 1; border.color: on ? win.teal : win.edge
                                            Label { id: chipL; anchors.centerIn: parent; text: modelData[1] + (parent.on ? " · on" : ""); font.pixelSize: 12 }
                                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Backend.setAccess(modelData[0], !parent.on) } } } }
                                Label { width: parent.width; wrapMode: Text.WordWrap; color: win.ink2; font.pixelSize: 11
                                    text: "Can't see this? Press Super + Alt + S at any point to hear it read out. Keyboard layout: " + Backend.layoutLabel } } } }
                }

                // ---------------------------------------------------- keyboard
                Item { visible: win.stepId === "keyboard"; anchors.fill: parent
                    TextBox { id: laySearch; width: parent.width; placeholder: "Search layouts"; onEdited: win.layoutFilter = text.toLowerCase() }
                    Rectangle { anchors { top: laySearch.bottom; topMargin: 10; left: parent.left; right: parent.right; bottom: tryIt.top; bottomMargin: 16 }
                        radius: 14; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine; clip: true
                        ListView { id: layList; anchors.fill: parent; anchors.margins: 6; spacing: 2; clip: true
                            model: Backend.layouts.filter(function (l) { return !win.layoutFilter || l.label.toLowerCase().indexOf(win.layoutFilter) >= 0 || l.id === win.layoutFilter })
                            function showChosen() { var i = model.findIndex(function (l) { return l.id === Backend.layout }); if (i >= 0) positionViewAtIndex(i, ListView.Center) }
                            onVisibleChanged: if (visible) Qt.callLater(showChosen)
                            onHeightChanged: if (visible) Qt.callLater(showChosen)
                            delegate: Rectangle { required property var modelData; width: layList.width; height: 36; radius: 10
                                color: modelData.id === Backend.layout ? Theme.t.accent : (kh.containsMouse ? Theme.t.hover : "transparent")
                                Label { x: 14; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; color: modelData.id === Backend.layout ? Theme.t.onAccent : Theme.t.text
                                    font.weight: modelData.id === Backend.layout ? Font.DemiBold : Font.Normal }
                                Label { anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } text: modelData.id; font.family: Theme.t.fontMono; font.pixelSize: 11
                                    color: modelData.id === Backend.layout ? Theme.t.onAccent : Theme.t.text_secondary }
                                MouseArea { id: kh; anchors.fill: parent; hoverEnabled: true; onClicked: Backend.setLayout(modelData.id) } } } }
                    Column { id: tryIt; anchors.bottom: parent.bottom; width: parent.width; spacing: 6
                        Label { text: "Try it"; secondary: true; font.pixelSize: 12 }
                        TextBox { objectName: "tryKeys"; width: parent.width; placeholder: "Type here: æøå, äöü, @, € and the rest" } }
                }


                // ---------------------------------------------------- is this computer ready?
                Item { visible: win.stepId === "check"; anchors.fill: parent
                Item { id: wifiPanel; visible: win.wifiOpen; anchors.fill: parent; z: 4
                    Column { width: parent.width; spacing: 10
                        Rectangle { visible: !!Backend.wifi.wired; width: parent.width; height: 52; radius: 14; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                            Row { x: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 12
                                Glyph { name: "check"; size: 18; ink: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
                                Label { text: "Connected by cable"; anchors.verticalCenter: parent.verticalCenter; font.weight: Font.DemiBold } } }
                        Rectangle { width: parent.width; height: Math.min(wifiCol.height + 12, body.height - (Backend.wifi.wired ? 62 : 0)); radius: 14; color: Theme.t.group
                            border.width: 1; border.color: Theme.t.islandLine; clip: true
                            Flickable { anchors.fill: parent; anchors.margins: 6; contentHeight: wifiCol.height; clip: true
                                Column { id: wifiCol; width: parent.width; spacing: 2
                                    Label { visible: !(Backend.wifi.networks || []).length; x: 10; topPadding: 12; bottomPadding: 12
                                        text: Backend.wifi.available === false ? "This computer has no Wi‑Fi." : "Looking for Wi‑Fi networks…"; secondary: true }
                                    Repeater { model: Backend.wifi.networks || []
                                        Rectangle { required property var modelData; width: wifiCol.width; radius: 10
                                            objectName: "wifi-" + modelData.ssid
                                            readonly property bool open: win.openWifi === modelData.ssid
                                            height: open ? 92 : 40
                                            color: wh.containsMouse || open ? Theme.t.hover : "transparent"
                                            Behavior on height { NumberAnimation { duration: 140 } }
                                            Row { x: 12; y: 8; spacing: 12
                                                Glyph { name: "wifi"; size: 18; opacity: 0.35 + modelData.signal / 150; anchors.verticalCenter: parent.verticalCenter }
                                                Label { text: modelData.ssid; anchors.verticalCenter: parent.verticalCenter; font.weight: modelData.ssid === Backend.wifi.connected ? Font.DemiBold : Font.Normal }
                                                Glyph { visible: modelData.secure; name: "lock"; size: 13; opacity: 0.6; anchors.verticalCenter: parent.verticalCenter } }
                                            Label { visible: modelData.ssid === Backend.wifi.connected; anchors { right: parent.right; rightMargin: 14; top: parent.top; topMargin: 11 } text: "Connected"; color: Theme.t.accent; font.pixelSize: 12 }
                                            MouseArea { id: wh; width: parent.width; height: 40; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                                onClicked: { if (modelData.ssid === Backend.wifi.connected) return
                                                    if (modelData.secure) { win.openWifi = parent.open ? "" : modelData.ssid; if (win.openWifi) Qt.callLater(function () { wifiPass.focusIn() }) }
                                                    else Backend.connectWifi(modelData.ssid, "") } }
                                            Row { visible: parent.open; x: 42; y: 46; spacing: 8
                                                TextBox { id: wifiPass; width: 280; secret: true; placeholder: "Password for " + modelData.ssid; onAccepted: { Backend.connectWifi(modelData.ssid, text); text = ""; win.openWifi = "" } }
                                                Btn { primary: true; text: "Join"; anchors.verticalCenter: parent.verticalCenter; onClicked: { Backend.connectWifi(modelData.ssid, wifiPass.text); wifiPass.text = ""; win.openWifi = "" } } } } } } } }
                        Row { spacing: 8
                            Btn { text: "Look again"; onClicked: Backend.refreshWifi() } } }
                }
                    Flickable { visible: !win.wifiOpen; anchors.fill: parent; contentHeight: Math.max(checkL.height, checkR.height) + 10; clip: true; boundsBehavior: Flickable.StopAtBounds
                        Column { id: checkL; objectName: "checkList"; width: parent.width * 0.56; spacing: 8
                            Small { text: "Before installing" }
                            Repeater { model: Backend.check
                                Rectangle { required property var modelData; width: checkL.width; height: ckCol.height + 20; radius: 13
                                    color: modelData.state === "warn" ? Qt.rgba(1, 0.7, 0.25, 0.10) : Qt.rgba(1, 1, 1, 0.04)
                                    border.width: 1; border.color: modelData.state === "warn" ? Qt.rgba(1, 0.77, 0.42, 0.5) : win.edge
                                    Rectangle { x: 12; y: 12; width: 22; height: 22; radius: 11
                                        color: modelData.state === "ok" ? win.teal : modelData.state === "warn" ? win.amber : Qt.rgba(1, 1, 1, 0.18)
                                        Label { anchors.centerIn: parent; text: modelData.state === "ok" ? "✓" : modelData.state === "warn" ? "!" : "i"; color: "#06231D"; font.weight: Font.Bold; font.pixelSize: 12 } }
                                    Column { id: ckCol; x: 46; y: 10; width: parent.width - 58; spacing: 2
                                        Label { width: parent.width; text: modelData.title; font.weight: Font.DemiBold; wrapMode: Text.WordWrap }
                                        Label { width: parent.width; text: modelData.line; color: win.ink2; font.pixelSize: 12; wrapMode: Text.WordWrap }
                                        Btn { visible: modelData.action === "wifi"; text: "Join Wi‑Fi"; onClicked: { win.wifiOpen = true; Backend.refreshWifi() } } } } } }
                        Column { id: checkR; x: checkL.width + 22; width: parent.width - x; spacing: 8
                            Small { text: "What works out of the box" }
                            Repeater { model: Backend.works
                                Row { required property var modelData; spacing: 10; width: checkR.width
                                    Rectangle { width: 20; height: 20; radius: 10; color: win.teal
                                        Label { anchors.centerIn: parent; text: "✓"; color: "#06231D"; font.weight: Font.Bold; font.pixelSize: 11 } }
                                    Column { width: parent.width - 30; spacing: 1
                                        Label { width: parent.width; text: modelData.title; font.weight: Font.DemiBold; wrapMode: Text.WordWrap }
                                        Label { width: parent.width; text: modelData.line; color: win.ink2; font.pixelSize: 12; wrapMode: Text.WordWrap } } } }
                            Label { visible: Backend.check.some(function (r) { return r.state === "warn" }); width: parent.width; wrapMode: Text.WordWrap; color: win.amber; font.pixelSize: 12; topPadding: 10
                                text: "You can still go on: what's marked is to stay safe, and the step it matters for says so again." } } }
                    Btn { visible: win.wifiOpen; anchors { right: parent.right; bottom: parent.bottom } text: "Done"; onClicked: win.wifiOpen = false }
                }

                // ---------------------------------------------------- extras: media formats, fonts and drivers
                Flickable { visible: win.stepId === "extras"; anchors.fill: parent; contentHeight: exGrid.height + 10; clip: true; boundsBehavior: Flickable.StopAtBounds
                    Item { id: exGrid; width: parent.width; height: Math.max(exL.height, exR.height)
                        Column { id: exL; objectName: "codecs"; width: parent.width * 0.58; spacing: 8
                            Row { width: parent.width
                                Label { text: "Media formats"; font.pixelSize: 16; font.weight: Font.DemiBold; width: parent.width * 0.45 }
                                Label { width: parent.width * 0.55; horizontalAlignment: Text.AlignRight; text: "MP4, H.264, H.265, AAC, MP3, DVDs and more"; color: win.ink2; font.pixelSize: 12; elide: Text.ElideRight } }
                            Choice { objectName: "codecs-download"; title: "Download them from Ubuntu · recommended"; on: Backend.extras.codecs === "download"
                                line: "Ubuntu's ready-made packages (the restricted extras), kept up to date with Software Update."; onPicked: Backend.setExtra("codecs", "download") }
                            Choice { objectName: "codecs-build"; title: "Build them on this computer"; on: Backend.extras.codecs === "build"
                                line: "Huginn fetches FFmpeg's source and builds it with every format, in the background after the first start. Slower, and you see exactly what goes in."
                                onPicked: Backend.setExtra("codecs", "build") }
                            Choice { objectName: "codecs-none"; title: "Not now"; on: Backend.extras.codecs === "none"
                                line: "Open formats (WebM, AV1, Opus, FLAC) still play. Add the rest later in Settings."; onPicked: Backend.setExtra("codecs", "none") }
                            Label { width: parent.width; wrapMode: Text.WordWrap; color: win.ink2; font.pixelSize: 11
                                text: "Some formats are covered by patents in some countries. You decide whether you may use them where you live." } }
                        Column { id: exR; x: exL.width + 20; width: parent.width - x; spacing: 6
                            Label { text: "Fonts for documents"; font.pixelSize: 16; font.weight: Font.DemiBold }
                            Switch { objectName: "msfonts"; title: "Microsoft's core fonts"; line: "Arial, Times New Roman, Verdana and others, so Word and PowerPoint files look right. You accept Microsoft's licence."
                                on: !!Backend.extras.msfonts; onFlipped: function (v) { Backend.setExtra("msfonts", v) } }
                            Switch { title: "Fonts for every script"; line: "Chinese, Japanese, Korean, Arabic, Indic and emoji, for pages that use them."
                                on: !!Backend.extras.scripts; onFlipped: function (v) { Backend.setExtra("scripts", v) } }
                            Item { width: 1; height: 8 }
                            Label { text: "Drivers for this computer"; font.pixelSize: 16; font.weight: Font.DemiBold }
                            Switch { visible: !!Backend.extras.hasNvidia; title: "NVIDIA's own driver"; line: "Faster for games. With Secure Boot on, you confirm a key once at the next start."
                                on: !!Backend.extras.nvidia; onFlipped: function (v) { Backend.setExtra("nvidia", v) } }
                            Label { visible: !Backend.extras.hasNvidia; width: parent.width; wrapMode: Text.WordWrap; color: win.ink2; font.pixelSize: 12
                                text: Backend.works.length ? Backend.works[0].title + ": built into Huginn. Nothing to add." : "This computer's graphics are built into Huginn." }
                            Switch { title: "Printers and scanners"; line: "The makers' drivers, for when one is plugged in."
                                on: !!Backend.extras.printers; onFlipped: function (v) { Backend.setExtra("printers", v) } }
                            Label { width: parent.width; wrapMode: Text.WordWrap; font.pixelSize: 11; topPadding: 6; color: Backend.extras.online ? win.ink2 : win.amber
                                text: Backend.extras.online ? "These come in the background after the first start, so installing isn't any slower."
                                                            : "Not online now: these come the first time Huginn is online, in the background." } } }
                }

                // ---------------------------------------------------- disk
                Flickable { id: diskFlick; visible: win.stepId === "disk"; anchors.fill: parent; contentHeight: diskCol.height + 10; clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    // a choice that opens more below it (beside Windows' slider, the partitions) scrolls it into view
                    readonly property string seen: Backend.mode + "/" + Backend.shrink.state
                    onSeenChanged: if (visible && (Backend.mode === "shrink" || Backend.mode === "manual")) diskReveal.restart()
                    Timer { id: diskReveal; interval: 60; onTriggered: { var end = Math.max(0, diskFlick.contentHeight - diskFlick.height); if (diskFlick.contentY < end) diskScroll.to = end, diskScroll.restart() } }
                    NumberAnimation { id: diskScroll; target: diskFlick; property: "contentY"; duration: 260; easing.type: Easing.OutCubic }
                    Column { id: diskCol; width: parent.width; spacing: 14
                        // the disks, when there's more than one
                        Flow { visible: Backend.disks.length > 1; width: parent.width; spacing: 8
                            Repeater { model: Backend.disks
                                Rectangle { required property var modelData
                                    objectName: "disk-" + modelData.path
                                    width: dRow.width + 26; height: 40; radius: 12
                                    color: modelData.path === Backend.disk ? Qt.alpha(Theme.t.accent, 0.2) : (dh.containsMouse ? Theme.t.hover : Theme.t.group)
                                    border.width: 1; border.color: modelData.path === Backend.disk ? Theme.t.accent : Theme.t.islandLine
                                    Row { id: dRow; anchors.centerIn: parent; spacing: 8
                                        Glyph { name: modelData.removable ? "download" : "disc"; size: 16; anchors.verticalCenter: parent.verticalCenter }
                                        Label { text: modelData.model; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                                        Label { text: modelData.sizeText; secondary: true; anchors.verticalCenter: parent.verticalCenter } }
                                    MouseArea { id: dh; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Backend.setDisk(modelData.path) } } } }
                        Label { visible: Backend.disks.length === 0; text: "No disk was found to put Huginn OS on."; color: Theme.t.danger }
                        // the disk as it will be: a bar of what's on it, with Huginn OS where it would go
                        Column { visible: !!Backend.chosenDisk.path; width: parent.width; spacing: 6
                            Row { spacing: 8
                                Label { text: Backend.chosenDisk.model || ""; font.weight: Font.DemiBold }
                                Label { text: (Backend.chosenDisk.sizeText || "") + " · " + (Backend.chosenDisk.kind || "") + (Backend.chosenDisk.systems && Backend.chosenDisk.systems.length ? " · has " + Backend.chosenDisk.systems.join(" and ") : ""); secondary: true } }
                            Rectangle { objectName: "diskBar"; width: parent.width; height: 34; radius: 10; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine; clip: true
                                Row { anchors.fill: parent; anchors.margins: 3; spacing: 2
                                    Repeater { model: Backend.mode === "erase" ? [{ label: "Huginn OS", holds: "Huginn", share: 1, sizeText: Backend.chosenDisk.sizeText }]
                                                    : Backend.mode === "shrink" && Backend.shrink.state === "ok" ? (Backend.chosenDisk.bar || []).reduce(function (out, b) {
                                                          if (b.holds === "Windows" && Math.abs(b.share - Backend.chosenDisk.shrinkSize / Backend.chosenDisk.size) < 0.001) {
                                                              out.push({ label: b.label, holds: "Windows", share: b.share - Backend.shrink.huginnFraction, sizeText: Backend.shrink.windowsText })
                                                              out.push({ label: "Huginn OS", holds: "Huginn", share: Backend.shrink.huginnFraction, sizeText: Backend.shrink.huginnText })
                                                          } else out.push(b)
                                                          return out }, [])
                                                    : (Backend.chosenDisk.bar || [])
                                        Rectangle { required property var modelData
                                            readonly property bool ours: modelData.holds === "Huginn" || (modelData.free && Backend.mode === "free") || (Backend.mode === "manual" && modelData.label === Backend.root)
                                            width: Math.max(6, (parent.width - 2 * ((Backend.chosenDisk.bar || []).length)) * modelData.share); height: parent.height; radius: 7
                                            color: ours ? Theme.t.accent : modelData.free ? "transparent" : ({ Windows: "#2F6FDB", Linux: "#E8833A", EFI: "#6B7280", macOS: "#A3A3A3" }[modelData.holds] || "#4B5563")
                                            border.width: modelData.free && !ours ? 1 : 0; border.color: Theme.t.separator
                                            Label { anchors.centerIn: parent; visible: parent.width > 90; text: (parent.ours ? "Huginn OS" : modelData.label) + "  " + modelData.sizeText; font.pixelSize: 11
                                                color: parent.ours ? Theme.t.onAccent : "#FFFFFF"; font.weight: Font.DemiBold } } } } } }
                        // how to use it
                        Repeater {
                            model: [{ id: "shrink", glyph: "split", title: "Install beside " + (Backend.chosenDisk.shrinkLabel || "Windows"),
                                      line: Backend.chosenDisk.bitlocker && !Backend.chosenDisk.shrinkPart ? "Windows is locked with BitLocker here. Turn BitLocker off in Windows first, or shrink it there (Disk Management)."
                                          : "Windows gives Huginn OS some of its room. Its files stay; you'll choose which to start each time.",
                                      ok: !!Backend.chosenDisk.shrinkPart, show: !!Backend.chosenDisk.shrinkPart || !!Backend.chosenDisk.bitlocker },
                                    { id: "erase", glyph: "trash", title: "Erase the disk and install Huginn OS",
                                      line: "Everything on " + (Backend.chosenDisk.model || "the disk") + " is deleted" + (Backend.chosenDisk.systems && Backend.chosenDisk.systems.length ? ", " + Backend.chosenDisk.systems.join(" and ") + " too." : ".")
                                            + (Backend.chosenDisk.mounted ? " (It's open in Files now; it will be closed first.)" : ""), ok: true },
                                    { id: "free", glyph: "split", title: Backend.chosenDisk.systems && Backend.chosenDisk.systems.length ? "Use the free space beside " + Backend.chosenDisk.systems.join(" and ") : "Use the free space",
                                      line: !Backend.chosenDisk.freeBytes ? "There's no free space on this disk. Make room first (Windows: Disk Management › Shrink Volume)."
                                          : Backend.chosenDisk.systems && Backend.chosenDisk.systems.length ? Backend.chosenDisk.freeText + " of free space. You'll choose which system to start each time the computer starts."
                                          : Backend.chosenDisk.freeText + " of free space. What's already on the disk stays as it is.",
                                      ok: (Backend.chosenDisk.freeBytes || 0) >= 20e9 },
                                    { id: "manual", glyph: "sliders", title: "Choose partitions myself", line: "For people who've already made room: pick the partition for Huginn OS.", ok: true }]
                            Rectangle { required property var modelData
                                objectName: "mode-" + modelData.id
                                readonly property bool on: Backend.mode === modelData.id
                                // an empty disk: "use the free space" would be the same as erasing it
                                visible: !(modelData.id === "free" && !(Backend.chosenDisk.parts && Backend.chosenDisk.parts.length)) && modelData.show !== false
                                        && !(modelData.id === "free" && !Backend.chosenDisk.freeBytes && !!Backend.chosenDisk.shrinkPart)
                                width: diskCol.width; height: 64; radius: 16; opacity: modelData.ok ? 1 : 0.5
                                color: on ? Qt.alpha(Theme.t.accent, 0.16) : (mh.containsMouse ? Theme.t.hover : Theme.t.group)
                                border.width: 1; border.color: on ? Theme.t.accent : Theme.t.islandLine
                                Row { x: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 14
                                    Rectangle { width: 20; height: 20; radius: 10; anchors.verticalCenter: parent.verticalCenter; color: "transparent"; border.width: parent.parent.on ? 6 : 1.5; border.color: parent.parent.on ? Theme.t.accent : Theme.t.separator }
                                    Glyph { name: modelData.glyph; size: 20; anchors.verticalCenter: parent.verticalCenter }
                                    Column { anchors.verticalCenter: parent.verticalCenter; spacing: 2; width: diskCol.width - 110
                                        Label { text: modelData.title; font.weight: Font.DemiBold }
                                        Label { width: parent.width; text: modelData.line; secondary: true; font.pixelSize: 12; elide: Text.ElideRight } } }
                                MouseArea { id: mh; anchors.fill: parent; hoverEnabled: true; enabled: modelData.ok; cursorShape: Qt.PointingHandCursor; onClicked: Backend.setMode(modelData.id) } } }
                        // beside Windows: how much room it gives
                        Rectangle { objectName: "shrinkBox"; visible: Backend.mode === "shrink"; width: parent.width; height: shrinkCol.height + 28; radius: 16; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                            Column { id: shrinkCol; x: 16; y: 14; width: parent.width - 32; spacing: 12
                                Label { visible: Backend.shrink.state !== "ok"; width: parent.width; wrapMode: Text.Wrap
                                    text: Backend.shrink.state === "probing" ? "Looking at how much room Windows can give\u2026 (this can take a minute)" : Backend.shrink.why; secondary: Backend.shrink.state === "probing" }
                                Row { visible: Backend.shrink.state === "ok"; width: parent.width
                                    Label { width: parent.width / 2; text: (Backend.chosenDisk.shrinkLabel || "Windows") + " keeps " + Backend.shrink.windowsText; font.weight: Font.DemiBold }
                                    Label { width: parent.width / 2; horizontalAlignment: Text.AlignRight; text: "Huginn OS gets " + Backend.shrink.huginnText; font.weight: Font.DemiBold; color: Theme.t.accent } }
                                Item { objectName: "shrinkSlider"; visible: Backend.shrink.state === "ok"; width: parent.width; height: 28
                                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 8; radius: 4; color: "#2F6FDB" }
                                    Rectangle { anchors.verticalCenter: parent.verticalCenter; anchors.right: parent.right; width: parent.width * Backend.shrink.share; height: 8; radius: 4; color: Theme.t.accent }
                                    Rectangle { x: parent.width * (1 - Backend.shrink.share) - width / 2; anchors.verticalCenter: parent.verticalCenter; width: 24; height: 24; radius: 12; color: "white"; border.width: 1; border.color: Theme.t.islandLine }
                                    MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.SizeHorCursor
                                        function set(x) { Backend.setShare(1 - Math.max(0, Math.min(1, x / width))) }
                                        onPressed: function (m) { set(m.x) } onPositionChanged: function (m) { if (pressed) set(m.x) } } }
                                Label { visible: Backend.shrink.state === "ok"; width: parent.width; wrapMode: Text.Wrap; font.pixelSize: 12; secondary: true
                                    text: "Windows needs " + Backend.shrink.windowsLeast + " for what's on it now. Shrinking moves some of its files and can take a while; back up anything important first." } } }
                        // choosing partitions
                        Column { visible: Backend.mode === "manual"; width: parent.width; spacing: 4
                            Repeater { model: Backend.chosenDisk.parts || []
                                Rectangle { required property var modelData; width: diskCol.width; height: 44; radius: 12; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                                    Row { x: 14; anchors.verticalCenter: parent.verticalCenter; spacing: 12
                                        Label { text: modelData.path; font.family: Theme.t.fontMono; width: 150; anchors.verticalCenter: parent.verticalCenter }
                                        Label { text: modelData.holds + (modelData.label ? " · " + modelData.label : ""); width: 220; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter }
                                        Label { text: modelData.sizeText; secondary: true; width: 70; anchors.verticalCenter: parent.verticalCenter } }
                                    Row { anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter } spacing: 6
                                        Btn { pill: true; primary: Backend.root === modelData.path; text: "Huginn OS"; enabled: modelData.size >= 20e9; onClicked: Backend.setRoot(modelData.path) }
                                        Btn { visible: Backend.firmware === "uefi" && modelData.holds === "EFI"; pill: true; primary: Backend.efi === modelData.path; text: "EFI"; onClicked: Backend.setEfi(modelData.path) } } } }
                            Label { text: "The partition for Huginn OS is formatted. The EFI partition is shared, not formatted."; secondary: true; font.pixelSize: 12 } }
                    }
                }

                // the disk step's scroll bar, and a fade where there's more below
                Rectangle { visible: diskFlick.visible && diskFlick.contentHeight > diskFlick.height + 4; z: 3
                    anchors { right: parent.right; rightMargin: -10 } width: 4; radius: 2; color: Theme.t.text_secondary; opacity: 0.45
                    y: diskFlick.visibleArea.yPosition * diskFlick.height; height: Math.max(30, diskFlick.visibleArea.heightRatio * diskFlick.height) }
                Rectangle { visible: diskFlick.visible && diskFlick.contentY < diskFlick.contentHeight - diskFlick.height - 4; z: 2
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: 28
                    gradient: Gradient { GradientStop { position: 0; color: "transparent" } GradientStop { position: 1; color: Qt.alpha(Theme.t.appBase, 0.85) } } }

                // ---------------------------------------------------- what comes with it
                Flickable { visible: win.stepId === "apps"; anchors.fill: parent; contentHeight: appCol.height + 10; clip: true; boundsBehavior: Flickable.StopAtBounds
                    Column { id: appCol; width: parent.width; spacing: 8
                        Repeater { model: [["Essentials", "Always", "Everything for the day: the browser, Files, Mail, Calendar, Notes, Photos, Music, Settings and more."],
                                           ["Pro Studio", "Included", "For making things: Easel for pictures, Code, Clips for films and Tempo for music."],
                                           ["Office", "Included", "Writer, Sheets and Slides, which open Word, Excel and PowerPoint files."],
                                           ["Games", "Included", "Your Steam, Epic, GOG and Amazon games in one place, with Game Mode for full speed."]]
                            Rectangle { required property var modelData; width: appCol.width; height: 58; radius: 13; color: Qt.rgba(1, 1, 1, 0.04); border.width: 1; border.color: win.edge
                                Column { x: 14; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 130; spacing: 2
                                    Label { text: modelData[0]; font.weight: Font.DemiBold }
                                    Label { width: parent.width; text: modelData[2]; color: win.ink2; font.pixelSize: 12; elide: Text.ElideRight } }
                                Rectangle { anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } width: incl.width + 18; height: 24; radius: 12; color: Qt.rgba(67 / 255, 217 / 255, 184 / 255, 0.15)
                                    Label { id: incl; anchors.centerIn: parent; text: modelData[1]; color: win.teal; font.pixelSize: 12; font.weight: Font.DemiBold } } } }
                        Rectangle { width: appCol.width; height: gdev.height + 20; radius: 13; color: Qt.rgba(1, 1, 1, 0.04); border.width: 1; border.color: Backend.apps.gamedev ? win.teal : win.edge
                            Switch { id: gdev; objectName: "gamedev"; x: 14; y: 10; width: parent.width - 28; title: "Game development"
                                line: "Godot, and Code's tools for games ready to go: Git with large files, compilers for Unreal Engine's builds, and containers."
                                on: !!Backend.apps.gamedev; onFlipped: function (v) { Backend.setApp("gamedev", v) } } }
                        Rectangle { width: appCol.width; height: fh.height + 20; radius: 13; color: Qt.rgba(1, 1, 1, 0.04); border.width: 1; border.color: win.edge
                            Switch { id: fh; x: 14; y: 10; width: parent.width - 28; title: "Flathub in the App Store"
                                line: "Thousands more apps, straight from the people who make them, each in its own sandbox, next to Ubuntu's."
                                on: Backend.apps.flathub !== false; onFlipped: function (v) { Backend.setApp("flathub", v) } } }
                        Rectangle { objectName: "windowsApps"; visible: (Backend.apps.windowsApps || []).length > 0; width: appCol.width; height: waCol.height + 22; radius: 13
                            color: Qt.rgba(1, 1, 1, 0.04); border.width: 1; border.color: win.edge
                            Column { id: waCol; x: 14; y: 11; width: parent.width - 28; spacing: 8
                                Row { width: parent.width
                                    Column { width: parent.width - 130; spacing: 2
                                        Label { text: "Bring the apps you use on Windows?"; font.weight: Font.DemiBold }
                                        Label { width: parent.width; wrapMode: Text.WordWrap; color: win.ink2; font.pixelSize: 12
                                            text: "Found in Windows. Huginn adds their Linux versions from Flathub after the first start." } }
                                    Btn { text: "Add all " + (Backend.apps.windowsApps || []).length; onClicked: Backend.setApp("allWindowsApps", true) } }
                                Flow { width: parent.width; spacing: 6
                                    Repeater { model: Backend.apps.windowsApps || []
                                        Rectangle { required property var modelData; width: waL.width + 24; height: 30; radius: 15
                                            color: modelData.on ? Qt.rgba(67 / 255, 217 / 255, 184 / 255, 0.2) : Qt.rgba(1, 1, 1, 0.07); border.width: 1; border.color: modelData.on ? win.teal : win.edge
                                            Label { id: waL; anchors.centerIn: parent; text: (modelData.on ? "✓ " : "+ ") + modelData.name; font.pixelSize: 12 }
                                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Backend.setApp("windowsApp", modelData.key) } } } } } } }
                }

                // ---------------------------------------------------- your things from Windows
                Flickable { visible: win.stepId === "windows"; anchors.fill: parent; contentHeight: wCol.height + 10; clip: true; boundsBehavior: Flickable.StopAtBounds
                    Column { id: wCol; width: parent.width; spacing: 10
                        Label { visible: Backend.windows.state === "probing" || Backend.windows.state === ""; text: "Looking in Windows (it's only read)…"; color: win.ink2 }
                        Label { visible: Backend.windows.state === "no"; width: parent.width; wrapMode: Text.WordWrap; color: win.amber; text: Backend.windows.problem || "Nothing was found to bring." }
                        Flow { visible: Backend.windows.state === "ok" && Backend.windows.users.length > 1; width: parent.width; spacing: 6
                            Repeater { model: Backend.windows.users || []
                                Btn { required property var modelData; pill: true; primary: Backend.windows.user === modelData; text: modelData + "'s things"; onClicked: Backend.setBring("user", modelData) } } }
                        Label { visible: Backend.windows.state === "ok"; width: parent.width; wrapMode: Text.WordWrap; color: win.ink2
                            text: "Found " + Backend.windows.user + "'s account. " + (Backend.windows.sizeText ? Backend.windows.sizeText + " to bring" : "") + (Backend.windows.counted ? "" : " (still counting: there's more)") }
                        Grid { visible: Backend.windows.state === "ok" && !Backend.windows.skip; columns: 2; columnSpacing: 10; rowSpacing: 8; width: parent.width
                            Repeater { model: Backend.windows.folders || []
                                Rectangle { required property var modelData; width: (wCol.width - 10) / 2; height: 54; radius: 13
                                    color: modelData.on ? Qt.rgba(67 / 255, 217 / 255, 184 / 255, 0.12) : Qt.rgba(1, 1, 1, 0.04); border.width: modelData.on ? 1.5 : 1; border.color: modelData.on ? win.teal : win.edge
                                    Rectangle { x: 13; anchors.verticalCenter: parent.verticalCenter; width: 18; height: 18; radius: 5; color: parent.modelData.on ? win.teal : "transparent"; border.width: 1.5; border.color: parent.modelData.on ? win.teal : win.ink2
                                        Label { anchors.centerIn: parent; visible: parent.parent.modelData.on; text: "✓"; color: "#06231D"; font.pixelSize: 11; font.weight: Font.Bold } }
                                    Column { x: 42; anchors.verticalCenter: parent.verticalCenter; spacing: 1
                                        Label { text: modelData.name; font.weight: Font.DemiBold }
                                        Label { text: modelData.files + (modelData.files === 1 ? " file" : " files") + (modelData.sizeText ? " · " + modelData.sizeText : ""); color: win.ink2; font.pixelSize: 12 } }
                                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Backend.setBring("folder", modelData.key) } } } }
                        Small { visible: Backend.windows.state === "ok" && !Backend.windows.skip; text: "How"; topPadding: 4 }
                        Row { visible: Backend.windows.state === "ok" && !Backend.windows.skip; width: parent.width; spacing: 10
                            Choice { width: (parent.width - 10) / 2; title: "Copy"; line: "After Huginn's first start, in the background, so installing isn't any slower. Nothing is overwritten."
                                on: Backend.windows.how === "copy"; onPicked: Backend.setBring("how", "copy") }
                            Choice { width: (parent.width - 10) / 2; title: "Use them where they are"; line: "Windows' folders show in Files, read-only, and stay in Windows."
                                on: Backend.windows.how === "link"; onPicked: Backend.setBring("how", "link") } }
                        Switch { visible: Backend.windows.state === "ok" && !Backend.windows.skip && !!Backend.windows.bookmarks && Backend.windows.bookmarks.count > 0
                            objectName: "bring-bookmarks"
                            title: "Bookmarks into Huginn (" + (Backend.windows.bookmarks || {}).count + " from " + (Backend.windows.bookmarks || {}).browsers + ")"
                            on: !!(Backend.windows.bookmarks || {}).on; onFlipped: function (v) { Backend.setBring("bookmarks", v) } }
                        Switch { visible: Backend.windows.state === "ok"; title: "Don't bring anything"; on: !!Backend.windows.skip; onFlipped: function (v) { Backend.setBring("skip", v) } }
                        Label { visible: !!Backend.windows.fastStartup; width: parent.width; wrapMode: Text.WordWrap; color: win.amber; font.pixelSize: 12
                            text: "Windows' Fast Startup is on: shut Windows down fully before the first start of Huginn, or your things can't be read then." } }
                }

                // ---------------------------------------------------- you
                Item { visible: win.stepId === "you"; anchors.fill: parent
                    Rectangle { id: face; width: 96; height: 96; radius: 48
                        gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.t.glowA } GradientStop { position: 1; color: Theme.t.glowB } }
                        Rectangle { anchors.fill: parent; anchors.margins: 3; radius: width / 2; color: Qt.darker(Theme.t.accent, 2.6)
                            Label { anchors.centerIn: parent; color: "#FFFFFF"; font.pixelSize: 34; font.weight: Font.DemiBold
                                text: { var n = (Backend.you.realName || "").trim().split(/\s+/); return n[0] ? (n[0][0] + (n.length > 1 ? n[n.length - 1][0] : "")).toUpperCase() : "" } }
                            Glyph { visible: !(Backend.you.realName || "").trim(); anchors.centerIn: parent; name: "user"; size: 40; ink: "#FFFFFF" } } }
                    Grid { anchors { left: face.right; leftMargin: 28; right: parent.right } columns: 2; columnSpacing: 12; rowSpacing: 12
                        property int w: (width - 12) / 2
                        Column { spacing: 5; Label { text: "Your name"; secondary: true; font.pixelSize: 12 }
                            TextBox { objectName: "realName"; width: parent.parent.w; placeholder: "Your full name"; onEdited: Backend.setYou("realName", text) } }
                        Column { spacing: 5; Label { text: "User name"; secondary: true; font.pixelSize: 12 }
                            TextBox { objectName: "userName"; width: parent.parent.w; mono: true; text: Backend.you.name || ""; onEdited: Backend.setYou("name", text) } }
                        Column { spacing: 5; Label { text: "Password"; secondary: true; font.pixelSize: 12 }
                            TextBox { objectName: "password"; width: parent.parent.w; secret: true; onEdited: Backend.setYou("password", text) }
                            Row { spacing: 4; Repeater { model: 4; Rectangle { required property int index; width: (parent.parent.parent.parent.w - 12) / 4; height: 4; radius: 2
                                color: index < (Backend.you.strength || 0) ? ["#EF4444", "#F59E0B", "#84CC16", Theme.t.accent][(Backend.you.strength || 1) - 1] : Theme.t.hover } } } }
                        Column { spacing: 5; Label { text: "Password again"; secondary: true; font.pixelSize: 12 }
                            TextBox { objectName: "again"; width: parent.parent.w; secret: true; onEdited: Backend.setYou("again", text) }
                            Label { text: Backend.you.hasPassword && !Backend.you.same ? "Not the same yet" : ""; color: Theme.t.danger; font.pixelSize: 11 } }
                        Column { spacing: 5; Label { text: "Computer name"; secondary: true; font.pixelSize: 12 }
                            TextBox { objectName: "hostname"; width: parent.parent.w; mono: true; text: Backend.you.hostname || ""; onEdited: Backend.setYou("hostname", text) }
                            Label { text: "How it shows to other computers on the network"; secondary: true; font.pixelSize: 11 } }
                    }
                    Rectangle { anchors { bottom: parent.bottom; left: parent.left; right: parent.right } height: 64; radius: 16; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine
                        Row { x: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 12
                            Glyph { name: "key"; size: 20; anchors.verticalCenter: parent.verticalCenter }
                            Column { anchors.verticalCenter: parent.verticalCenter; Label { text: "Sign in by myself"; font.weight: Font.DemiBold }
                                Label { text: "Skip the sign-in screen. Anyone at this computer could use it."; secondary: true; font.pixelSize: 12 } } }
                        Toggle { anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter } on: !!Backend.you.autologin
                            onToggled: function (v) { Backend.setYou("autologin", v ? "true" : "false") } } }
                }

                // ---------------------------------------------------- time zone
                // The zones in a list the backend filters (ZoneModel): suggested ones for the language's country on
                // top, then them all; a search matches cities, countries, "Central", CST or UTC−6, every word of it.
                Item { visible: win.stepId === "time"; anchors.fill: parent
                    Rectangle { id: zoneNow; width: parent.width; height: 74; radius: 16; color: Qt.alpha(Theme.t.accent, 0.14); border.width: 1; border.color: Theme.t.accent
                        Row { x: 18; anchors.verticalCenter: parent.verticalCenter; spacing: 14
                            Glyph { name: "globe"; size: 26; ink: Theme.t.accent; anchors.verticalCenter: parent.verticalCenter }
                            Column { anchors.verticalCenter: parent.verticalCenter; spacing: 2
                                Label { objectName: "zoneCity"; text: Backend.zoneCity; font.pixelSize: 17; font.weight: Font.DemiBold }
                                Label { text: Backend.zonePlace; secondary: true; font.pixelSize: 12 } } }
                        Column { anchors { right: parent.right; rightMargin: 20; verticalCenter: parent.verticalCenter } spacing: 2
                            Label { anchors.right: parent.right; objectName: "zoneClock"; font.pixelSize: 20; font.weight: Font.Light
                                text: Backend.zoneModel.minute !== undefined ? Backend.zoneModel.clock(Backend.zone) : "" }
                            Label { anchors.right: parent.right; text: Backend.zoneOffset; secondary: true; font.pixelSize: 12 } } }
                    TextBox { id: zoneSearch; objectName: "zoneSearch"; anchors { top: zoneNow.bottom; topMargin: 14 } width: parent.width
                        placeholder: "Search for a city, a country or a zone (Central, CST, UTC−6)"
                        onEdited: Backend.zoneModel.setFilter(text)
                        onAccepted: if (zoneList.count > 0) { var it = zoneList.itemAtIndex(0); if (it) Backend.setZone(it.zid) } }
                    Rectangle { anchors { top: zoneSearch.bottom; topMargin: 10; left: parent.left; right: parent.right; bottom: parent.bottom }
                        radius: 14; color: Theme.t.group; border.width: 1; border.color: Theme.t.islandLine; clip: true
                        ListView { id: zoneList; objectName: "zoneList"; anchors.fill: parent; anchors.margins: 6; spacing: 2; clip: true; reuseItems: true
                            model: Backend.zoneModel
                            boundsBehavior: Flickable.StopAtBounds
                            section.property: "group"
                            section.delegate: Item { required property string section; width: zoneList.width; height: 28
                                Label { x: 14; anchors { bottom: parent.bottom; bottomMargin: 5 } text: section; secondary: true; font.pixelSize: 11
                                    font.weight: Font.DemiBold; font.capitalization: Font.AllUppercase; font.letterSpacing: 0.6 } }
                            delegate: Rectangle { id: zrow
                                required property string zid
                                required property string city
                                required property string place
                                required property string offset
                                required property string clock
                                readonly property bool chosen: zid === Backend.zone
                                width: zoneList.width; height: 38; radius: 10
                                objectName: "zone-" + zid
                                color: chosen ? Theme.t.accent : (zh.containsMouse ? Theme.t.hover : "transparent")
                                Label { id: zc; x: 14; anchors.verticalCenter: parent.verticalCenter; text: zrow.city
                                    color: zrow.chosen ? Theme.t.onAccent : Theme.t.text; font.weight: zrow.chosen ? Font.DemiBold : Font.Normal }
                                Label { anchors { left: zc.right; leftMargin: 10; right: zt.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
                                    text: zrow.place; elide: Text.ElideRight; font.pixelSize: 12; color: zrow.chosen ? Theme.t.onAccent : Theme.t.text_secondary }
                                Label { id: zt; anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
                                    text: zrow.clock + (zrow.offset ? "   " + zrow.offset : ""); font.pixelSize: 12
                                    color: zrow.chosen ? Theme.t.onAccent : Theme.t.text_secondary }
                                MouseArea { id: zh; anchors.fill: parent; hoverEnabled: true; onClicked: Backend.setZone(zrow.zid) } }
                            Label { anchors.centerIn: parent; visible: zoneList.count === 0; text: "No time zone matches that. Try the city's country, or its offset (UTC+1)."
                                secondary: true; width: parent.width - 40; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter } } }
                }

                // ---------------------------------------------------- keep it safe
                Flickable { visible: win.stepId === "safety"; anchors.fill: parent; contentHeight: Math.max(sfL.height, sfR.height) + 10; clip: true; boundsBehavior: Flickable.StopAtBounds
                    Column { id: sfL; width: parent.width * 0.56; spacing: 8
                        Label { text: "Encrypt Huginn"; font.pixelSize: 16; font.weight: Font.DemiBold }
                        Choice { objectName: "encryptOn"; title: "With a password · suggested"; on: Backend.encrypt; visible: Backend.safety.canEncrypt
                            line: "Asked for on the start screen. Moving the drive to another computer won't open it."
                            onPicked: Backend.setEncrypt(true, win.encOne === win.encTwo ? win.encOne : "") }
                        Choice { objectName: "encryptOff"; title: "Don't encrypt"; on: !Backend.encrypt; line: "Starts a touch faster. Anyone with the drive can read it."
                            onPicked: Backend.setEncrypt(false, "") }
                        Label { visible: !Backend.safety.canEncrypt; width: parent.width; wrapMode: Text.WordWrap; color: win.amber; font.pixelSize: 12
                            text: "With partitions you chose yourself, the installer can't encrypt. Erase a drive or use free space to encrypt." }
                        Row { visible: Backend.encrypt; spacing: 10; topPadding: 4
                            TextBox { objectName: "encOne"; width: (sfL.width - 10) / 2; secret: true; placeholder: "Disk password"; onEdited: { win.encOne = text; win.pushEncryption() } }
                            TextBox { objectName: "encTwo"; width: (sfL.width - 10) / 2; secret: true; placeholder: "Again"; onEdited: { win.encTwo = text; win.pushEncryption() } } }
                        Label { visible: Backend.encrypt && win.encOne !== "" && win.encTwo !== "" && win.encOne !== win.encTwo; text: "The two aren't the same."; color: Theme.t.danger; font.pixelSize: 12 }
                        Switch { objectName: "tpmUnlock"; visible: Backend.encrypt && !!Backend.safety.canTpm; title: "Open it with this computer's security chip and a PIN"
                            line: "The chip (TPM) checks the computer hasn't been tampered with; you type a short PIN instead of the password. The password still works."
                            on: !!Backend.safety.tpm; onFlipped: function (v) { Backend.setTpm(v, win.tpmPin) } }
                        TextBox { objectName: "tpmPin"; visible: !!Backend.safety.tpm; width: sfL.width / 2; secret: true; placeholder: "PIN (4 or more)"
                            onEdited: { win.tpmPin = text; Backend.setTpm(true, text) } }
                        Rectangle { objectName: "recoveryKey"; visible: Backend.encrypt; width: parent.width; height: rkCol.height + 24; radius: 14; color: Qt.rgba(0, 0, 0, 0.22); border.width: 1; border.color: win.edge
                            Column { id: rkCol; x: 14; y: 12; width: parent.width - 28; spacing: 8
                                Row { width: parent.width
                                    Label { width: parent.width - 100; text: "Your recovery key"; font.weight: Font.DemiBold }
                                    Btn { text: "New words"; onClicked: Backend.newRecoveryKey() } }
                                Flow { width: parent.width; spacing: 6
                                    Repeater { model: Backend.safety.recoveryWords || []
                                        Rectangle { required property var modelData; required property int index; width: rkW.width + 18; height: 28; radius: 8; color: Qt.rgba(1, 1, 1, 0.07)
                                            Label { id: rkW; anchors.centerIn: parent; text: (index + 1) + " " + modelData; font.family: Theme.t.fontMono; font.pixelSize: 13 } } } }
                                Label { width: parent.width; wrapMode: Text.WordWrap; color: win.ink2; font.pixelSize: 12
                                    text: "Write these down, or take a photo of them. They open Huginn if the password is forgotten; nobody, Huginn included, can open it otherwise." } } } }
                    Column { id: sfR; x: sfL.width + 22; width: parent.width - x; spacing: 4
                        Label { text: "Privacy and protection"; font.pixelSize: 16; font.weight: Font.DemiBold; bottomPadding: 4 }
                        Switch { title: "A restore point before every update"; line: "Undo an update from the start screen."; on: Backend.safety.restorePoints; onFlipped: function (v) { Backend.setSafety("restorePoints", v) } }
                        Switch { title: "Firewall"; line: "Nothing comes in unless an app asks."; on: Backend.safety.firewall; onFlipped: function (v) { Backend.setSafety("firewall", v) } }
                        Switch { title: "Security fixes by themselves"; line: "Bigger updates still ask first."; on: Backend.safety.autoUpdates; onFlipped: function (v) { Backend.setSafety("autoUpdates", v) } }
                        Label { width: parent.width; wrapMode: Text.WordWrap; color: win.ink2; font.pixelSize: 12; topPadding: 8
                            text: "Huginn never sends crash reports or anything else without asking. All of these can be changed in Settings › Privacy & Security." } }
                }

                // ---------------------------------------------------- the last look
                Flickable { visible: win.stepId === "ready"; anchors.fill: parent; contentHeight: rdCol.height + 10; clip: true; boundsBehavior: Flickable.StopAtBounds
                    Column { id: rdCol; width: parent.width; spacing: 12
                        Rectangle { width: parent.width; height: sumCol.height + 12; radius: 16; color: Qt.rgba(0, 0, 0, 0.2); border.width: 1; border.color: win.edge
                            Column { id: sumCol; objectName: "summary"; y: 6; width: parent.width
                                Repeater { model: Backend.summary
                                    Item { required property var modelData; required property int index; width: sumCol.width; height: Math.max(40, val.height + 20)
                                        Rectangle { visible: index > 0; x: 16; width: parent.width - 32; height: 1; color: win.edge }
                                        Label { x: 18; y: 11; width: 150; text: modelData.label; color: win.ink2 }
                                        Label { id: val; x: 170; y: 11; width: parent.width - 190; text: modelData.value; wrapMode: Text.WordWrap
                                            color: modelData.warn ? win.amber : Theme.t.text; font.weight: modelData.warn ? Font.DemiBold : Font.Normal } } } } }
                        Label { width: parent.width; wrapMode: Text.WordWrap; color: win.ink2; font.pixelSize: 12
                            text: Backend.mode === "erase" ? "Pressing Erase and Install deletes everything on the disk. This can't be undone."
                                  : Backend.mode === "shrink" ? "Pressing Install shrinks Windows as shown, then installs. Windows' files stay, but back up anything important first."
                                  : "Pressing Install changes the disk as shown. Back up anything important first." } }
                }

            }
        }
        // Back and Continue, in the card's foot, with what's still missing on this step
        Label { objectName: "problem"; visible: win.stepId !== "welcome" && Backend.problem !== ""; anchors { left: parent.left; leftMargin: 34; bottom: parent.bottom; bottomMargin: 30 }
            width: parent.width - 34 - 300; elide: Text.ElideRight; text: Backend.problem; color: win.ink2; font.pixelSize: 12 }
        Row { visible: win.stepId !== "welcome"; anchors { right: parent.right; rightMargin: 24; bottom: parent.bottom; bottomMargin: 18 } spacing: 10
            Rectangle { objectName: "back"; width: 92; height: 40; radius: 20; color: backHit.containsMouse ? Qt.rgba(1, 1, 1, 0.12) : Qt.rgba(1, 1, 1, 0.06); border.width: 1; border.color: win.edge
                Label { anchors.centerIn: parent; text: "Back" }
                MouseArea { id: backHit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Backend.back() } }
            Rectangle { id: goBtn; objectName: "continue"; width: goL.width + 48; height: 40; radius: 20
                readonly property bool last: win.stepId === "ready"
                readonly property bool wipe: last && Backend.mode === "erase"
                gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: goBtn.wipe ? "#FF8A65" : "#3DD6B5" } GradientStop { position: 1; color: goBtn.wipe ? "#FFB07A" : "#7BD8F0" } }
                opacity: Backend.problem === "" ? 1 : 0.6
                Label { id: goL; anchors.centerIn: parent; color: "#06231D"; font.weight: Font.DemiBold
                    text: parent.last ? (Backend.mode === "erase" ? "Erase and Install" : "Install") : "Continue" }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: parent.last ? Backend.install() : Backend.next() } } }
    }

    // ================================================================ the dock: every step an island, the orb installs
    Row {
        id: dock; objectName: "dock"
        visible: win.setup
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 22 } spacing: 10
        Pill { radius: 20; height: 62; width: tiles.width + 16; anchors.bottom: parent.bottom
            Row { id: tiles; x: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                Repeater { model: Backend.answers.filter(function (a) { return a.id !== "ready" })
                    Item { id: tile; required property var modelData; required property int index
                        objectName: "island-" + modelData.id
                        readonly property bool here: modelData.here
                        width: here ? 124 : Math.max(70, Math.min(118, Math.max(tl.implicitWidth, ta.visible ? ta.implicitWidth : 0) + 16)); height: 46
                        Behavior on width { NumberAnimation { duration: 160 * win.still; easing.type: Easing.OutCubic } }
                        Rectangle { id: lit; width: parent.width; height: tile.here ? 66 : 46; y: tile.here ? -26 : 0; radius: tile.here ? 18 : 13
                            Behavior on y { NumberAnimation { duration: 180 * win.still; easing.type: Easing.OutCubic } }
                            color: tile.here ? "transparent" : (tileHit.containsMouse && !modelData.off ? Qt.rgba(1, 1, 1, 0.08) : "transparent")
                            gradient: tile.here ? hereGrad : null
                            border.width: tile.here ? 1.5 : 0; border.color: win.teal
                            Column { anchors.centerIn: parent; spacing: 1
                                Label { id: tl; anchors.horizontalCenter: parent.horizontalCenter; text: modelData.label; font.pixelSize: tile.here ? 13 : 12; font.weight: tile.here || modelData.done ? Font.DemiBold : Font.Normal
                                    color: modelData.off ? win.ink2 : (tile.here || modelData.done ? Theme.t.text : win.ink2); opacity: modelData.off ? 0.6 : 1 }
                                Label { id: ta; anchors.horizontalCenter: parent.horizontalCenter; width: Math.min(implicitWidth, tile.width - 8); elide: Text.ElideRight
                                    visible: modelData.done || tile.here || modelData.off; text: tile.here && !modelData.done ? "now" : modelData.answer; font.pixelSize: 11
                                    color: tile.here ? "#DCF7F0" : win.teal; opacity: modelData.off ? 0.6 : 1 } } }
                        MouseArea { id: tileHit; anchors.fill: parent; hoverEnabled: true; enabled: !modelData.off; cursorShape: Qt.PointingHandCursor; onClicked: Backend.goTo(win.indexOf(modelData.id)) } } } } }
        Gradient { id: hereGrad; orientation: Gradient.Horizontal; GradientStop { position: 0; color: Qt.rgba(61 / 255, 214 / 255, 181 / 255, 0.42) } GradientStop { position: 1; color: Qt.rgba(123 / 255, 97 / 255, 255 / 255, 0.42) } }
        // the orb: the last look, then Install
        Rectangle { id: orb; objectName: "orb"; width: 62; height: 62; radius: 31; anchors.bottom: parent.bottom
            readonly property bool here: win.stepId === "ready"
            color: win.glassC; border.width: here ? 1.5 : 1; border.color: here ? win.teal : win.edge
            Rectangle { anchors.centerIn: parent; width: 30; height: 30; radius: 15; opacity: orb.here ? 1 : 0.6
                gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: "#7BF0D6" } GradientStop { position: 1; color: "#7B61FF" } } }
            Rectangle { anchors.centerIn: parent; width: 62; height: 62; radius: 31; color: "transparent"; border.width: 2; border.color: win.teal; opacity: 0.0
                SequentialAnimation on opacity { running: orb.here && win.still > 0; loops: Animation.Infinite
                    NumberAnimation { to: 0.7; duration: 900 } NumberAnimation { to: 0.0; duration: 900 } } }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: orb.here ? Backend.install() : Backend.goTo(win.indexOf("ready")) } }
    }
    Label { visible: win.setup && win.stepId === "welcome"; anchors { horizontalCenter: parent.horizontalCenter; bottom: dock.top; bottomMargin: 34 }
        text: "Each step is an island in the dock; done ones keep your answer, and the orb at the end installs."; color: "#B9C2CB"; font.pixelSize: 12 }

    // ================================================================ installing, done, or stopped
    Rectangle {
        id: runCard; objectName: "runCard"
        visible: !win.setup
        width: Math.min(820, win.width - 200); height: runCol.height + 60
        anchors.centerIn: parent; radius: 22; color: win.glassC; border.width: 1; border.color: win.edge
        scale: win.big
        Column {
            id: runCol; x: 34; y: 30; width: parent.width - 68; spacing: 16
            Label { objectName: "runTitle"; font.pixelSize: 30; font.weight: Font.Light
                text: Backend.state === "done" ? "Huginn OS is ready" : Backend.state === "error" ? "The installation stopped" : "Huginn is settling in" }
            Label { width: parent.width; wrapMode: Text.WordWrap; color: Backend.state === "error" ? Theme.t.danger : win.ink2
                text: Backend.state === "done" ? "Restart the computer, and take out the installation drive when the screen goes dark."
                    : Backend.state === "error" ? Backend.error
                    : "About " + Math.max(1, Math.round((1 - Backend.fraction) * 10)) + " minutes left · you can keep using this computer meanwhile" }
            Row { visible: Backend.state === "installing"; width: parent.width; spacing: 24
                // what's done, and what's being done
                Column { id: phases; objectName: "phases"; width: parent.width * 0.48; spacing: 7
                    Repeater { model: Backend.phases
                        Row { required property var modelData; spacing: 10
                            Rectangle { width: 18; height: 18; radius: 9; anchors.verticalCenter: parent.verticalCenter
                                color: modelData.state === "done" ? win.teal : "transparent"; border.width: modelData.state === "done" ? 0 : 1.5
                                border.color: modelData.state === "now" ? win.teal : win.edge
                                Label { anchors.centerIn: parent; visible: modelData.state === "done"; text: "✓"; color: "#06231D"; font.pixelSize: 10; font.weight: Font.Bold }
                                Rectangle { anchors.centerIn: parent; visible: modelData.state === "now"; width: 6; height: 6; radius: 3; color: win.teal } }
                            Label { text: modelData.label; color: modelData.state === "todo" ? win.ink2 : Theme.t.text; font.weight: modelData.state === "now" ? Font.DemiBold : Font.Normal } } }
                    Label { visible: Backend.later !== ""; width: parent.width; wrapMode: Text.WordWrap; color: win.ink2; font.pixelSize: 12; topPadding: 6; text: Backend.later } }
                // what's waiting on the other side
                Rectangle { id: slide; width: parent.width - phases.width - 24; height: 150; radius: 18; color: Qt.rgba(1, 1, 1, 0.05); border.width: 1; border.color: win.edge
                    visible: !win.showLog
                    property int at: 0
                    Timer { running: slide.visible; interval: 6500; repeat: true; onTriggered: { fadeSlide.restart() } }
                    SequentialAnimation { id: fadeSlide
                        NumberAnimation { target: slideCol; property: "opacity"; to: 0; duration: 250 * win.still }
                        ScriptAction { script: slide.at = (slide.at + 1) % Math.max(1, Backend.slides.length) }
                        NumberAnimation { target: slideCol; property: "opacity"; to: 1; duration: 350 * win.still } }
                    Column { id: slideCol; x: 16; y: 14; width: parent.width - 32; spacing: 6
                        Label { text: "Waiting on the other side · " + (slide.at + 1) + " of " + Backend.slides.length; color: win.ink2; font.pixelSize: 11 }
                        Row { spacing: 12
                            Image { width: 48; height: 48; source: Backend.slides.length ? Backend.slides[slide.at].icon : ""; sourceSize: Qt.size(96, 96); smooth: true; mipmap: true }
                            Label { anchors.verticalCenter: parent.verticalCenter; text: Backend.slides.length ? Backend.slides[slide.at].name : ""; font.pixelSize: 17; font.weight: Font.DemiBold } }
                        Label { width: parent.width; text: Backend.slides.length ? Backend.slides[slide.at].line : ""; color: win.ink2; wrapMode: Text.WordWrap; font.pixelSize: 13 } } }
                Rectangle { visible: win.showLog; width: parent.width - phases.width - 24; height: 150; radius: 14; color: Qt.rgba(0, 0, 0, 0.3); border.width: 1; border.color: win.edge
                    Flickable { anchors.fill: parent; anchors.margins: 10; contentHeight: logText.height; clip: true
                        onContentHeightChanged: contentY = Math.max(0, contentHeight - height)
                        Label { id: logText; width: parent.width; text: Backend.log; font.family: Theme.t.fontMono; font.pixelSize: 11; wrapMode: Text.WrapAnywhere; color: win.ink2 } } } }
            // the line of light
            Rectangle { visible: Backend.state === "installing"; objectName: "progressTrack"; width: parent.width; height: 8; radius: 4; color: Qt.rgba(1, 1, 1, 0.08)
                Rectangle { width: Math.max(8, parent.width * Backend.fraction); height: parent.height; radius: 4
                    Behavior on width { NumberAnimation { duration: 400 * win.still; easing.type: Easing.OutCubic } }
                    gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: "#3DD6B5" } GradientStop { position: 1; color: "#7B61FF" } } } }
            Rectangle { visible: Backend.state === "error"; width: parent.width; height: 150; radius: 14; color: Qt.rgba(0, 0, 0, 0.3); border.width: 1; border.color: win.edge
                Flickable { anchors.fill: parent; anchors.margins: 10; contentHeight: errLog.height; clip: true
                    onContentHeightChanged: contentY = Math.max(0, contentHeight - height)
                    Label { id: errLog; width: parent.width; text: Backend.log; font.family: Theme.t.fontMono; font.pixelSize: 11; wrapMode: Text.WrapAnywhere; color: win.ink2 } } }
            Label { visible: Backend.state === "done" && Backend.later !== ""; width: parent.width; wrapMode: Text.WordWrap; color: win.ink2; text: Backend.later }
            Row { spacing: 10
                Btn { visible: Backend.state === "installing"; text: win.showLog ? "Hide Details" : "Show Details"; onClicked: win.showLog = !win.showLog }
                Btn { visible: Backend.state === "installing"; text: "Keep Trying Huginn Meanwhile"; onClicked: win.visibility = Window.Minimized }
                Btn { visible: Backend.state === "done"; text: "Keep Trying It"; onClicked: Qt.quit() }
                Btn { visible: Backend.state === "done"; objectName: "restart"; primary: true; text: "Restart Now"; onClicked: Backend.restart() }
                Btn { visible: Backend.state === "error"; text: "Save the Log"; onClicked: { var f = Backend.saveLog(); toast.say(f ? "Saved to " + f : "Couldn't save it.", !f) } }
                Btn { visible: Backend.state === "error"; primary: true; text: "Back to the Summary"; onClicked: Backend.retry() } }
        }
    }
    Toast { id: toast; z: 50; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 110 } }
}
