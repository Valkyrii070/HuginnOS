import QtQuick

// An island that runs down the side: a list of places, pages or notes. Scrolls when it is taller than its room.
Rectangle {
    id: rail
    default property alias items: col.data
    property int maxHeight: 400
    width: 220; height: Math.min(col.height + 10, maxHeight); radius: 16
    color: Theme.t.island; border.width: 1; border.color: Theme.t.islandLine
    // scroll so an item in it shows (the page that's open, say)
    property Item wanted: null
    function reveal(item) { wanted = item; revealing.restart() }
    Timer { id: revealing; interval: 60; onTriggered: rail.scrollTo(rail.wanted) }   // once it's laid out
    function scrollTo(item) {
        if (!item || fl.height <= 0) return
        var p = item.mapToItem(col, 0, 0)
        var top = fl.contentY, bottom = fl.contentY + fl.height
        var to = p.y < top ? p.y - 30 : p.y + item.height > bottom ? p.y + item.height - fl.height + 8 : top
        fl.contentY = Math.max(0, Math.min(to, col.height - fl.height))
    }
    MouseArea { anchors.fill: parent }
    Flickable { id: fl; anchors { fill: parent; margins: 5 } contentHeight: col.height; clip: true; interactive: col.height > height
        boundsBehavior: Flickable.StopAtBounds
        Column { id: col; width: parent.width; spacing: 2 } }
}
