//! GTK's own protocol (gtk_shell1), for one thing: GTK apps' menu bars in the top bar. The compositor says it shows
//! menu bars (the global_menu_bar capability), so GTK hides the menu bar of an app built on GtkApplication and says
//! on which bus name and paths its menus and actions are; the window list (huginn.rs) carries that to the shell,
//! which reads them (org.gtk.Menus, org.gtk.Actions) and shows them in the app's menu. The rest of the protocol is
//! taken and left alone (focus goes through xdg-activation).

use std::sync::Mutex;

use smithay::{
    reexports::wayland_server::{Client, DataInit, DisplayHandle, New, Resource, Weak, protocol::wl_surface::WlSurface},
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
        wayland_scanner::generate_interfaces!("resources/gtk-shell.xml");
    }
    use self::__interfaces::*;
    wayland_scanner::generate_server_code!("resources/gtk-shell.xml");
}

use protocol::{gtk_shell1::{self, GtkShell1}, gtk_surface1::{self, GtkSurface1}};

/// Where a window's menus are, as its app said (gtk_surface1.set_dbus_properties).
#[derive(Default, Clone, PartialEq, Debug)]
pub struct GtkMenus {
    pub bus: String,
    pub menubar: String,
    pub app: String,
    pub window: String,
    pub app_id: String,
}

/// A window's menus, when its app said where they are.
pub fn menus_of(surface: &WlSurface) -> Option<GtkMenus> {
    with_states(surface, |s| s.data_map.get::<Mutex<GtkMenus>>().and_then(|m| m.lock().ok().map(|m| m.clone())))
        .filter(|m| !m.bus.is_empty() && !m.menubar.is_empty())
}

pub struct ShellGlobal;
pub struct ShellData;
pub struct SurfaceData(Weak<WlSurface>);

pub fn init<B: Backend + 'static>(dh: &DisplayHandle) {
    dh.create_global::<HuginnState<B>, GtkShell1, _>(4, ShellGlobal);
}

impl<B: Backend + 'static> GlobalDispatch2<GtkShell1, HuginnState<B>> for ShellGlobal {
    fn bind(&self, _state: &mut HuginnState<B>, _handle: &DisplayHandle, _client: &Client, resource: New<GtkShell1>, data_init: &mut DataInit<'_, HuginnState<B>>) {
        let shell = data_init.init(resource, ShellData);
        shell.capabilities(gtk_shell1::Capability::GlobalMenuBar as u32);
    }
}

impl<B: Backend + 'static> Dispatch2<GtkShell1, HuginnState<B>> for ShellData {
    fn request(
        &self,
        _state: &mut HuginnState<B>,
        _client: &Client,
        _resource: &GtkShell1,
        request: gtk_shell1::Request,
        _dhandle: &DisplayHandle,
        data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        if let gtk_shell1::Request::GetGtkSurface { gtk_surface, surface } = request {
            data_init.init(gtk_surface, SurfaceData(surface.downgrade()));
        }
        // (set_startup_id, system_bell, notify_launch: nothing to do)
    }
}

impl<B: Backend + 'static> Dispatch2<GtkSurface1, HuginnState<B>> for SurfaceData {
    fn request(
        &self,
        state: &mut HuginnState<B>,
        _client: &Client,
        _resource: &GtkSurface1,
        request: gtk_surface1::Request,
        _dhandle: &DisplayHandle,
        _data_init: &mut DataInit<'_, HuginnState<B>>,
    ) {
        if let gtk_surface1::Request::SetDbusProperties {
            application_id,
            menubar_path,
            window_object_path,
            application_object_path,
            unique_bus_name,
            ..
        } = request
        {
            let Ok(surface) = self.0.upgrade() else { return };
            let clean = |s: Option<String>, cap: usize| s.unwrap_or_default().chars().take(cap).collect::<String>();
            let now = GtkMenus {
                bus: clean(unique_bus_name, 255),
                menubar: clean(menubar_path, 255),
                app: clean(application_object_path, 255),
                window: clean(window_object_path, 255),
                app_id: clean(application_id, 255),
            };
            let changed = with_states(&surface, |s| {
                s.data_map.insert_if_missing_threadsafe(|| Mutex::new(GtkMenus::default()));
                let mut held = s.data_map.get::<Mutex<GtkMenus>>().unwrap().lock().unwrap();
                let changed = *held != now;
                *held = now;
                changed
            });
            if changed {
                state.report_windows_now();
            }
        }
        // (set_modal, unset_modal, present, request_focus, release: nothing to do)
    }
}
