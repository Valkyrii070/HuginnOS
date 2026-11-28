#include "layershell.h"
#include "layerwindow.h"

#include <QScreen>
#include <QWindow>
#include <any>
#include <QtWaylandClient/private/qwaylanddisplay_p.h>
#include <QtWaylandClient/private/qwaylandscreen_p.h>
#include <QtWaylandClient/private/qwaylandsurface_p.h>
#include <QtWaylandClient/private/qwaylandwindow_p.h>
#include <wayland-client-core.h>

#include "wayland-xdg-shell-client-protocol.h"

HuginnLayerShell::HuginnLayerShell() : QWaylandShellIntegrationTemplate<HuginnLayerShell>(5)
{
}

HuginnLayerShell::~HuginnLayerShell()
{
    if (object() && zwlr_layer_shell_v1_get_version(object()) >= ZWLR_LAYER_SHELL_V1_DESTROY_SINCE_VERSION)
        destroy();
}

QtWaylandClient::QWaylandShellSurface *HuginnLayerShell::createShellSurface(QtWaylandClient::QWaylandWindow *window)
{
    return new HuginnLayerSurface(this, window);
}

static uint32_t versionOf(void *object)
{
    return object ? wl_proxy_get_version(static_cast<wl_proxy *>(object)) : 0;
}

HuginnLayerSurface::HuginnLayerSurface(HuginnLayerShell *shell, QtWaylandClient::QWaylandWindow *window)
    : QtWaylandClient::QWaylandShellSurface(window), m_shell(shell), m_props(HuginnLayerWindow::find(window->window()))
{
    // its screen: the one it was given (else the window's), or the one in use when it asks for that
    ::wl_output *output = nullptr;
    if (!m_props || !m_props->wantsToBeOnActiveScreen()) {
        QScreen *screen = m_props && m_props->screen() ? m_props->screen() : window->window()->screen();
        if (screen)
            if (auto *wayland = dynamic_cast<QtWaylandClient::QWaylandScreen *>(screen->handle()))
                output = wayland->output();
    }
    const uint32_t layer = m_props ? uint32_t(m_props->layer()) : uint32_t(HuginnLayerWindow::LayerTop);
    const QString scope = m_props ? m_props->scope() : QStringLiteral("window");
    init(shell->get_layer_surface(window->waylandSurface()->object(), output, layer, scope));

    auto keys = [this] {
        uint32_t k = m_props ? uint32_t(m_props->keyboardInteractivity()) : 0;
        if (k == HuginnLayerWindow::KeyboardInteractivityOnDemand && versionOf(object()) < 4)
            k = HuginnLayerWindow::KeyboardInteractivityExclusive;       // (on demand came in version 4)
        set_keyboard_interactivity(k);
    };
    if (m_props) {
        set_anchor(uint32_t(m_props->anchors()));
        set_exclusive_zone(m_props->exclusionZone());
        keys();
        connect(m_props, &HuginnLayerWindow::anchorsChanged, this, [this] {
            set_anchor(uint32_t(m_props->anchors()));
            sendSize(this->window()->window()->size());
            changed();
        });
        connect(m_props, &HuginnLayerWindow::exclusionZoneChanged, this, [this] {
            set_exclusive_zone(m_props->exclusionZone());
            changed();
        });
        connect(m_props, &HuginnLayerWindow::keyboardInteractivityChanged, this, [this, keys] {
            keys();
            changed();
        });
        connect(m_props, &HuginnLayerWindow::layerChanged, this, [this] {
            if (versionOf(object()) >= 2) {
                set_layer(uint32_t(m_props->layer()));
                changed();
            }
        });
    }
    sendSize(window->window()->size());
}

HuginnLayerSurface::~HuginnLayerSurface()
{
    if (object())
        destroy();
}

void HuginnLayerSurface::sendSize(const QSize &want)
{
    // 0 along a side it's stretched along (anchored to both ends): the compositor gives that length
    const auto a = m_props ? m_props->anchors() : HuginnLayerWindow::Anchors();
    int w = qMax(1, want.width()), h = qMax(1, want.height());
    if ((a & HuginnLayerWindow::AnchorLeft) && (a & HuginnLayerWindow::AnchorRight))
        w = 0;
    if ((a & HuginnLayerWindow::AnchorTop) && (a & HuginnLayerWindow::AnchorBottom))
        h = 0;
    set_size(uint32_t(w), uint32_t(h));
}

void HuginnLayerSurface::changed()
{
    if (m_configured)
        window()->commit();
}

void HuginnLayerSurface::setWindowSize(const QSize &size)
{
    sendSize(size);
    changed();
}

void HuginnLayerSurface::setWindowGeometry(const QRect &rect)
{
    sendSize(rect.size());
    changed();
}

void HuginnLayerSurface::zwlr_layer_surface_v1_configure(uint32_t serial, uint32_t width, uint32_t height)
{
    ack_configure(serial);
    m_pending = QSize(int(width), int(height));
    if (!m_configured) {
        m_configured = true;
        applyConfigure();
        window()->updateExposure();
    } else {
        window()->applyConfigureWhenPossible();             // (not in the middle of drawing)
    }
}

void HuginnLayerSurface::applyConfigure()
{
    // a length of 0: the window's own
    QSize size = m_pending;
    const QSize own = window()->window()->size();
    if (size.width() <= 0)
        size.setWidth(qMax(1, own.width()));
    if (size.height() <= 0)
        size.setHeight(qMax(1, own.height()));
    window()->resizeFromApplyConfigure(size);
}

void HuginnLayerSurface::zwlr_layer_surface_v1_closed()
{
    // the compositor took it away (its screen went): the window hides, and is made again when it's shown
    QWindow *w = window()->window();
    QMetaObject::invokeMethod(w, [w] { w->setVisible(false); }, Qt::QueuedConnection);
}

void HuginnLayerSurface::attachPopup(QtWaylandClient::QWaylandShellSurface *popup)
{
    // a pop-up of this window (made by xdg-shell, with no xdg parent): given this surface as its parent
    std::any role = popup->surfaceRole();
    if (auto *xdgPopup = std::any_cast<::xdg_popup *>(&role))
        get_popup(*xdgPopup);
}
