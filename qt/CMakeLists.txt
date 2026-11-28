# Huginn's own Qt parts: the platform theme (colours, fonts, icons, Open and Save through the portal, and menu bars
# shown in the top bar), the widget style, and the shell's layer-shell windows (a QML module). Built in the image
# (scripts/build.sh) against its Qt.
#
#   cmake -S qt -B build && cmake --build build      ->  build/libhuginntheme.so, build/libhuginnstyle.so,
#                                                       build/org/huginn/layershell/ (qmldir, plugin, types)
cmake_minimum_required(VERSION 3.21)
project(huginn-qt LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_CXX_VISIBILITY_PRESET hidden)
set(CMAKE_C_VISIBILITY_PRESET hidden)
set(QT_NO_PRIVATE_MODULE_WARNING ON)                     # (yes: the theme and the layer shell use Qt's inner parts)
add_link_options($<$<CONFIG:Release>:-s>)                  # (stripped: they go into the image and into updates)

find_package(Qt6 REQUIRED COMPONENTS Core Gui GuiPrivate Widgets DBus Qml WaylandClient WaylandClientPrivate)
find_package(PkgConfig REQUIRED)
pkg_check_modules(WAYLAND REQUIRED IMPORTED_TARGET wayland-client)
pkg_get_variable(WAYLAND_PROTOCOLS_DIR wayland-protocols pkgdatadir)

# The platform theme (QT_QPA_PLATFORMTHEME=huginn)
add_library(huginntheme MODULE theme/plugin.cpp theme/theme.cpp theme/menus.cpp)
target_link_libraries(huginntheme PRIVATE Qt6::Core Qt6::Gui Qt6::GuiPrivate Qt6::DBus)

# The widget style (the theme names it first; also QT_STYLE_OVERRIDE=huginn)
add_library(huginnstyle MODULE style/style.cpp)
target_link_libraries(huginnstyle PRIVATE Qt6::Core Qt6::Gui Qt6::Widgets)

# The shell's layer-shell windows (import org.huginn.layershell 1.0)
qt_policy(SET QTP0001 NEW)
qt_add_qml_module(huginnlayershell
    URI org.huginn.layershell
    VERSION 1.0
    PLUGIN_TARGET huginnlayershell
    OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/org/huginn/layershell
    SOURCES layershell/layerwindow.h layershell/layerwindow.cpp layershell/layershell.h layershell/layershell.cpp
)
qt6_generate_wayland_protocol_client_sources(huginnlayershell PRIVATE_CODE FILES
    ${CMAKE_CURRENT_SOURCE_DIR}/layershell/wlr-layer-shell-unstable-v1.xml
    ${WAYLAND_PROTOCOLS_DIR}/stable/xdg-shell/xdg-shell.xml)
target_include_directories(huginnlayershell PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/layershell)
target_link_libraries(huginnlayershell PRIVATE Qt6::Core Qt6::Gui Qt6::GuiPrivate Qt6::Qml Qt6::WaylandClient Qt6::WaylandClientPrivate PkgConfig::WAYLAND)

# (scripts/build.sh puts them in place: <qt6 plugins>/platformthemes, <qt6 plugins>/styles and <qt6 qml>/org/huginn/layershell)
