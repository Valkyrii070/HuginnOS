# Easel
Paint, retouch and draw: pixel layers and vector layers in one picture.

## Start
Pick a size (screen, square post, A4 for printing and more) or open a picture. Easel opens PNG, JPEG, WebP, TIFF and SVG, its own .easel files, OpenRaster (.ora) files from Krita, GIMP and MyPaint, and Photoshop (.psd) files.

## Pixel and Vector
The two buttons at the top of the tools switch benches. Pixel has the brush, eraser, fill, gradient, selections, move and crop: for painting and photos. Vector has the pen, rectangles, ellipses, lines, stars and type: shapes that stay sharp at any size.

## Painting
Pick a brush (round, soft, pencil, ink, airbrush, chalk, marker) and set its size, hardness, flow and opacity in the bar at the top. Shift-click draws a straight line from the last stroke. [ and ] change the size; number keys set the opacity. A right-click picks a colour from the picture. If your hand wobbles, turn up Steady in the bar above: the brush trails the pointer a little and evens the line out, and still ends where you let go. Some brushes leave a mark that isn't a disc: Dry Bristle streaks, Charcoal has grain, the Calligraphy Pen is thick one way and thin the other, Ribbon turns with your hand, and Spray Can, Splatter and Leaves scatter as they go.

## Choosing part of the picture
Rectangle, ellipse, lasso and the magic wand choose an area; painting, filters and fills then stay inside it. Shift adds to the selection, Alt takes away. Feather softens its edge; Grow or Shrink moves it. Select › Outline… draws a line of the front colour along the selection's edge: inside it, outside it or centred on it, as wide as you like. The Quick Selection brush selects a whole thing as you drag over it (Alt takes away). Press Q for Quick Mask to paint a selection by hand: the brush adds, the eraser takes away, and Q again turns what you painted into the selection. Select › Smooth tidies a ragged selection; Select › Border selects a band along its edge.

## Layers
Add pixel layers, vector layers and adjustment layers (brightness and contrast, hue and saturation, levels, black and white and more, which change everything below without touching it). Each layer has a blend mode and opacity. Drag the arrows to reorder, click the eye to hide, the lock to protect. Besides the usual blend modes there are Hue, Saturation, Colour and Luminosity: a Colour layer tints what's under it and keeps its light and dark, which is how a black and white photograph is coloured by hand. Adjustment layers also include Exposure, Colour Balance, Threshold and Channel Mixer, and each shows the picture's tones as bars above its sliders, so you can see shadows and highlights move as you drag.

## Clipping and locked transparency
Clip a layer to the one below it (Ctrl+Alt+G, or Layer › Clip to the Layer Below) and it shows only where that layer has something: paint shading over a shape without going over its edge, or put a photo inside some lettering. Clipped layers step in under a small arrow in Layers, several can share one layer, and an adjustment clipped this way changes only that layer. The same command lets it go again.

Lock Transparency (Layer menu, or Mask and more) keeps a layer's shape as it is: brushes, Fill and gradients colour only what's already painted, and the eraser paints the back colour instead of making holes. A small grid mark shows beside the layer's name.

## Transform, clone and heal
Ctrl+T puts a box around the layer (or the selection): drag inside to move it, pull a corner to resize (Shift keeps its shape), drag outside it to turn it, and flip it from the bar. Enter applies it, Escape puts it back.
The clone stamp (S) paints a copy of another part of the picture: Alt-click where to copy from, then paint. The healing brush (J) paints over a spot or a blemish and blends it into what's around it; Alt-click a clean area first, or let Easel find one.

## Curves
An adjustment layer of the kind Curves bends the brightness of everything below, or of red, green or blue alone: click the curve to add a point and drag it, drag a point off the side to take it away.

## Masks
A mask hides parts of a layer without erasing them: white shows, black hides. Add one from the Layer button (from the selection, too), click it to paint on it, and apply or delete it later.

## Shapes and type
Draw shapes with Shift for squares and circles and Alt to draw from the middle. With Select, drag a shape, pull its handles to resize (Shift keeps its proportions) or the round handle to turn it. The bar sets fill, line, width, corner rounding, star points and opacity. Combine unites, subtracts, intersects or excludes picked shapes. The pen: click for corners, drag for curves, click the first point to close. Text: click and type.

## Filters and the Image menu
The menu (≡) has Image (canvas size, image size, rotate, flip, trim, crop to selection), Select, Layer, and Filters: blur, motion blur, sharpen, noise, pixelate, emboss, find edges, posterize, auto levels and more. Clarity lifts contrast in the midtones without the halos sharpening leaves; High Pass makes the grey layer you set to Overlay to sharpen; Reduce Noise smooths grain and keeps edges; Soft Glow and Vignette finish a photograph.

## Gradients and editing points
Shapes can be filled with a gradient: turn on Gradient in the shape bar, choose its second colour and its direction (down, across, corner to corner or round from the middle).
Points (A) edits a vector shape's outline: drag a point or its handles, click the outline to add a point, Delete takes the picked one away, and Corner ⇄ Smooth in the bar switches it between a sharp corner and a smooth curve. Convert to Outlines (in Arrange) turns type and simple shapes into editable outlines. The gradient tool's list has gradients of several colours (Sunset, Fire, Chrome and more) beside the two made from your colours; Reverse runs any of them the other way.

## Saving and exporting
Save keeps an .easel file with every layer, mask and shape. Export makes PNG, JPEG or WebP; SVG and PDF keep shapes and type as vectors; ORA keeps layers for Krita and GIMP; PSD keeps layers for Photoshop, and Easel opens PSD files too (their pixel layers, names, opacity, blend modes and hidden layers). Whatever you export looks like the picture on screen. Where the other format can't say what Easel did (an adjustment layer, a blend mode in a PDF or SVG, clipping in OpenRaster), those layers are merged in the exported file, and Easel tells you so; your own picture keeps its layers.

## Keys
B brush, E eraser, S clone stamp, J healing brush, A points, V move or select, M rectangle selection, L lasso, W wand, K fill, G gradient, I picker, T text, C crop, P pen, U rectangle, O ellipse, H hand (or hold Space), Z zoom. X swaps colours, D resets them. Ctrl+Z undo, Ctrl+Shift+Z redo, Ctrl+J duplicates the layer, Ctrl+T transforms, Ctrl+0 fits the picture, Ctrl+1 shows it at full size.

## Fill with surroundings
Choose an area round something you don't want (a wire, a passer-by, a mark), then Select → Fill with Surroundings: Easel paints it out using what's around it. Choose a little more than the thing itself.

## Text on a path
Pick a line or a curve drawn with the pen, and a piece of text, then Arrange → Text on Path: the text follows the line. Its start can be moved along it from the bar. Off Path puts it back.

## Pen pressure
With a drawing tablet, the brush gets bigger or stronger the harder you press: choose Size, Strength, Both or Neither in the brush bar.

## Trying a filter before applying it
Open any filter from the menu and the picture shows what it would do while you move its slider; nothing is changed
until you press Apply. Cancel puts the picture back.

## Refine Edge
Select › Refine Edge fits a rough selection to the edge of the thing you selected. Reach says how far either side of
your edge it may look: small for a tidy outline, larger for hair and fur.

## Brushes of your own
Select something dark on a light ground (a stamp, a leaf, a scribble) and choose Select › Make a Brush from It. It
joins the brush list as My Brush and is there next time you open Easel.

## Letter and line spacing
With the text tool, Spacing on the bar sets the room between letters and Lines the room between lines.

## Choosing by colour or tone
Select › Colour Range chooses everything of one kind: the front colour (pick it from the picture first with the
eyedropper), the highlights, midtones or shadows, or all the reds, greens and so on. Range sets how near a colour must
be. What would be chosen shows washed in a colour that stands out from the picture while the sheet is open.

## Gradients of your own
With the gradient tool, open the gradient list and choose New from This…. Click the bar to add the front colour at
that place, drag the markers to move the colours, and press Keep. Opacity makes the ringed colour see-through;
Middle moves the place where it has half turned into the next colour. Your gradients stay in the list; Change and Forget
are beside each one.
