import QtQuick
import QtQuick.Window

// A floating group of controls, like one island of the dock. Lay Seg, IslandField and labels inside it.
Rectangle {
    id: isl
    default property alias items: row.data
    property bool drags: false                 // true: pressing its background moves the window (the name island)
    property int pad: 5
    property bool rtl: false                   // lay the items out from the right
    height: inBar ? host.barIh : 40; width: row.width + pad * 2; radius: inBar ? height / 2 : 16
    color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
    // A filled window shares the top bar's row (GlassWindow.qml: lifted): its top islands are as tall as the bar's
    // and take their pill shape (what's in them is 30 tall and still fits).
    property bool bar: false                   // one of the window's own two (always in the row)
    readonly property var host: Window.window
    readonly property bool inBar: !!host && host.lifted === true && y < 24 && (bar || (parent && parent.objectName === "glassOver"))
    MouseArea { anchors.fill: parent; onPressed: if (isl.drags) isl.Window.window.startSystemMove() }
    Row { id: row; x: isl.pad; height: parent.height; spacing: 4; layoutDirection: isl.rtl ? Qt.RightToLeft : Qt.LeftToRight }
}
