import QtQuick
import QtQuick.Window
import org.kde.layershell 1.0 as LayerShell

// Huginn's sign-in screen (huginn_greeter.py): one full-screen layer on every screen. The main one signs you in
// (GreeterView.qml); the others show the realm's wallpaper and nothing else. The Python side is "Host".
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
            LayerShell.Window.scope: "huginn-greeter"
            LayerShell.Window.layer: LayerShell.Window.LayerOverlay
            LayerShell.Window.keyboardInteractivity: win.main ? LayerShell.Window.KeyboardInteractivityExclusive
                                                              : LayerShell.Window.KeyboardInteractivityNone
            LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
            LayerShell.Window.exclusionZone: -1

            GreeterView { anchors.fill: parent; main: win.main; focus: win.main }
        }
    }
}
