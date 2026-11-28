# Huginn's own Qt look: the platform theme (colours, fonts, icons, Open and Save through the portal, and menu bars
# shown in the top bar) and the widget style. Built in the image (scripts/build.sh) against its Qt.
#
#   cmake -S qt -B build && cmake --build build      ->  build/libhuginntheme.so, build/libhuginnstyle.so
cmake_minimum_required(VERSION 3.21)
project(huginn-qt LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_CXX_VISIBILITY_PRESET hidden)
add_link_options($<$<CONFIG:Release>:-s>)                  # (stripped: they go into the image and into updates)

find_package(Qt6 REQUIRED COMPONENTS Core Gui GuiPrivate Widgets DBus)

# The platform theme (QT_QPA_PLATFORMTHEME=huginn)
add_library(huginntheme MODULE theme/plugin.cpp theme/theme.cpp theme/menus.cpp)
target_link_libraries(huginntheme PRIVATE Qt6::Core Qt6::Gui Qt6::GuiPrivate Qt6::DBus)

# The widget style (the theme names it first; also QT_STYLE_OVERRIDE=huginn)
add_library(huginnstyle MODULE style/style.cpp)
target_link_libraries(huginnstyle PRIVATE Qt6::Core Qt6::Gui Qt6::Widgets)

# (scripts/build.sh puts them in place: <qt6 plugins>/platformthemes and <qt6 plugins>/styles)
