//! KDE's app-menu protocol (org_kde_kwin_appmenu, resources/appmenu.xml, MIT), for one thing: the menu bars of Qt
//! apps on KDE's platform theme (App Store apps on KDE's Flatpak runtime) in the top bar. Such an app exports its menu
//! bar as com.canonical.dbusmenu and says, for each window, on which bus name and object path (set_address); the
//! window list (huginn.rs) carries that to the shell, which reads the menus (shell/huginn_appmenu.py). Apps only do
//! this while com.canonical.AppMenu.Registrar is on the bus, which the shell owns.

use std::sync::Mutex;

use smithay::{
    reexports::wayland_server::{Client, DataInit, DisplayHandle, New, Resource, Weak, backend::ClientId, protocol::wl_surface::WlSurface},
    wayland::{Dispatch2, GlobalDispatch2, compositor::with_states},
};

use crate::state::{Backend, HuginnState};

#[allow(dead_code, non_camel_case_types, unused_unsafe, unused_variables, non_upper_case_globals, non_snake_case, unused_imports)]
#[allow(missing_docs, clippy::all)]
pub mod protocol {
    use smithay::reexports::wayland_server;
    use smithay::reexports::wayland_server::protocol::*;
    pub mod __interfaces {
        use smithay::reexports::wayland_server::backend as wayland_backend;
        use smithay::reexports::wayland_server::protocol::__interfaces::*;
        wayland_scanner::generate_interfaces!("resources/appmenu.xml");
    }
    use self::__interfaces::*;
    wayland_scanner::generate_server_code!("resources/appmenu.xml");
}

use protocol::{
    org_kde_kwin_appmenu::{self, OrgKdeKwinAppmenu},
    org_kde_kwin_appmenu_manager::{self, OrgKdeKwinAppmenuManager},
};

/// Where a window's menu bar is on the session bus, as its app said.
#[derive(Default, Clone, PartialEq, Debug)]
pub struct AppMenu {
    pub service: String,
    pub path: String,
}

/// A window's menu bar, when its app said where it is.
pub fn menu_of(surface: &WlSurface) -> Option<AppMenu> {
    with_states(surface, |s| s.data_map.get::<Mutex<AppMenu>>().and_then(|m| m.lock().ok().map(|m| m.clone())))
        .filter(|m| !m.service.is_empty() && !m.path.is_empty())
}

/// A bus name (":1.42", "org.example.App") and an object path ("/MenuBar/1") as D-Bus has them; anything else is
/// dropped rather than passed on.
fn bus_name(s: &str) -> bool {
    !s.is_empty() && s.len() <= 255 && s.chars().all(|c| c.is_ascii_alphanumeric() || "_.:-".contains(c)) && s.contains('.')
}

fn object_path(s: &str) -> bool {
    s.len() <= 255
        && s.starts_with('/')
        && (s == "/" || (!s.ends_with('/') && !s.contains("//")))
        && s.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '/')
}

pub struct ManagerGlobal;
pub struct ManagerData;
pub struct MenuData(Weak<WlSurface>);

pub fn init<B: Backend + 'static>(dh: &DisplayHandle) {
    dh.create_global::<HuginnState<B>, OrgKdeKwinAppmenuManager, _>(2, ManagerGlobal);
}

impl<B: Backend + 'static> GlobalDispatch2<OrgKdeKwinAppmenuManager, HuginnState<B>> for ManagerGlobal {
    fn bind(&self, _state: &mut HuginnState<B>, _handle: &DisplayHandle, _client: &Client, resource: New<OrgKdeKwinAppmenuManager>, data_init: &mut DataInit<'_, HuginnState<B>>) {
        data_init.init(resource, ManagerData);
    }
}

impl<B: Backend + 'static> Dispatch2<OrgKdeKwinAppmenuManager, HuginnState<B>> for ManagerData {
    fn request(
        &self,
        _state: &mut HuginnState<B>,
        _client: &Client,
        _resource: &OrgKdeKwinAppmenuManager,
        request: org_kde_kwin_appmenu_manager::Request,
        _dhandle: &DisplayHandle,
        data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        if let org_kde_kwin_appmenu_manager::Request::Create { id, surface } = request {
            data_init.init(id, MenuData(surface.downgrade()));
        }
        // (release: nothing to do)
    }
}

impl MenuData {
    /// Keep (or, with None, forget) where the window's menu bar is; true when that changed.
    fn set(&self, now: Option<AppMenu>) -> bool {
        let Ok(surface) = self.0.upgrade() else { return false };
        let now = now.unwrap_or_default();
        with_states(&surface, |s| {
            s.data_map.insert_if_missing_threadsafe(|| Mutex::new(AppMenu::default()));
            let mut held = s.data_map.get::<Mutex<AppMenu>>().unwrap().lock().unwrap();
            let changed = *held != now;
            *held = now;
            changed
        })
    }
}

impl<B: Backend + 'static> Dispatch2<OrgKdeKwinAppmenu, HuginnState<B>> for MenuData {
    fn request(
        &self,
        state: &mut HuginnState<B>,
        _client: &Client,
        _resource: &OrgKdeKwinAppmenu,
        request: org_kde_kwin_appmenu::Request,
        _dhandle: &DisplayHandle,
        _data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        let changed = match request {
            org_kde_kwin_appmenu::Request::SetAddress { service_name, object_path: path } => {
                let ok = bus_name(&service_name) && object_path(&path);
                self.set(ok.then_some(AppMenu { service: service_name, path }))
            }
            org_kde_kwin_appmenu::Request::Release => self.set(None),
        };
        if changed {
            state.report_windows_now();
        }
    }

    fn destroyed(&self, state: &mut HuginnState<B>, _client: ClientId, _resource: &OrgKdeKwinAppmenu) {
        if self.set(None) {
            state.report_windows_now();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{bus_name, object_path};

    #[test]
    fn addresses() {
        assert!(bus_name(":1.42") && bus_name("org.kde.kate-1234") && !bus_name("") && !bus_name("nodot") && !bus_name("a.b c"));
        assert!(object_path("/MenuBar/1") && object_path("/") && !object_path("MenuBar") && !object_path("/a//b") && !object_path("/a/"));
        assert!(!object_path("/a-b") && !bus_name(&"a.".repeat(200)));
    }
}
