#include "layerwindow.h"
#include "layershell.h"

#include <QHash>
#include <QLoggingCategory>
#include <QtWaylandClient/private/qwaylanddisplay_p.h>
#include <QtWaylandClient/private/qwaylandwindow_p.h>

Q_LOGGING_CATEGORY(HUGINN_LAYER, "huginn.layershell")

static QHash<QWindow *, HuginnLayerWindow *> s_windows;

HuginnLayerWindow::HuginnLayerWindow(QWindow *window) : QObject(window), m_window(window)
{
    s_windows.insert(window, this);
    connect(window, &QObject::destroyed, window, [window] { s_windows.remove(window); });

    // The window's own platform window, without its surface's role yet: told to take a layer surface when it shows
    window->create();
    auto *wayland = dynamic_cast<QtWaylandClient::QWaylandWindow *>(window->handle());
    if (!wayland) {
        qCWarning(HUGINN_LAYER) << window << "isn't a Wayland window: it stays an ordinary one";
        return;
    }
    static HuginnLayerShell *shell = nullptr;
    static bool tried = false;
    if (!tried) {
        tried = true;
        auto *made = new HuginnLayerShell;
        if (made->initialize(wayland->display()))
            shell = made;                                  // (kept for the app's life)
        else
            qCWarning(HUGINN_LAYER) << "The compositor doesn't offer layer-shell: windows stay ordinary ones";
    }
    if (shell)
        wayland->setShellIntegration(shell);
}

HuginnLayerWindow *HuginnLayerWindow::find(QWindow *window)
{
    return s_windows.value(window, nullptr);
}

HuginnLayerWindow *HuginnLayerWindow::get(QWindow *window)
{
    if (!window)
        return nullptr;
    if (auto *have = find(window))
        return have;
    return new HuginnLayerWindow(window);
}

HuginnLayerWindow *HuginnLayerWindow::qmlAttachedProperties(QObject *object)
{
    return get(qobject_cast<QWindow *>(object));
}

void HuginnLayerWindow::setLayer(Layer layer)
{
    if (layer != m_layer) {
        m_layer = layer;
        emit layerChanged();
    }
}

void HuginnLayerWindow::setAnchors(Anchors anchors)
{
    if (anchors != m_anchors) {
        m_anchors = anchors;
        emit anchorsChanged();
    }
}

void HuginnLayerWindow::setExclusionZone(int zone)
{
    if (zone != m_zone) {
        m_zone = zone;
        emit exclusionZoneChanged();
    }
}

void HuginnLayerWindow::setKeyboardInteractivity(KeyboardInteractivity keys)
{
    if (keys != m_keys) {
        m_keys = keys;
        emit keyboardInteractivityChanged();
    }
}

void HuginnLayerWindow::setScope(const QString &scope)
{
    if (scope != m_scope) {
        m_scope = scope;
        emit scopeChanged();
    }
}

void HuginnLayerWindow::setScreen(QScreen *screen)
{
    if (screen != m_screen) {
        m_screen = screen;
        if (screen && m_window)
            m_window->setScreen(screen);                    // (so Qt draws for that screen's scale)
        emit screenChanged();
    }
}

void HuginnLayerWindow::setWantsToBeOnActiveScreen(bool on)
{
    if (on != m_active) {
        m_active = on;
        emit wantsToBeOnActiveScreenChanged();
    }
}
