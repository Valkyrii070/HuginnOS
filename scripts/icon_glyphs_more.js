// More of Huginn's line glyphs, for the icon theme alone (scripts/icon_symbols.py puts these cases into Glyph.qml's
// drawing code when it draws the theme; the shell and the apps don't need them). The same 24-unit grid, the same
// helpers (line, ring, dot, box, poly) and the same 1.7 stroke. Each glyph is one line: case "name": …; break
        case "facesmile": ring(12, 12, 9); dot(9, 10, 1.1); dot(15, 10, 1.1); c.beginPath(); c.arc(12, 12.2, 4.6, 0.18 * Math.PI, 0.82 * Math.PI); c.stroke(); break
        case "facesmilebig": ring(12, 12, 9); dot(9, 9.5, 1.1); dot(15, 9.5, 1.1); c.beginPath(); c.moveTo(7.6, 13); c.lineTo(16.4, 13); c.arc(12, 13, 4.4, 0, Math.PI); c.closePath(); c.stroke(); break
        case "facesad": ring(12, 12, 9); dot(9, 10, 1.1); dot(15, 10, 1.1); c.beginPath(); c.arc(12, 18.8, 4.6, 1.22 * Math.PI, 1.78 * Math.PI); c.stroke(); break
        case "facelaugh": ring(12, 12, 9); line(7.4, 10.4, 9, 8.6, 10.6, 10.4); line(13.4, 10.4, 15, 8.6, 16.6, 10.4); c.beginPath(); c.moveTo(7.6, 13.2); c.lineTo(16.4, 13.2); c.arc(12, 13.2, 4.4, 0, Math.PI); c.closePath(); c.stroke(); break
        case "facewink": ring(12, 12, 9); dot(9, 10, 1.1); line(13.4, 10, 16.6, 10); c.beginPath(); c.arc(12, 12.2, 4.6, 0.18 * Math.PI, 0.82 * Math.PI); c.stroke(); break
        case "facesurprise": ring(12, 12, 9); dot(9, 9.5, 1.1); dot(15, 9.5, 1.1); ring(12, 15.4, 2.2); break
        case "faceangry": ring(12, 12, 9); line(7.2, 8, 10.6, 9.6); line(16.8, 8, 13.4, 9.6); dot(9, 11.4, 1.1); dot(15, 11.4, 1.1); c.beginPath(); c.arc(12, 19.4, 4.2, 1.25 * Math.PI, 1.75 * Math.PI); c.stroke(); break
        case "facecool": ring(12, 12, 9); box(6, 8.6, 5.2, 3.4, 1.2); box(12.8, 8.6, 5.2, 3.4, 1.2); line(11.2, 9.6, 12.8, 9.6); c.beginPath(); c.arc(12, 13, 4.2, 0.2 * Math.PI, 0.8 * Math.PI); c.stroke(); break
        case "facecrying": ring(12, 12, 9); dot(9, 10, 1.1); dot(15, 10, 1.1); line(8.6, 12.6, 8.6, 15.4); c.beginPath(); c.arc(12, 19.6, 4.2, 1.25 * Math.PI, 1.75 * Math.PI); c.stroke(); break
        case "facekiss": ring(12, 12, 9); dot(9, 10, 1.1); dot(15, 10, 1.1); line(11, 13.4, 13.2, 14.8, 11, 16.2, 13.2, 17.6); break
        case "faceplain": ring(12, 12, 9); dot(9, 10, 1.1); dot(15, 10, 1.1); line(8.8, 15.2, 15.2, 15.2); break
        case "facesick": ring(12, 12, 9); line(7.6, 8.6, 10.2, 11.2); line(10.2, 8.6, 7.6, 11.2); line(13.8, 8.6, 16.4, 11.2); line(16.4, 8.6, 13.8, 11.2); line(7.8, 16, 9.9, 14.6, 12, 16, 14.1, 14.6, 16.2, 16); break
        case "facetired": ring(12, 12, 9); line(7.4, 10.4, 10.6, 10.4); line(13.4, 10.4, 16.6, 10.4); ring(12, 15.6, 1.6); break
        case "faceuncertain": ring(12, 12, 9); dot(9, 10, 1.1); dot(15, 10, 1.1); line(8.8, 15.8, 15.2, 14.2); break
        case "faceworried": ring(12, 12, 9); line(7.4, 8.4, 10.4, 7.4); line(16.6, 8.4, 13.6, 7.4); dot(9, 10.6, 1.1); dot(15, 10.6, 1.1); line(8.4, 16, 10.2, 14.8, 12, 16, 13.8, 14.8, 15.6, 16); break
        case "faceangel": ring(12, 13.4, 7.8); dot(9.4, 12, 1); dot(14.6, 12, 1); c.beginPath(); c.arc(12, 14, 3.8, 0.2 * Math.PI, 0.8 * Math.PI); c.stroke(); c.beginPath(); c.ellipse(7, 1.6, 10, 3.2); c.stroke(); break
        case "facedevilish": ring(12, 13, 8.2); line(5.4, 7.6, 5, 2.8, 8.6, 5.4); line(18.6, 7.6, 19, 2.8, 15.4, 5.4); line(8, 11, 10.4, 12); line(16, 11, 13.6, 12); c.beginPath(); c.arc(12, 14, 4, 0.18 * Math.PI, 0.82 * Math.PI); c.stroke(); break
        case "faceembarrassed": ring(12, 12, 9); dot(9, 9.6, 1.1); dot(15, 9.6, 1.1); line(6.4, 13.2, 7.6, 12.2); line(17.6, 13.2, 16.4, 12.2); line(9.6, 16, 14.4, 16); break
        case "facemonkey": ring(12, 12.6, 7.2); ring(3.9, 11.4, 2.2); ring(20.1, 11.4, 2.2); dot(9.6, 11, 1); dot(14.4, 11, 1); c.beginPath(); c.arc(12, 13.4, 3.4, 0.2 * Math.PI, 0.8 * Math.PI); c.stroke(); break
        case "faceraspberry": ring(12, 12, 9); dot(9, 10, 1.1); dot(15, 10, 1.1); line(8, 14, 16, 14); box(10.4, 14, 3.2, 4, 1.6); break
        case "facesmirk": ring(12, 12, 9); dot(9, 10, 1.1); dot(15, 10, 1.1); c.beginPath(); c.arc(13.4, 12.4, 3.8, 0.1 * Math.PI, 0.62 * Math.PI); c.stroke(); line(9, 15.6, 11.8, 15.9); break
        case "indentmore": line(11, 5, 20, 5); line(11, 10, 20, 10); line(11, 15, 20, 15); line(4, 20, 20, 20); line(4, 7.5, 7.4, 10, 4, 12.5); break
        case "indentless": line(11, 5, 20, 5); line(11, 10, 20, 10); line(11, 15, 20, 15); line(4, 20, 20, 20); line(7.4, 7.5, 4, 10, 7.4, 12.5); break
        case "textltr": c.beginPath(); c.arc(10.5, 7.5, 3.5, 0.5 * Math.PI, 1.5 * Math.PI); c.stroke(); line(10.5, 4, 16, 4); line(12, 4, 12, 15); line(15, 4, 15, 15); line(4, 19, 19, 19); line(16.4, 16.6, 19, 19, 16.4, 21.4); break
        case "textrtl": c.beginPath(); c.arc(13.5, 7.5, 3.5, 1.5 * Math.PI, 0.5 * Math.PI); c.stroke(); line(8, 4, 13.5, 4); line(9, 4, 9, 15); line(12, 4, 12, 15); line(5, 19, 20, 19); line(7.6, 16.6, 5, 19, 7.6, 21.4); break
        case "jump": c.beginPath(); c.moveTo(4, 17); c.bezierCurveTo(5.5, 7.5, 14.5, 6, 18.4, 12.6); c.stroke(); line(14.4, 12.4, 18.6, 13.4, 19.6, 9.2); line(3, 20.5, 21, 20.5); break
        case "bang": line(12, 4, 12, 14.5); dot(12, 19.4, 1.5); break
        case "one": line(9.6, 8, 12.6, 5.4, 12.6, 19); line(9.4, 19, 15.6, 19); break
        case "arrowdown": line(12, 4, 12, 20); line(6, 14, 12, 20, 18, 14); break
        case "arrowup": line(12, 20, 12, 4); line(6, 10, 12, 4, 18, 10); break
        case "updown": line(8, 4, 8, 20); line(4, 8, 8, 4, 12, 8); line(16, 4, 16, 20); line(12, 16, 16, 20, 20, 16); break
        case "arrowin": line(20, 4, 9, 15); line(9, 8.4, 9, 15, 15.6, 15); break
        case "arrowout": line(9, 15, 20, 4); line(13.4, 4, 20, 4, 20, 10.6); break
        case "mailopen": poly(3, 10, 12, 4, 21, 10, 21, 20, 3, 20); line(3, 10.4, 12, 15.4, 21, 10.4); break
        case "dotbig": dot(12, 12, 5.6); break
        case "spinner": for (var s = 0; s < 8; s++) { var u = s * Math.PI / 4; dot(12 + 7.4 * Math.cos(u), 12 + 7.4 * Math.sin(u), 0.7 + s * 0.16) } break
        case "hourglass": c.beginPath(); c.moveTo(7, 3); c.lineTo(17, 3); c.lineTo(17, 6.6); c.lineTo(12, 12); c.lineTo(17, 17.4); c.lineTo(17, 21); c.lineTo(7, 21); c.lineTo(7, 17.4); c.lineTo(12, 12); c.lineTo(7, 6.6); c.closePath(); c.stroke(); line(9.6, 18.6, 14.4, 18.6); break
        case "tornado": line(3, 5, 21, 5); line(5, 9, 19, 9); line(7, 13, 16, 13); line(9, 17, 13.5, 17); line(10.5, 21, 12.5, 21); break
        case "viewcontinuous": box(5.5, 2.5, 13, 9, 1.8); box(5.5, 13, 13, 9, 1.8); break
        case "viewpaged": box(5, 3, 14, 18, 2); line(8.5, 8, 15.5, 8); line(8.5, 12, 15.5, 12); line(8.5, 16, 12.5, 16); break
        case "viewdual": box(2.5, 5, 9, 14, 1.6); box(12.5, 5, 9, 14, 1.6); break
        case "viewwrapped": line(4, 6, 20, 6); c.beginPath(); c.moveTo(4, 12); c.lineTo(17, 12); c.arc(17, 15, 3, 1.5 * Math.PI, 0.5 * Math.PI); c.lineTo(12, 18); c.stroke(); line(14.4, 15.6, 12, 18, 14.4, 20.4); line(4, 18, 8, 18); break
        case "checkbox": box(4, 4, 16, 16, 3.4); line(8, 12.2, 11, 15.2, 16.4, 9.2); break
        case "radio": ring(12, 12, 8.4); dot(12, 12, 3.6); break
        case "draghandle": dot(9, 6, 1.4); dot(15, 6, 1.4); dot(9, 12, 1.4); dot(15, 12, 1.4); dot(9, 18, 1.4); dot(15, 18, 1.4); break
        case "wifigood": c.beginPath(); c.arc(12, 19, 9.6, 1.25 * Math.PI, 1.75 * Math.PI); c.stroke(); c.beginPath(); c.arc(12, 19, 5.4, 1.25 * Math.PI, 1.75 * Math.PI); c.stroke(); dot(12, 19, 1.7); c.setLineDash([1.4, 2.2]); c.beginPath(); c.arc(12, 19, 13.8, 1.25 * Math.PI, 1.75 * Math.PI); c.stroke(); c.setLineDash([]); break
        case "wifiok": c.beginPath(); c.arc(12, 19, 5.4, 1.25 * Math.PI, 1.75 * Math.PI); c.stroke(); dot(12, 19, 1.7); c.setLineDash([1.4, 2.2]); c.beginPath(); c.arc(12, 19, 9.6, 1.25 * Math.PI, 1.75 * Math.PI); c.stroke(); c.beginPath(); c.arc(12, 19, 13.8, 1.25 * Math.PI, 1.75 * Math.PI); c.stroke(); c.setLineDash([]); break
        case "wifiweak": dot(12, 19, 1.7); c.setLineDash([1.4, 2.2]); c.beginPath(); c.arc(12, 19, 5.4, 1.25 * Math.PI, 1.75 * Math.PI); c.stroke(); c.beginPath(); c.arc(12, 19, 9.6, 1.25 * Math.PI, 1.75 * Math.PI); c.stroke(); c.beginPath(); c.arc(12, 19, 13.8, 1.25 * Math.PI, 1.75 * Math.PI); c.stroke(); c.setLineDash([]); break
        case "wifinone": c.setLineDash([1.4, 2.2]); c.beginPath(); c.arc(12, 19, 5.4, 1.25 * Math.PI, 1.75 * Math.PI); c.stroke(); c.beginPath(); c.arc(12, 19, 9.6, 1.25 * Math.PI, 1.75 * Math.PI); c.stroke(); c.beginPath(); c.arc(12, 19, 13.8, 1.25 * Math.PI, 1.75 * Math.PI); c.stroke(); c.setLineDash([]); dot(12, 19, 1.4); break
        case "cellular": box(3.5, 15, 3, 5, 1); box(8.5, 11, 3, 9, 1); box(13.5, 7, 3, 13, 1); box(18.5, 3, 3, 17, 1); break
        case "airplane": poly(12, 2.5, 13.5, 4, 13.5, 9.4, 21, 14, 21, 16, 13.5, 13.8, 13.5, 18.4, 16, 20.4, 16, 22, 12, 20.9, 8, 22, 8, 20.4, 10.5, 18.4, 10.5, 13.8, 3, 16, 3, 14, 10.5, 9.4, 10.5, 4); break
        case "gauge": c.beginPath(); c.arc(12, 15, 8.4, Math.PI, 2 * Math.PI); c.stroke(); line(12, 15, 12, 9.4); dot(12, 15, 1.5); line(3.6, 18.5, 20.4, 18.5); break
        case "gaugehigh": c.beginPath(); c.arc(12, 15, 8.4, Math.PI, 2 * Math.PI); c.stroke(); line(12, 15, 16.6, 10.6); dot(12, 15, 1.5); line(3.6, 18.5, 20.4, 18.5); break
        case "battempty": box(2.5, 7, 17, 10, 2.4); box(19.5, 10, 2, 4, 0.8); break
        case "battlow": box(2.5, 7, 17, 10, 2.4); box(19.5, 10, 2, 4, 0.8); c.fillRect(4.6, 9.1, 3.4, 5.8); break
        case "battgood": box(2.5, 7, 17, 10, 2.4); box(19.5, 10, 2, 4, 0.8); c.fillRect(4.6, 9.1, 8.4, 5.8); break
        case "battfull": box(2.5, 7, 17, 10, 2.4); box(19.5, 10, 2, 4, 0.8); c.fillRect(4.6, 9.1, 12.8, 5.8); break
        case "textcolor": line(6.4, 17, 12, 3.6, 17.6, 17); line(8.6, 12, 15.4, 12); line(4, 21, 20, 21); break
        case "rule": line(3, 12, 21, 12); line(7, 6.5, 17, 6.5); line(7, 17.5, 17, 17.5); break
        case "halignleft": line(4, 3, 4, 21); box(7.5, 6, 11, 4, 1.2); box(7.5, 14, 7, 4, 1.2); break
        case "haligncenter": line(12, 3, 12, 21); box(6, 6, 12, 4, 1.2); box(8, 14, 8, 4, 1.2); break
        case "halignright": line(20, 3, 20, 21); box(5.5, 6, 11, 4, 1.2); box(9.5, 14, 7, 4, 1.2); break
        case "playlistnext": line(4, 7, 14, 7); line(4, 12, 14, 12); line(4, 17, 10, 17); line(16.6, 13, 20, 16.4, 16.6, 19.8); line(13, 16.4, 20, 16.4); break
        case "displays": box(2, 5, 10, 8.5, 1.4); box(12, 5, 10, 8.5, 1.4); line(7, 17, 17, 17); line(12, 13.5, 12, 17); break
        case "users": ring(9.5, 8, 3.2); c.beginPath(); c.arc(9.5, 20.4, 6.2, 1.04 * Math.PI, 1.96 * Math.PI); c.stroke(); ring(16.8, 9, 2.6); c.beginPath(); c.moveTo(14.6, 14.2); c.bezierCurveTo(18.4, 12.8, 21.4, 15.4, 21.4, 19); c.stroke(); break
        case "touchpad": box(3, 5, 18, 14, 2.6); line(3, 15, 21, 15); line(12, 15, 12, 19); break
        case "dialpad": for (var r = 0; r < 4; r++) { for (var q = 0; q < 3; q++) { if (r < 3 || q === 1) dot(7 + q * 5, 4.5 + r * 5, 1.5) } } break
        case "player": box(7, 2.5, 10, 19, 2.6); ring(12, 15, 2.8); line(9.6, 6.4, 14.4, 6.4); break
        case "floppy": poly(4, 4, 17, 4, 20, 7, 20, 20, 4, 20); box(8, 4, 7.5, 5, 0.6); box(7, 13, 10, 7, 0.6); break
        case "tape": box(2.5, 5.5, 19, 13, 2.2); ring(8.4, 11, 2); ring(15.6, 11, 2); line(7, 18.5, 8.6, 15.5, 15.4, 15.5, 17, 18.5); break
        case "tablet": box(3, 4.5, 14, 15, 2.2); line(12.6, 15.4, 20.4, 7.6); line(19.6, 6.8, 21.2, 8.4); line(12.6, 15.4, 11.8, 17, 13.4, 16.2); break
