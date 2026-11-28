// The layer-shell protocol itself, for the windows that asked for it (layerwindow.h): Qt's Wayland client gives
// such a window this shell integration instead of xdg-shell's, and it makes the window's zwlr_layer_surface_v1.
#pragma once

#include <QSize>
#include <QtWaylandClient/private/qwaylandshellintegration_p.h>
#include <QtWaylandClient/private/qwaylandshellsurface_p.h>

#include "qwayland-wlr-layer-shell-unstable-v1.h"

class HuginnLayerWindow;

class HuginnLayerShell : public QtWaylandClient::QWaylandShellIntegrationTemplate<HuginnLayerShell>,
                         public QtWayland::zwlr_layer_shell_v1
{
public:
    HuginnLayerShell();
    ~HuginnLayerShell() override;
    QtWaylandClient::QWaylandShellSurface *createShellSurface(QtWaylandClient::QWaylandWindow *window) override;
};

class HuginnLayerSurface : public QtWaylandClient::QWaylandShellSurface, public QtWayland::zwlr_layer_surface_v1
{
    Q_OBJECT
public:
    HuginnLayerSurface(HuginnLayerShell *shell, QtWaylandClient::QWaylandWindow *window);
    ~HuginnLayerSurface() override;

    bool isExposed() const override { return m_configured; }
    void applyConfigure() override;
    void setWindowSize(const QSize &size) override;
    void attachPopup(QtWaylandClient::QWaylandShellSurface *popup) override;
    void setWindowGeometry(const QRect &rect) override;

protected:
    void zwlr_layer_surface_v1_configure(uint32_t serial, uint32_t width, uint32_t height) override;
    void zwlr_layer_surface_v1_closed() override;

private:
    void sendSize(const QSize &size);
    void changed();                                     // a property changed after the surface was made
    HuginnLayerShell *m_shell;
    HuginnLayerWindow *m_props;
    QSize m_pending;
    bool m_configured = false;
};
