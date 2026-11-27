import QtQuick
import QtQuick.Window
import org.kde.layershell 1.0 as LayerShell

// The lock screen under Huginn's own compositor (huginn_locker.py): the sign-in screen's own design (GreeterView.qml,
// as "Host" sees it: you alone in the dock, Sleep only), a full-screen overlay on every screen; the main one asks for
// your password, the others show the wallpaper. The compositor draws nothing else and sends keys nowhere else while
// it's up; leaving with 0 (after the wake) is what unlocks.
QtObject {
    id: root

    property Instantiator screens: Instantiator {
        model: Host.screens
        delegate: Window {
            id: win
            required property var modelData
            required property int index
            readonly property bool main: index === 0
            visible: true
            color: "black"
            LayerShell.Window.screen: modelData
            LayerShell.Window.wantsToBeOnActiveScreen: false
            LayerShell.Window.scope: "huginn-lock"
            LayerShell.Window.layer: LayerShell.Window.LayerOverlay
            LayerShell.Window.keyboardInteractivity: win.main ? LayerShell.Window.KeyboardInteractivityExclusive
                                                              : LayerShell.Window.KeyboardInteractivityNone
            LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
            LayerShell.Window.exclusionZone: -1

            GreeterView { anchors.fill: parent; main: win.main; focus: win.main }
        }
    }
}
