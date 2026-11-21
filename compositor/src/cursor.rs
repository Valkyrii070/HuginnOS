//! The pointer's pictures, from the cursor theme: the arrow, and every shape apps and the compositor ask for by name
//! (cursor-shape-v1, resizing a window's edge, a link's hand, text's I-beam), each loaded the first time and kept.
use std::{collections::HashMap, io::Read, time::Duration};

use smithay::input::pointer::CursorIcon;

use tracing::warn;
use xcursor::{
    CursorTheme,
    parser::{Image, parse_xcursor},
};

static FALLBACK_CURSOR_DATA: &[u8] = include_bytes!("../resources/cursor.rgba");

pub struct Cursor {
    icons: Vec<Image>,
    size: u32,
    theme: CursorTheme,
    named: HashMap<&'static str, Vec<Image>>,
}

impl Cursor {
    pub fn load() -> Cursor {
        // Settings › Accessibility › Pointer size (kcminputrc, as KDE keeps it), else the session's
        let name = crate::input::kconfig("kcminputrc", "Mouse", "cursorTheme")
            .filter(|t| !t.is_empty())
            .or_else(|| std::env::var("XCURSOR_THEME").ok())
            .unwrap_or_else(|| "default".into());
        let size = crate::input::kconfig("kcminputrc", "Mouse", "cursorSize")
            .and_then(|s| s.parse().ok())
            .or_else(|| std::env::var("XCURSOR_SIZE").ok().and_then(|s| s.parse().ok()))
            .unwrap_or(24u32)
            .clamp(16, 128);

        let theme = CursorTheme::load(&name);
        let icons = load_icon(&theme)
            .map_err(|err| warn!("Unable to load xcursor: {}, using fallback cursor", err))
            .unwrap_or_else(|_| {
                vec![Image {
                    size: 32,
                    width: 64,
                    height: 64,
                    xhot: 1,
                    yhot: 1,
                    delay: 1,
                    pixels_rgba: Vec::from(FALLBACK_CURSOR_DATA),
                    pixels_argb: vec![], //unused
                }]
            });

        Cursor { icons, size, theme, named: HashMap::new() }
    }

    /// The picture for a shape at a scale (whole numbers: 2 on a screen at 150 %), the frame for this moment of an
    /// animated one. A shape the theme doesn't have is the arrow.
    pub fn get_image(&mut self, icon: CursorIcon, scale: u32, time: Duration) -> Image {
        let size = self.size * scale.max(1);
        if icon == CursorIcon::Default {
            return frame(time.as_millis() as u32, size, &self.icons);
        }
        let name = icon.name();
        if !self.named.contains_key(name) {
            let found = std::iter::once(name)
                .chain(icon.alt_names().iter().copied())
                .find_map(|n| load_named(&self.theme, n).ok())
                .unwrap_or_else(|| self.icons.clone());
            self.named.insert(name, found);
        }
        frame(time.as_millis() as u32, size, &self.named[name])
    }
}

fn nearest_images(size: u32, images: &[Image]) -> impl Iterator<Item = &Image> {
    // Follow the nominal size of the cursor to choose the nearest
    let nearest_image = images
        .iter()
        .min_by_key(|image| (size as i32 - image.size as i32).abs())
        .unwrap();

    images
        .iter()
        .filter(move |image| image.width == nearest_image.width && image.height == nearest_image.height)
}

fn frame(mut millis: u32, size: u32, images: &[Image]) -> Image {
    let total = nearest_images(size, images).fold(0, |acc, image| acc + image.delay);
    if total == 0 {
        return nearest_images(size, images).next().unwrap().clone();
    }
    millis %= total;

    for img in nearest_images(size, images) {
        if millis < img.delay {
            return img.clone();
        }
        millis -= img.delay;
    }

    unreachable!()
}

#[derive(thiserror::Error, Debug)]
enum Error {
    #[error("Theme has no default cursor")]
    NoDefaultCursor,
    #[error("Error opening xcursor file: {0}")]
    File(#[from] std::io::Error),
    #[error("Failed to parse XCursor file")]
    Parse,
}

fn load_icon(theme: &CursorTheme) -> Result<Vec<Image>, Error> {
    load_named(theme, "default")
}

fn load_named(theme: &CursorTheme, name: &str) -> Result<Vec<Image>, Error> {
    let icon_path = theme.load_icon(name).ok_or(Error::NoDefaultCursor)?;
    let mut cursor_file = std::fs::File::open(icon_path)?;
    let mut cursor_data = Vec::new();
    cursor_file.read_to_end(&mut cursor_data)?;
    parse_xcursor(&cursor_data).ok_or(Error::Parse)
}
